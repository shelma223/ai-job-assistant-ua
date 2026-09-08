import asyncio
import os
import re
from hashlib import sha256

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from job_sources import get_vacancies


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_NAME = "job_assistant.db"
MAX_PROFILES = 5

dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")


class ProfileWizard(StatesGroup):
    job_query = State()
    city = State()
    work_format = State()
    region = State()
    employment_type = State()
    experience_level = State()
    hours_per_day = State()
    salary = State()
    salary_required = State()
    posted_within = State()
    excluded_keywords = State()
    skills = State()


class ProfileEdit(StatesGroup):
    waiting_value = State()


BTN_SEARCH = "🔎 Знайти вакансії"
BTN_PROFILES = "👤 Мої профілі"
BTN_FAVORITES = "⭐ Обране"
BTN_NOTIFICATIONS = "🔔 Сповіщення"
BTN_HELP = "ℹ️ Допомога"

WORK_FORMATS = ["Віддалено", "Офіс", "Гібрид"]
REGION_FILTERS = {
    "Будь-де": "Anywhere",
    "Європа": "Europe",
    "Україна": "Ukraine",
    "США": "USA",
    "Азія": "Asia",
}
EMPLOYMENT_FILTERS = {
    "Будь-яка": "Any",
    "Повна зайнятість": "Full-Time",
    "Часткова зайнятість": "Part-Time",
    "Фриланс": "Freelance",
    "Контракт": "Contract",
}
EXPERIENCE_LEVELS = ["Будь-який", "Без досвіду", "Junior", "Middle", "Senior"]
HOURS_OPTIONS = ["Будь-які", "До 4 годин", "До 6 годин", "8 годин"]
SALARY_REQUIRED_OPTIONS = ["Ні", "Так"]
FRESHNESS_OPTIONS = ["Будь-коли", "За добу", "За 3 дні", "За тиждень"]

PROFILE_COLUMNS = (
    "id, user_id, name, job_query, city, work_format, region, "
    "employment_type, salary, experience_level, hours_per_day, "
    "posted_within, salary_required, excluded_keywords, skills, is_active"
)

FIELD_LABELS = {
    "job_query": "Професія",
    "city": "Місто",
    "work_format": "Формат роботи",
    "region": "Регіон",
    "employment_type": "Зайнятість",
    "experience_level": "Досвід",
    "hours_per_day": "Робочий час",
    "salary": "Бажана зарплата",
    "salary_required": "Лише з указаною зарплатою",
    "posted_within": "Дата публікації",
    "excluded_keywords": "Стоп-слова",
    "skills": "Мої навички",
}

FIELD_CHOICES = {
    "work_format": WORK_FORMATS,
    "region": list(REGION_FILTERS),
    "employment_type": list(EMPLOYMENT_FILTERS),
    "experience_level": EXPERIENCE_LEVELS,
    "hours_per_day": HOURS_OPTIONS,
    "salary_required": SALARY_REQUIRED_OPTIONS,
    "posted_within": FRESHNESS_OPTIONS,
}

FIELD_PROMPTS = {
    "job_query": "Яку роботу ти шукаєш?\nНаприклад: Junior Python Developer.",
    "city": "У якому місті шукати? Напиши місто або «неважливо».",
    "work_format": "Обери формат роботи.",
    "region": "Обери регіон пошуку.",
    "employment_type": "Обери тип зайнятості.",
    "experience_level": "Обери свій рівень досвіду.",
    "hours_per_day": "Скільки годин на день ти готовий працювати?",
    "salary": "Напиши бажану зарплату, наприклад «від 30000 грн», або «обговорюється».",
    "salary_required": "Показувати лише вакансії, де роботодавець указав зарплату?",
    "posted_within": "Наскільки свіжими мають бути вакансії?",
    "excluded_keywords": (
        "Напиши небажані слова через кому. Наприклад: senior, casino, betting.\n"
        "Якщо обмежень немає — напиши «немає»."
    ),
    "skills": (
        "Переліч свої ключові навички через кому — вони впливатимуть на оцінку відповідності.\n"
        "Наприклад: Python, Excel, англійська B1. Якщо не хочеш — напиши «немає»."
    ),
}

WIZARD_FIELDS = [
    (ProfileWizard.job_query, "job_query"),
    (ProfileWizard.city, "city"),
    (ProfileWizard.work_format, "work_format"),
    (ProfileWizard.region, "region"),
    (ProfileWizard.employment_type, "employment_type"),
    (ProfileWizard.experience_level, "experience_level"),
    (ProfileWizard.hours_per_day, "hours_per_day"),
    (ProfileWizard.salary, "salary"),
    (ProfileWizard.salary_required, "salary_required"),
    (ProfileWizard.posted_within, "posted_within"),
    (ProfileWizard.excluded_keywords, "excluded_keywords"),
    (ProfileWizard.skills, "skills"),
]
STATE_TO_INDEX = {state.state: index for index, (state, _) in enumerate(WIZARD_FIELDS)}


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_SEARCH)],
            [KeyboardButton(text=BTN_PROFILES), KeyboardButton(text=BTN_FAVORITES)],
            [KeyboardButton(text=BTN_NOTIFICATIONS), KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def choices_keyboard(options: list[str]) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=option)] for option in options]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)


