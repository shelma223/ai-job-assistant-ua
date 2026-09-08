import asyncio
import html
import os
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode
from xml.etree import ElementTree

import httpx


DOU_RSS_URL = "https://jobs.dou.ua/vacancies/feeds/"
JOOBLE_API_URL = "https://ua.jooble.org/api/{api_key}"
JOBICY_API_URL = "https://jobicy.com/api/v2/remote-jobs"
REMOTIVE_API_URL = "https://remotive.com/api/remote-jobs"

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 JobAssistantBot/1.0",
    "Accept": "application/json, application/rss+xml, application/xml, text/xml, */*",
}

JOOBLE_CACHE_TTL_SECONDS = 3600
_jooble_cache: dict[tuple, tuple[float, list[dict]]] = {}


def _clean_text(value: object, fallback: str = "Не вказано") -> str:
    if value is None:
        return fallback
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or fallback


def _salary_number(value: str | None) -> int | None:
    if not value:
        return None
    numbers = re.findall(r"\d[\d\s.,]*", value)
    if not numbers:
        return None
    digits = re.sub(r"\D", "", numbers[0])
    return int(digits) if digits else None


def _salary_currency(value: str | None) -> str | None:
    lowered = (value or "").casefold()
    if "$" in lowered or "usd" in lowered:
        return "USD"
    if "€" in lowered or "eur" in lowered:
        return "EUR"
    if "₴" in lowered or "uah" in lowered or "грн" in lowered:
        return "UAH"
    return None


def _looks_remote(text: str) -> bool:
    lowered = text.casefold()
    return any(word in lowered for word in ("remote", "віддалено", "віддалена", "дистанційно"))


def _matches_work_format(vacancy: dict, work_format: str | None) -> bool:
    if not work_format:
        return True

    combined = " ".join(
        str(vacancy.get(key, ""))
        for key in ("title", "location", "job_type", "description")
    ).casefold()

    if work_format == "Віддалено":
        return _looks_remote(combined)
    if work_format == "Гібрид":
        return "hybrid" in combined or "гібрид" in combined
    if work_format == "Офіс":
        return not _looks_remote(combined) and "hybrid" not in combined and "гібрид" not in combined
    return True


def _matches_city(vacancy: dict, city: str | None, work_format: str | None) -> bool:
    if not city or city.casefold() in {
        "будь-де",
        "будь де",
        "неважливо",
        "не важно",
        "anywhere",
    }:
        return True
    if work_format == "Віддалено":
        return True

    location = str(vacancy.get("location", "")).casefold()
    city_words = [word for word in re.split(r"[,/\s]+", city.casefold()) if len(word) > 2]
    return not location or location == "не вказано" or any(word in location for word in city_words)


def _matches_salary(vacancy: dict, minimum_salary: str | None) -> bool:
    requested = _salary_number(minimum_salary)
    offered = _salary_number(str(vacancy.get("salary", "")))
    requested_currency = _salary_currency(minimum_salary)
    offered_currency = _salary_currency(str(vacancy.get("salary", "")))
    # Не порівнюємо суми в різних валютах і не ховаємо вакансії без зарплати.
    if requested is None or offered is None:
        return True
    if requested_currency and offered_currency and requested_currency != offered_currency:
        return True
    return offered >= requested


def _matches_employment(vacancy: dict, employment_type: str) -> bool:
    if employment_type == "Any":
        return True

    value = str(vacancy.get("job_type", "")).casefold()
    if not value or value == "не вказано":
        return True

    aliases = {
        "Full-Time": ("full-time", "full time", "повна", "полная"),
        "Part-Time": ("part-time", "part time", "часткова", "частичная"),
        "Freelance": ("freelance", "фриланс"),
        "Contract": ("contract", "контракт"),
    }
    return any(alias in value for alias in aliases.get(employment_type, ()))


def _matches_experience(vacancy: dict, experience_level: str | None) -> bool:
    if not experience_level or experience_level == "Будь-який":
        return True
    text = f"{vacancy.get('title', '')} {vacancy.get('description', '')}".casefold()
    aliases = {
        "Без досвіду": ("без досвіду", "no experience", "trainee", "стажер", "intern"),
        "Junior": ("junior", "trainee", "intern", "початківець", "без досвіду"),
        "Middle": ("middle", "mid-level", "2+ years", "3+ years", "2 рок", "3 рок"),
        "Senior": ("senior", "lead", "5+ years", "5 рок", "6+ years"),
    }
    markers = aliases.get(experience_level, ())
    all_markers = tuple(word for values in aliases.values() for word in values)
    return not any(word in text for word in all_markers) or any(word in text for word in markers)


