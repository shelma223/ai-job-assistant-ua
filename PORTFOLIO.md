# Portfolio description

## Короткий опис українською

**AI Job Assistant UA** — Telegram-бот для автоматизованого пошуку вакансій з
українських і міжнародних джерел. Користувач може створити декілька пошукових
профілів, налаштувати фільтри, отримувати персоналізований рейтинг відповідності,
зберігати вакансії та вмикати регулярні сповіщення.

## Рядки для резюме українською

- Розробив Telegram-бота для пошуку та персоналізованого ранжування вакансій із
  Jooble, DOU, Jobicy та Remotive.
- Реалізував асинхронну роботу з REST API і RSS, SQLite-сховище, FSM-анкети,
  декілька профілів користувача, фільтрацію, обране та планові сповіщення.
- Створив локальний алгоритм оцінювання відповідності вакансії профілю з
  поясненням результату та кешування API-запитів.

## Short English description

**AI Job Assistant UA** is a Telegram bot that aggregates vacancies from
Ukrainian and international sources, supports multiple personalized search
profiles, applies advanced filters, ranks vacancies by profile fit, saves
favorites, and sends scheduled notifications.

## CV bullets in English

- Built an asynchronous Telegram job-search assistant integrating Jooble, DOU,
  Jobicy, and Remotive through REST APIs and RSS.
- Implemented SQLite persistence, FSM-based onboarding, multiple user profiles,
  advanced vacancy filters, favorites, deduplication, and scheduled alerts.
- Designed a transparent local job-match scoring algorithm and API caching to
  improve ranking quality and reduce external requests.

## Технології

`Python`, `aiogram`, `asyncio`, `SQLite`, `aiosqlite`, `REST API`,
`RSS/XML`, `httpx`, `APScheduler`, `Git`.

## Як розповісти про проєкт на співбесіді

> Я створив Telegram-бота, який збирає вакансії з кількох джерел і допомагає
> користувачу не переглядати все вручну. У боті можна створювати декілька
> пошукових профілів, задавати місто, формат роботи, досвід, зарплату, графік і
> стоп-слова. Дані зберігаються в SQLite, а зовнішні джерела опитуються
> асинхронно. Якщо один сервіс тимчасово недоступний, інші продовжують працювати.
> Також я реалізував локальну оцінку відповідності вакансії профілю та
> кешування Jooble для економії API-запитів.

## Що важливо не перебільшувати

Поточна оцінка відповідності є власним алгоритмом ранжування, а не повноцінною
великою мовною моделлю. На співбесіді краще називати її **smart matching** або
**rule-based matching**, доки до проєкту не підключено справжній LLM API.