def profile_from_row(row: tuple) -> dict:
    return {
        "id": row[0],
        "user_id": row[1],
        "name": row[2],
        "job_query": row[3],
        "city": row[4],
        "work_format": row[5],
        "region": row[6],
        "employment_type": row[7],
        "salary": row[8],
        "experience_level": row[9],
        "hours_per_day": row[10],
        "posted_within": row[11],
        "salary_required": bool(row[12]),
        "excluded_keywords": row[13] or "",
        "skills": row[14] or "",
        "is_active": bool(row[15]),
    }


async def create_database() -> None:
    async with aiosqlite.connect(DATABASE_NAME) as database:
        await database.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                job_query TEXT NOT NULL,
                city TEXT,
                work_format TEXT,
                region TEXT,
                employment_type TEXT,
                salary TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await database.execute(
            """
            CREATE TABLE IF NOT EXISTS search_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                job_query TEXT NOT NULL,
                city TEXT,
                work_format TEXT,
                region TEXT,
                employment_type TEXT,
                salary TEXT,
                experience_level TEXT NOT NULL DEFAULT 'Будь-який',
                hours_per_day TEXT NOT NULL DEFAULT 'Будь-які',
                posted_within TEXT NOT NULL DEFAULT 'Будь-коли',
                salary_required INTEGER NOT NULL DEFAULT 0,
                excluded_keywords TEXT NOT NULL DEFAULT '',
                skills TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await database.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        await database.execute(
            """
            CREATE TABLE IF NOT EXISTS sent_profile_vacancies (
                profile_id INTEGER NOT NULL,
                vacancy_url TEXT NOT NULL,
                PRIMARY KEY (profile_id, vacancy_url)
            )
            """
        )
        await database.execute(
            """
            CREATE TABLE IF NOT EXISTS favorites (
                user_id INTEGER NOT NULL,
                vacancy_url TEXT NOT NULL,
                PRIMARY KEY (user_id, vacancy_url)
            )
            """
        )
        await database.execute(
            """
            CREATE TABLE IF NOT EXISTS vacancy_cache (
                vacancy_id TEXT PRIMARY KEY,
                vacancy_url TEXT NOT NULL
            )
            """
        )

        # Одноразово переносимо старий профіль у нову таблицю.
        await database.execute(
            """
            INSERT INTO search_profiles (
                user_id, name, job_query, city, work_format, region,
                employment_type, salary, is_active
            )
            SELECT
                old.user_id,
                old.job_query || ' · ' || COALESCE(old.city, 'неважливо'),
                old.job_query,
                old.city,
                old.work_format,
                COALESCE(old.region, 'Будь-де'),
                COALESCE(old.employment_type, 'Будь-яка'),
                old.salary,
                1
            FROM user_profiles AS old
            WHERE NOT EXISTS (
                SELECT 1 FROM search_profiles AS new WHERE new.user_id = old.user_id
            )
            """
        )
        await database.commit()


async def get_profiles(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DATABASE_NAME) as database:
        cursor = await database.execute(
            f"SELECT {PROFILE_COLUMNS} FROM search_profiles "
            "WHERE user_id = ? ORDER BY is_active DESC, id",
            (user_id,),
        )
        return [profile_from_row(row) for row in await cursor.fetchall()]


async def get_profile(user_id: int, profile_id: int | None = None) -> dict | None:
    query = f"SELECT {PROFILE_COLUMNS} FROM search_profiles WHERE user_id = ?"
    params: list[object] = [user_id]
    if profile_id is None:
        query += " ORDER BY is_active DESC, id LIMIT 1"
    else:
        query += " AND id = ? LIMIT 1"
        params.append(profile_id)
    async with aiosqlite.connect(DATABASE_NAME) as database:
        cursor = await database.execute(query, params)
        row = await cursor.fetchone()
    return profile_from_row(row) if row else None


async def set_active_profile(user_id: int, profile_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_NAME) as database:
        cursor = await database.execute(
            "SELECT 1 FROM search_profiles WHERE id = ? AND user_id = ?",
            (profile_id, user_id),
        )
        if not await cursor.fetchone():
            return False
        await database.execute(
            "UPDATE search_profiles SET is_active = 0 WHERE user_id = ?", (user_id,)
        )
        await database.execute(
            "UPDATE search_profiles SET is_active = 1 WHERE id = ?", (profile_id,)
        )
        await database.commit()
    return True


def profile_summary(profile: dict) -> str:
    salary_only = "так" if profile["salary_required"] else "ні"
    excluded = profile["excluded_keywords"] or "немає"
    skills = profile["skills"] or "не вказані"
    active = " ✅ активний" if profile["is_active"] else ""
    return (
        f"👤 {profile['name']}{active}\n\n"
        f"Професія: {profile['job_query']}\n"
        f"Місто: {profile['city']}\n"
        f"Формат: {profile['work_format']}\n"
        f"Регіон: {profile['region']}\n"
        f"Зайнятість: {profile['employment_type']}\n"
        f"Досвід: {profile['experience_level']}\n"
        f"Робочий час: {profile['hours_per_day']}\n"
        f"Зарплата: {profile['salary']}\n"
        f"Лише з зарплатою: {salary_only}\n"
        f"Опубліковано: {profile['posted_within']}\n"
        f"Стоп-слова: {excluded}\n"
        f"Навички: {skills}"
    )


def profiles_keyboard(profiles: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for profile in profiles:
        marker = "✅" if profile["is_active"] else "▫️"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{marker} {profile['name'][:35]}",
                    callback_data=f"profile:view:{profile['id']}",
                )
            ]
        )
    if len(profiles) < MAX_PROFILES:
        rows.append([InlineKeyboardButton(text="➕ Новий профіль", callback_data="profile:create")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profile_actions(profile_id: int, is_active: bool) -> InlineKeyboardMarkup:
    rows = []
    if not is_active:
        rows.append(
            [InlineKeyboardButton(text="✅ Зробити активним", callback_data=f"profile:select:{profile_id}")]
        )
    rows.extend(
        [
            [InlineKeyboardButton(text="✏️ Змінити поля", callback_data=f"profile:edit:{profile_id}")],
            [InlineKeyboardButton(text="🔎 Шукати за цим профілем", callback_data=f"profile:search:{profile_id}")],
            [InlineKeyboardButton(text="🗑 Видалити", callback_data=f"profile:delete:{profile_id}")],
            [InlineKeyboardButton(text="⬅️ До профілів", callback_data="profile:list")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_fields_keyboard(profile_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"field:{profile_id}:{field}")]
        for field, label in FIELD_LABELS.items()
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"profile:view:{profile_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_profiles(message: Message, user_id: int) -> None:
    profiles = await get_profiles(user_id)
    if not profiles:
        await message.answer(
            "У тебе ще немає пошукових профілів.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Створити профіль", callback_data="profile:create")]
                ]
            ),
        )
        return
    await message.answer(
        f"Твої пошукові профілі: {len(profiles)}/{MAX_PROFILES}\n"
        "Активний профіль використовується кнопкою «Знайти вакансії».",
        reply_markup=profiles_keyboard(profiles),
    )


def normalize_optional(value: str) -> str:
    return "" if value.casefold() in {"немає", "нет", "пропустити", "пропустить", "-"} else value


def validate_field(field: str, value: str) -> tuple[bool, object, str | None]:
    value = value.strip()
    if not value:
        return False, value, "Відповідь не може бути порожньою."
    if value.startswith("/"):
        return False, value, "Команда не може бути відповіддю на це запитання."
    if field in FIELD_CHOICES and value not in FIELD_CHOICES[field]:
        return False, value, "Обери один із запропонованих варіантів кнопкою."
    if field in {"job_query", "city"} and len(value) < 2:
        return False, value, "Напиши трохи точнішу відповідь."
    if field == "salary_required":
        return True, value == "Так", None
    if field in {"excluded_keywords", "skills"}:
        return True, normalize_optional(value), None
    return True, value, None


async def send_field_prompt(message: Message, field: str, step: int | None = None) -> None:
    prefix = f"Крок {step} із {len(WIZARD_FIELDS)}.\n\n" if step else ""
    keyboard = (
        choices_keyboard(FIELD_CHOICES[field])
        if field in FIELD_CHOICES
        else ReplyKeyboardRemove()
    )
    await message.answer(prefix + FIELD_PROMPTS[field], reply_markup=keyboard)


async def start_profile_creation(
    message: Message, state: FSMContext, user_id: int
) -> None:
    if len(await get_profiles(user_id)) >= MAX_PROFILES:
        await message.answer(f"Можна створити не більше {MAX_PROFILES} профілів.")
        return
    await state.clear()
    await state.set_state(ProfileWizard.job_query)
    await state.set_data({"mode": "create"})
    await send_field_prompt(message, "job_query", 1)


async def save_new_profile(user_id: int, data: dict) -> int:
    name = f"{data['job_query']} · {data['city']}"[:60]
    async with aiosqlite.connect(DATABASE_NAME) as database:
        await database.execute(
            "UPDATE search_profiles SET is_active = 0 WHERE user_id = ?", (user_id,)
        )
        cursor = await database.execute(
            """
            INSERT INTO search_profiles (
                user_id, name, job_query, city, work_format, region,
                employment_type, salary, experience_level, hours_per_day,
                posted_within, salary_required, excluded_keywords, skills, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                user_id,
                name,
                data["job_query"],
                data["city"],
                data["work_format"],
                data["region"],
                data["employment_type"],
                data["salary"],
                data["experience_level"],
                data["hours_per_day"],
                data["posted_within"],
                int(data["salary_required"]),
                data["excluded_keywords"],
                data["skills"],
            ),
        )
        await database.commit()
        return cursor.lastrowid