def _matches_hours(vacancy: dict, hours_per_day: str | None) -> bool:
    if not hours_per_day or hours_per_day == "Будь-які":
        return True
    text = f"{vacancy.get('job_type', '')} {vacancy.get('description', '')}".casefold()
    known_markers = (
        "part-time", "part time", "неповн", "4 год", "4 hour",
        "6 год", "6 hour", "8 год", "8 hour", "full-time", "full time",
    )
    if not any(word in text for word in known_markers):
        return True
    if hours_per_day == "До 4 годин":
        return any(word in text for word in ("part-time", "part time", "неповн", "4 год", "4 hour"))
    if hours_per_day == "До 6 годин":
        return not any(word in text for word in ("8 год", "8 hour", "full-time", "full time"))
    if hours_per_day == "8 годин":
        return not any(word in text for word in ("part-time", "part time", "неповн", "4 год", "4 hour"))
    return True


def _published_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = (
            parsedate_to_datetime(text)
            if "," in text
            else datetime.fromisoformat(text.replace("Z", "+00:00"))
        )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _matches_freshness(vacancy: dict, posted_within: str | None) -> bool:
    days = {"За добу": 1, "За 3 дні": 3, "За тиждень": 7}.get(posted_within or "")
    if days is None:
        return True
    published = _published_datetime(vacancy.get("published_at"))
    return published is None or published >= datetime.now(timezone.utc) - timedelta(days=days)


def _matches_exclusions(vacancy: dict, excluded_keywords: str | None) -> bool:
    if not excluded_keywords:
        return True
    text = " ".join(
        str(vacancy.get(key, "")) for key in ("title", "company", "description")
    ).casefold()
    words = [
        word.strip().casefold()
        for word in re.split(r"[,;\n]+", excluded_keywords)
        if word.strip()
    ]
    return not any(word in text for word in words)


async def _fetch_jooble(
    client: httpx.AsyncClient,
    search_query: str,
    city: str | None,
    minimum_salary: str | None,
    limit: int,
) -> list[dict]:
    api_key = os.getenv("JOOBLE_API_KEY", "").strip()
    if not api_key:
        return []

    normalized_city = (city or "").strip()
    if normalized_city.casefold() in {"неважливо", "не важно", "будь-де", "anywhere"}:
        normalized_city = "Україна"

    payload: dict[str, object] = {
        "keywords": search_query,
        "location": normalized_city or "Україна",
        "page": 1,
        "ResultOnPage": min(max(limit * 2, 10), 20),
    }
    salary = _salary_number(minimum_salary)
    if salary and _salary_currency(minimum_salary) in {None, "UAH"}:
        payload["salary"] = salary

    cache_key = tuple(sorted((key, str(value)) for key, value in payload.items()))
    cached = _jooble_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < JOOBLE_CACHE_TTL_SECONDS:
        return [dict(item) for item in cached[1]]

    response = await client.post(JOOBLE_API_URL.format(api_key=api_key), json=payload)
    response.raise_for_status()

    vacancies = []
    for item in response.json().get("jobs", []):
        url = str(item.get("link", "")).strip()
        if not url:
            continue
        vacancies.append(
            {
                "title": _clean_text(item.get("title")),
                "company": _clean_text(item.get("company")),
                "location": _clean_text(item.get("location")),
                "job_type": _clean_text(item.get("type")),
                "salary": _clean_text(item.get("salary")),
                "source": "Jooble Україна",
                "url": url,
                "description": _clean_text(item.get("snippet"), ""),
                "published_at": item.get("updated"),
            }
        )
    _jooble_cache[cache_key] = (time.monotonic(), [dict(item) for item in vacancies])
    return vacancies


def _parse_dou_title(raw_title: str) -> tuple[str, str, str, str]:
    title = raw_title.strip()
    company = "Не вказано"
    details = ""

    if " в " in title:
        title, remainder = title.split(" в ", 1)
        company, separator, details = remainder.partition(", ")
        if not separator:
            details = ""

    salary_match = re.search(
        r"(?:від\s+)?(?:\$|€|£|₴)?\s*\d[\d\s]*(?:[–—-]\s*(?:\$|€|£|₴)?\s*\d[\d\s]*)?\s*(?:USD|EUR|UAH|грн)?",
        details,
        flags=re.IGNORECASE,
    )
    salary = salary_match.group(0).strip(" ,") if salary_match else "Не вказано"
    location = details
    if salary_match:
        location = (details[: salary_match.start()] + details[salary_match.end() :]).strip(" ,")

    return (
        _clean_text(title),
        _clean_text(company),
        _clean_text(location),
        _clean_text(salary),
    )