def words(text: str) -> set[str]:
    stop = {
        "and", "the", "for", "with", "this", "that", "або", "для", "та", "і",
        "на", "з", "в", "у", "робота", "вакансія", "developer", "specialist",
    }
    return {
        word
        for word in re.findall(r"[a-zа-яіїєґ0-9+#.]{2,}", text.casefold())
        if word not in stop
    }


def number_from_salary(value: str | None) -> int | None:
    match = re.search(r"\d[\d\s.,]*", value or "")
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group())
    return int(digits) if digits else None


def salary_currency(value: str | None) -> str | None:
    text = (value or "").casefold()
    if "$" in text or "usd" in text:
        return "USD"
    if "€" in text or "eur" in text:
        return "EUR"
    if "₴" in text or "uah" in text or "грн" in text:
        return "UAH"
    return None


def smart_match(profile: dict, vacancy: dict) -> tuple[int, list[str]]:
    title = str(vacancy.get("title", ""))
    description = str(vacancy.get("description", ""))
    location = str(vacancy.get("location", ""))
    job_type = str(vacancy.get("job_type", ""))
    combined_words = words(f"{title} {description}")
    query_words = words(profile["job_query"])
    skill_words = words(profile.get("skills", ""))

    score = 20
    reasons: list[str] = []

    query_ratio = len(query_words & combined_words) / max(len(query_words), 1)
    score += round(35 * query_ratio)
    if query_ratio >= 0.6:
        reasons.append("назва та опис добре відповідають запиту")
    elif query_ratio > 0:
        reasons.append("є частковий збіг із професією")

    if skill_words:
        skill_ratio = len(skill_words & combined_words) / len(skill_words)
        score += round(20 * skill_ratio)
        if skill_ratio >= 0.5:
            reasons.append("знайдено кілька твоїх навичок")
    else:
        score += 8

    location_text = location.casefold()
    city = str(profile.get("city", "")).casefold()
    remote_text = f"{title} {description} {location}".casefold()
    if profile.get("work_format") == "Віддалено" and any(
        word in remote_text for word in ("remote", "віддалено", "дистанційно")
    ):
        score += 10
        reasons.append("підходить віддалений формат")
    elif city and city not in {"неважливо", "не важно"} and city in location_text:
        score += 10
        reasons.append("підходить місто")
    else:
        score += 4

    wanted_type = EMPLOYMENT_FILTERS.get(profile.get("employment_type"), "Any")
    if wanted_type == "Any":
        score += 5
    elif wanted_type.casefold().replace("-", " ") in job_type.casefold().replace("-", " "):
        score += 5

    wanted_salary = number_from_salary(profile.get("salary"))
    offered_salary = number_from_salary(str(vacancy.get("salary", "")))
    wanted_currency = salary_currency(profile.get("salary"))
    offered_currency = salary_currency(str(vacancy.get("salary", "")))
    same_currency = (
        not wanted_currency or not offered_currency or wanted_currency == offered_currency
    )
    if wanted_salary and offered_salary and same_currency:
        if offered_salary >= wanted_salary:
            score += 10
            reasons.append("зарплата не нижча за бажану")
    elif not wanted_salary:
        score += 6
    else:
        score += 3

    level = profile.get("experience_level", "Будь-який")
    if level == "Будь-який":
        score += 5
    elif level.casefold() in remote_text:
        score += 5
        reasons.append("збігається рівень досвіду")
    else:
        score += 2

    score = max(20, min(score, 98))
    if not reasons:
        reasons.append("вакансія пройшла вибрані фільтри")
    return score, reasons[:3]


async def vacancies_for_profile(profile: dict, limit: int = 5) -> list[dict]:
    vacancies = await get_vacancies(
        search_query=profile["job_query"],
        region=REGION_FILTERS.get(profile["region"], "Anywhere"),
        employment_type=EMPLOYMENT_FILTERS.get(profile["employment_type"], "Any"),
        limit=max(limit * 2, 10),
        city=profile["city"],
        work_format=profile["work_format"],
        minimum_salary=profile["salary"],
        experience_level=profile["experience_level"],
        hours_per_day=profile["hours_per_day"],
        posted_within=profile["posted_within"],
        salary_required=profile["salary_required"],
        excluded_keywords=profile["excluded_keywords"],
    )
    for vacancy in vacancies:
        score, reasons = smart_match(profile, vacancy)
        vacancy["match_score"] = score
        vacancy["match_reasons"] = reasons
    vacancies.sort(key=lambda item: item["match_score"], reverse=True)
    return vacancies[:limit]


def vacancy_id_from_url(url: str) -> str:
    return sha256(url.encode("utf-8")).hexdigest()[:16]


async def cache_vacancy(url: str) -> str:
    vacancy_id = vacancy_id_from_url(url)
    async with aiosqlite.connect(DATABASE_NAME) as database:
        await database.execute(
            "INSERT OR REPLACE INTO vacancy_cache (vacancy_id, vacancy_url) VALUES (?, ?)",
            (vacancy_id, url),
        )
        await database.commit()
    return vacancy_id