async def _fetch_dou(
    client: httpx.AsyncClient,
    search_query: str,
) -> list[dict]:
    url = f"{DOU_RSS_URL}?{urlencode({'search': search_query})}"
    response = await client.get(url)
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)

    vacancies = []
    for item in root.findall("./channel/item"):
        raw_title = item.findtext("title", default="")
        link = item.findtext("link", default="").strip()
        if not link:
            continue
        title, company, location, salary = _parse_dou_title(raw_title)
        description = _clean_text(item.findtext("description", default=""), "")
        vacancies.append(
            {
                "title": title,
                "company": company,
                "location": location,
                "job_type": "Не вказано",
                "salary": salary,
                "source": "DOU",
                "url": link,
                "description": description,
                "published_at": item.findtext("pubDate", default=""),
            }
        )
    return vacancies


async def _fetch_jobicy(
    client: httpx.AsyncClient,
    search_query: str,
    region: str,
    limit: int,
) -> list[dict]:
    params: dict[str, object] = {"count": min(max(limit * 2, 10), 50), "tag": search_query}
    if region != "Anywhere":
        params["geo"] = region

    response = await client.get(JOBICY_API_URL, params=params)
    response.raise_for_status()

    vacancies = []
    for item in response.json().get("jobs", []):
        url = str(item.get("url", "")).strip()
        if not url:
            continue
        vacancies.append(
            {
                "title": _clean_text(item.get("jobTitle")),
                "company": _clean_text(item.get("companyName")),
                "location": _clean_text(item.get("jobGeo")),
                "job_type": _clean_text(item.get("jobType")),
                "salary": _clean_text(item.get("annualSalaryMin")),
                "source": "Jobicy",
                "url": url,
                "description": _clean_text(item.get("jobExcerpt"), ""),
                "published_at": item.get("pubDate") or item.get("jobPosted"),
            }
        )
    return vacancies


async def _fetch_remotive(
    client: httpx.AsyncClient,
    search_query: str,
    limit: int,
) -> list[dict]:
    response = await client.get(
        REMOTIVE_API_URL,
        params={"search": search_query, "limit": min(max(limit * 2, 10), 50)},
    )
    response.raise_for_status()

    vacancies = []
    for item in response.json().get("jobs", []):
        url = str(item.get("url", "")).strip()
        if not url:
            continue
        vacancies.append(
            {
                "title": _clean_text(item.get("title")),
                "company": _clean_text(item.get("company_name")),
                "location": _clean_text(item.get("candidate_required_location")),
                "job_type": _clean_text(item.get("job_type")),
                "salary": _clean_text(item.get("salary")),
                "source": "Remotive",
                "url": url,
                "description": _clean_text(item.get("description"), ""),
                "published_at": item.get("publication_date"),
            }
        )
    return vacancies


def _round_robin(groups: list[list[dict]], limit: int) -> list[dict]:
    result: list[dict] = []
    seen_urls: set[str] = set()
    position = 0

    while len(result) < limit:
        added = False
        for group in groups:
            if position >= len(group):
                continue
            added = True
            vacancy = group[position]
            url = vacancy["url"].split("?", 1)[0].rstrip("/")
            if url not in seen_urls:
                seen_urls.add(url)
                result.append(vacancy)
                if len(result) == limit:
                    break
        if not added:
            break
        position += 1

    return result


async def get_vacancies(
    search_query: str,
    region: str = "Anywhere",
    employment_type: str = "Any",
    limit: int = 5,
    city: str | None = None,
    work_format: str | None = None,
    minimum_salary: str | None = None,
    experience_level: str | None = None,
    hours_per_day: str | None = None,
    posted_within: str | None = None,
    salary_required: bool = False,
    excluded_keywords: str | None = None,
) -> list[dict]:
    """Отримує вакансії з кількох джерел; помилка одного сайту не зупиняє інші."""
    timeout = httpx.Timeout(15.0, connect=10.0)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers=REQUEST_HEADERS,
    ) as client:
        tasks = [
            _fetch_jooble(client, search_query, city, minimum_salary, limit),
            _fetch_dou(client, search_query)
            if region in {"Anywhere", "Europe", "Ukraine"}
            else asyncio.sleep(0, result=[]),
            _fetch_jobicy(client, search_query, region, limit),
            _fetch_remotive(client, search_query, limit),
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

    groups: list[list[dict]] = []
    for response in responses:
        if isinstance(response, BaseException):
            continue
        filtered = [
            vacancy
            for vacancy in response
            if _matches_employment(vacancy, employment_type)
            and _matches_work_format(vacancy, work_format)
            and _matches_city(vacancy, city, work_format)
            and _matches_salary(vacancy, minimum_salary)
            and _matches_experience(vacancy, experience_level)
            and _matches_hours(vacancy, hours_per_day)
            and _matches_freshness(vacancy, posted_within)
            and _matches_exclusions(vacancy, excluded_keywords)
            and (
                not salary_required
                or vacancy.get("salary") not in {None, "", "Не вказано"}
            )
        ]
        groups.append(filtered)

    return _round_robin(groups, limit)