def vacancy_text(number: int, vacancy: dict) -> str:
    reasons = "\n".join(f"• {reason}" for reason in vacancy.get("match_reasons", []))
    return (
        f"{number}. {vacancy['title']}\n"
        f"🏢 {vacancy['company']}\n"
        f"📍 {vacancy['location']}\n"
        f"🕒 {vacancy['job_type']}\n"
        f"💰 {vacancy['salary']}\n"
        f"🌐 {vacancy['source']}\n\n"
        f"🤖 Відповідність профілю: {vacancy.get('match_score', 50)}%\n"
        f"{reasons}"
    )


def vacancy_keyboard(vacancy_id: str, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Відкрити вакансію", url=url)],
            [
                InlineKeyboardButton(text="⭐ Зберегти", callback_data=f"favorite:{vacancy_id}"),
                InlineKeyboardButton(text="📌 Моє обране", callback_data="favorites"),
            ],
        ]
    )


async def send_vacancy_cards(
    bot: Bot, chat_id: int, vacancies: list[dict], heading: str
) -> None:
    await bot.send_message(chat_id, heading)
    for number, vacancy in enumerate(vacancies, start=1):
        vacancy_id = await cache_vacancy(vacancy["url"])
        await bot.send_message(
            chat_id,
            vacancy_text(number, vacancy),
            reply_markup=vacancy_keyboard(vacancy_id, vacancy["url"]),
        )


async def search_and_send(message: Message, bot: Bot, profile: dict) -> None:
    await message.answer(f"Шукаю вакансії за профілем «{profile['name']}»…")
    try:
        vacancies = await vacancies_for_profile(profile)
    except Exception:
        await message.answer("Не вдалося зв’язатися з джерелами. Спробуй трохи пізніше.")
        return
    if not vacancies:
        await message.answer(
            "За цими фільтрами нічого не знайдено. Спробуй послабити фільтри у профілі."
        )
        return
    await send_vacancy_cards(
        bot, message.chat.id, vacancies, f"Найкращі вакансії для «{profile['name']}»:"
    )


async def get_new_vacancies(profile: dict) -> list[dict]:
    vacancies = await vacancies_for_profile(profile)
    result = []
    async with aiosqlite.connect(DATABASE_NAME) as database:
        for vacancy in vacancies:
            cursor = await database.execute(
                "SELECT 1 FROM sent_profile_vacancies WHERE profile_id = ? AND vacancy_url = ?",
                (profile["id"], vacancy["url"]),
            )
            if not await cursor.fetchone():
                result.append(vacancy)
                await database.execute(
                    "INSERT INTO sent_profile_vacancies (profile_id, vacancy_url) VALUES (?, ?)",
                    (profile["id"], vacancy["url"]),
                )
        await database.commit()
    return result


async def send_scheduled_vacancies(bot: Bot) -> None:
    async with aiosqlite.connect(DATABASE_NAME) as database:
        cursor = await database.execute(
            "SELECT user_id FROM subscriptions WHERE enabled = 1"
        )
        subscribers = await cursor.fetchall()
    for (user_id,) in subscribers:
        for profile in await get_profiles(user_id):
            try:
                vacancies = await get_new_vacancies(profile)
                if vacancies:
                    await send_vacancy_cards(
                        bot, user_id, vacancies, f"Нові вакансії: {profile['name']}"
                    )
            except Exception:
                continue


@dp.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Зараз немає активної анкети.", reply_markup=main_keyboard())
        return
    await state.clear()
    await message.answer("Дію скасовано.", reply_markup=main_keyboard())


@dp.message(
    StateFilter(*ProfileWizard.__all_states__, ProfileEdit.waiting_value),
    F.text.startswith("/"),
)
async def reject_command_during_form(message: Message) -> None:
    await message.answer(
        "⚠️ Під час заповнення команда не може бути відповіддю. "
        "Дай відповідь на запитання або надішли /cancel."
    )


@dp.message(
    StateFilter(*ProfileWizard.__all_states__),
    F.text & ~F.text.startswith("/"),
)
async def wizard_answer(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    index = STATE_TO_INDEX[current]
    _, field = WIZARD_FIELDS[index]
    valid, value, error = validate_field(field, message.text)
    if not valid:
        await message.answer(error)
        await send_field_prompt(message, field, index + 1)
        return
    await state.update_data(**{field: value})
    if index + 1 < len(WIZARD_FIELDS):
        next_state, next_field = WIZARD_FIELDS[index + 1]
        await state.set_state(next_state)
        await send_field_prompt(message, next_field, index + 2)
        return
    data = await state.get_data()
    profile_id = await save_new_profile(message.from_user.id, data)
    await state.clear()
    profile = await get_profile(message.from_user.id, profile_id)
    await message.answer(
        "Профіль створено й зроблено активним ✅\n\n" + profile_summary(profile),
        reply_markup=main_keyboard(),
    )


@dp.message(ProfileEdit.waiting_value, F.text & ~F.text.startswith("/"))
async def edit_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile_id = data["edit_profile_id"]
    field = data["edit_field"]
    valid, value, error = validate_field(field, message.text)
    if not valid:
        await message.answer(error)
        await send_field_prompt(message, field)
        return
    profile = await get_profile(message.from_user.id, profile_id)
    if not profile:
        await state.clear()
        await message.answer("Профіль не знайдено.", reply_markup=main_keyboard())
        return
    sql_value = int(value) if field == "salary_required" else value
    async with aiosqlite.connect(DATABASE_NAME) as database:
        await database.execute(
            f"UPDATE search_profiles SET {field} = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND user_id = ?",
            (sql_value, profile_id, message.from_user.id),
        )
        if field in {"job_query", "city"}:
            updated = dict(profile)
            updated[field] = value
            name = f"{updated['job_query']} · {updated['city']}"[:60]
            await database.execute(
                "UPDATE search_profiles SET name = ? WHERE id = ?", (name, profile_id)
            )
        await database.commit()
    await state.clear()
    updated_profile = await get_profile(message.from_user.id, profile_id)
    await message.answer(
        "Зміни збережено ✅\n\n" + profile_summary(updated_profile),
        reply_markup=main_keyboard(),
    )
    await message.answer(
        "Можеш змінити ще одне поле:",
        reply_markup=edit_fields_keyboard(profile_id),
    )


@dp.message(CommandStart())
async def start_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Привіт! Я допоможу знайти вакансії та порівняю їх із твоїм профілем. 👋\n\n"
        "Користуйся кнопками нижче — запам’ятовувати команди не потрібно.",
        reply_markup=main_keyboard(),
    )


@dp.message(Command("profile"))
@dp.message(F.text == BTN_PROFILES)
async def profiles_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_profiles(message, message.from_user.id)


@dp.callback_query(F.data == "profile:list")
async def profiles_callback(callback: CallbackQuery) -> None:
    await show_profiles(callback.message, callback.from_user.id)
    await callback.answer()


@dp.callback_query(F.data == "profile:create")
async def create_profile_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await start_profile_creation(callback.message, state, callback.from_user.id)


@dp.callback_query(F.data.startswith("profile:view:"))
async def view_profile_callback(callback: CallbackQuery) -> None:
    profile_id = int(callback.data.rsplit(":", 1)[1])
    profile = await get_profile(callback.from_user.id, profile_id)
    if not profile:
        await callback.answer("Профіль не знайдено.", show_alert=True)
        return
    await callback.message.answer(
        profile_summary(profile),
        reply_markup=profile_actions(profile_id, profile["is_active"]),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("profile:select:"))
async def select_profile_callback(callback: CallbackQuery) -> None:
    profile_id = int(callback.data.rsplit(":", 1)[1])
    if not await set_active_profile(callback.from_user.id, profile_id):
        await callback.answer("Профіль не знайдено.", show_alert=True)
        return
    await callback.answer("Активний профіль змінено ✅")
    profile = await get_profile(callback.from_user.id, profile_id)
    await callback.message.answer(profile_summary(profile))


@dp.callback_query(F.data.startswith("profile:edit:"))
async def edit_profile_callback(callback: CallbackQuery) -> None:
    profile_id = int(callback.data.rsplit(":", 1)[1])
    if not await get_profile(callback.from_user.id, profile_id):
        await callback.answer("Профіль не знайдено.", show_alert=True)
        return
    await callback.message.answer(
        "Що саме хочеш змінити?",
        reply_markup=edit_fields_keyboard(profile_id),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("field:"))
async def edit_field_callback(callback: CallbackQuery, state: FSMContext) -> None:
    _, profile_id_text, field = callback.data.split(":", 2)
    profile_id = int(profile_id_text)
    if field not in FIELD_LABELS or not await get_profile(callback.from_user.id, profile_id):
        await callback.answer("Не вдалося відкрити це поле.", show_alert=True)
        return
    await state.set_state(ProfileEdit.waiting_value)
    await state.set_data({"edit_profile_id": profile_id, "edit_field": field})
    await callback.answer()
    await send_field_prompt(callback.message, field)


@dp.callback_query(F.data.startswith("profile:delete:"))
async def delete_profile_question(callback: CallbackQuery) -> None:
    profile_id = int(callback.data.rsplit(":", 1)[1])
    profile = await get_profile(callback.from_user.id, profile_id)
    if not profile:
        await callback.answer("Профіль не знайдено.", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Так, видалити", callback_data=f"profile:delete_yes:{profile_id}"
                ),
                InlineKeyboardButton(
                    text="Ні", callback_data=f"profile:view:{profile_id}"
                ),
            ]
        ]
    )
    await callback.message.answer(
        f"Видалити профіль «{profile['name']}»?", reply_markup=keyboard
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("profile:delete_yes:"))
async def delete_profile_confirm(callback: CallbackQuery) -> None:
    profile_id = int(callback.data.rsplit(":", 1)[1])
    profile = await get_profile(callback.from_user.id, profile_id)
    if not profile:
        await callback.answer("Профіль не знайдено.", show_alert=True)
        return
    async with aiosqlite.connect(DATABASE_NAME) as database:
        await database.execute(
            "DELETE FROM search_profiles WHERE id = ? AND user_id = ?",
            (profile_id, callback.from_user.id),
        )
        await database.execute(
            "DELETE FROM sent_profile_vacancies WHERE profile_id = ?", (profile_id,)
        )
        await database.commit()
    profiles = await get_profiles(callback.from_user.id)
    if profiles and not any(item["is_active"] for item in profiles):
        await set_active_profile(callback.from_user.id, profiles[0]["id"])
    await callback.answer("Профіль видалено")
    await show_profiles(callback.message, callback.from_user.id)


@dp.message(Command("vacancies"))
@dp.message(F.text == BTN_SEARCH)
async def vacancies_command(message: Message, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    profile = await get_profile(message.from_user.id)
    if not profile:
        await message.answer(
            "Спочатку створи пошуковий профіль.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Створити профіль", callback_data="profile:create")]
                ]
            ),
        )
        return
    await search_and_send(message, bot, profile)


@dp.callback_query(F.data.startswith("profile:search:"))
async def search_profile_callback(callback: CallbackQuery, bot: Bot) -> None:
    profile_id = int(callback.data.rsplit(":", 1)[1])
    profile = await get_profile(callback.from_user.id, profile_id)
    if not profile:
        await callback.answer("Профіль не знайдено.", show_alert=True)
        return
    await callback.answer()
    await search_and_send(callback.message, bot, profile)


@dp.callback_query(F.data.startswith("favorite:"))
async def save_favorite_callback(callback: CallbackQuery) -> None:
    vacancy_id = callback.data.split(":", 1)[1]
    async with aiosqlite.connect(DATABASE_NAME) as database:
        cursor = await database.execute(
            "SELECT vacancy_url FROM vacancy_cache WHERE vacancy_id = ?", (vacancy_id,)
        )
        vacancy = await cursor.fetchone()
        if not vacancy:
            await callback.answer("Вакансія вже недоступна.", show_alert=True)
            return
        await database.execute(
            "INSERT OR IGNORE INTO favorites (user_id, vacancy_url) VALUES (?, ?)",
            (callback.from_user.id, vacancy[0]),
        )
        await database.commit()
    await callback.answer("Вакансію збережено ⭐")


async def show_favorites(message: Message, user_id: int) -> None:
    async with aiosqlite.connect(DATABASE_NAME) as database:
        cursor = await database.execute(
            "SELECT vacancy_url FROM favorites WHERE user_id = ?", (user_id,)
        )
        favorites = await cursor.fetchall()
    if not favorites:
        await message.answer("В обраному поки нічого немає.")
        return
    await message.answer("Твої збережені вакансії:")
    for number, (url,) in enumerate(favorites, start=1):
        vacancy_id = await cache_vacancy(url)
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Відкрити", url=url)],
                [
                    InlineKeyboardButton(
                        text="🗑 Видалити з обраного",
                        callback_data=f"remove:{vacancy_id}",
                    )
                ],
            ]
        )
        await message.answer(f"{number}. {url}", reply_markup=keyboard)


@dp.message(Command("favorites"))
@dp.message(F.text == BTN_FAVORITES)
async def favorites_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_favorites(message, message.from_user.id)


@dp.callback_query(F.data == "favorites")
async def favorites_callback(callback: CallbackQuery) -> None:
    await show_favorites(callback.message, callback.from_user.id)
    await callback.answer()


@dp.callback_query(F.data.startswith("remove:"))
async def remove_favorite_callback(callback: CallbackQuery) -> None:
    vacancy_id = callback.data.split(":", 1)[1]
    async with aiosqlite.connect(DATABASE_NAME) as database:
        cursor = await database.execute(
            "SELECT vacancy_url FROM vacancy_cache WHERE vacancy_id = ?", (vacancy_id,)
        )
        vacancy = await cursor.fetchone()
        if not vacancy:
            await callback.answer("Вакансію не знайдено.", show_alert=True)
            return
        await database.execute(
            "DELETE FROM favorites WHERE user_id = ? AND vacancy_url = ?",
            (callback.from_user.id, vacancy[0]),
        )
        await database.commit()
    await callback.answer("Вакансію видалено")
    await callback.message.edit_reply_markup(reply_markup=None)


async def subscription_enabled(user_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_NAME) as database:
        cursor = await database.execute(
            "SELECT enabled FROM subscriptions WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
    return bool(row and row[0])


async def set_subscription(user_id: int, enabled: bool) -> None:
    async with aiosqlite.connect(DATABASE_NAME) as database:
        await database.execute(
            """
            INSERT INTO subscriptions (user_id, enabled) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET enabled = excluded.enabled
            """,
            (user_id, int(enabled)),
        )
        await database.commit()


async def show_notifications(message: Message, user_id: int) -> None:
    enabled = await subscription_enabled(user_id)
    status = "увімкнено ✅" if enabled else "вимкнено 🔕"
    action = (
        InlineKeyboardButton(text="🔕 Вимкнути", callback_data="notify:off")
        if enabled
        else InlineKeyboardButton(text="🔔 Увімкнути", callback_data="notify:on")
    )
    await message.answer(
        f"Сповіщення зараз {status}.\n"
        "Перевірка всіх профілів відбувається о 09:00 та 19:00 за Києвом.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[action]]),
    )


@dp.message(F.text == BTN_NOTIFICATIONS)
async def notifications_button(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_notifications(message, message.from_user.id)


@dp.message(Command("subscribe"))
async def subscribe_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not await get_profiles(message.from_user.id):
        await message.answer("Спочатку створи хоча б один профіль.")
        return
    await set_subscription(message.from_user.id, True)
    await message.answer("Сповіщення увімкнено ✅", reply_markup=main_keyboard())


@dp.message(Command("unsubscribe"))
async def unsubscribe_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await set_subscription(message.from_user.id, False)
    await message.answer("Сповіщення вимкнено 🔕", reply_markup=main_keyboard())


@dp.callback_query(F.data.in_({"notify:on", "notify:off"}))
async def notification_callback(callback: CallbackQuery) -> None:
    enabled = callback.data == "notify:on"
    if enabled and not await get_profiles(callback.from_user.id):
        await callback.answer("Спочатку створи профіль.", show_alert=True)
        return
    await set_subscription(callback.from_user.id, enabled)
    await callback.answer("Налаштування збережено")
    await show_notifications(callback.message, callback.from_user.id)


@dp.message(F.text == BTN_HELP)
async def help_button(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Як користуватися ботом:\n\n"
        "1. Відкрий «Мої профілі» та створи один або кілька профілів.\n"
        "2. Зроби потрібний профіль активним.\n"
        "3. Натисни «Знайти вакансії».\n"
        "4. Бот покаже процент відповідності й причини оцінки.\n"
        "5. Корисні вакансії можна додати в обране.\n\n"
        "Під час анкети команда /cancel скасовує дію.",
        reply_markup=main_keyboard(),
    )


@dp.message(F.text)
async def fallback_message(message: Message) -> None:
    await message.answer(
        "Не зовсім зрозумів повідомлення. Обери потрібну дію кнопкою нижче.",
        reply_markup=main_keyboard(),
    )


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("У файлі .env не знайдено BOT_TOKEN")
    await create_database()
    bot = Bot(token=BOT_TOKEN)
    scheduler.add_job(
        send_scheduled_vacancies,
        CronTrigger(hour="9,19", minute=0),
        args=[bot],
        id="scheduled_vacancies",
        replace_existing=True,
    )
    scheduler.start()
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
