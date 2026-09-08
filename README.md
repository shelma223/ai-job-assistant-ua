# AI Job Assistant UA

Telegram bot that helps users search, filter, rank, and save job vacancies from
Ukrainian and international sources.

The project is focused on the Ukrainian job market. Its interface is in
Ukrainian, while vacancies may be returned in the language used by the original
source.

## Features

- Up to five independent search profiles per user
- Step-by-step profile setup with validation
- Editing individual profile fields without completing the full form again
- Search by profession, city, region, work format, employment type, experience,
  working hours, salary, and publication date
- Required-salary and excluded-keyword filters
- Smart vacancy-to-profile match score with short explanations
- Favorites with one-click save and removal
- Scheduled vacancy checks at 09:00 and 19:00 Europe/Kyiv time
- Duplicate prevention for scheduled notifications
- Persistent SQLite storage
- Ukrainian button-based interface
- Graceful fallback when one vacancy source is unavailable
- One-hour Jooble response cache to conserve the API quota

## Vacancy sources

| Source | Integration | Purpose |
| --- | --- | --- |
| Jooble Ukraine | REST API | Broad Ukrainian job market |
| DOU | RSS | Ukrainian IT and digital vacancies |
| Jobicy | REST API | International remote vacancies |
| Remotive | REST API | International remote vacancies |

Jooble is optional. Without a Jooble key, the bot continues working with the
other sources.

## Technology

- Python 3.14
- aiogram 3
- SQLite and aiosqlite
- httpx
- APScheduler
- python-dotenv
- Telegram Bot API

## Project structure

```text
ai-job-assistant/
├── bot.py              # Telegram interface, profiles, database and scheduler
├── job_sources.py      # Vacancy APIs, RSS parsing and filtering
├── requirements.txt    # Python dependencies
├── .env.example        # Safe environment-variable template
├── .gitignore          # Files that must not be published
├── PORTFOLIO.md        # Ready-to-use CV and interview descriptions
└── README.md
```

The application creates `job_assistant.db` automatically on first launch.

## Installation on Windows

1. Install Python 3.14 or newer.
2. Open the project folder in VS Code.
3. Create a virtual environment:

```powershell
python -m venv .venv
```

4. Activate it in PowerShell:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
.venv\Scripts\Activate.ps1
```

5. Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

6. Copy `.env.example` to a new file named `.env`.
7. Add the Telegram bot token and, optionally, the Jooble API key:

```env
BOT_TOKEN=your_telegram_bot_token
JOOBLE_API_KEY=your_jooble_ukraine_api_key
```

8. Start the bot:

```powershell
python bot.py
```

Stop it with `Ctrl+C`.

## User flow

1. Send `/start`.
2. Open **Мої профілі**.
3. Create one or more vacancy-search profiles.
4. Select the active profile.
5. Press **Знайти вакансії**.
6. Review the match score and save useful vacancies.
7. Enable notifications if scheduled checks are needed.

## Commands

| Command | Action |
| --- | --- |
| `/start` | Open the main menu |
| `/profile` | Manage search profiles |
| `/vacancies` | Search using the active profile |
| `/favorites` | Open saved vacancies |
| `/subscribe` | Enable scheduled notifications |
| `/unsubscribe` | Disable scheduled notifications |
| `/cancel` | Cancel the current form or editing action |

## Match score

The current match score is calculated locally and does not require a paid AI
service. It considers:

- overlap between the search query and vacancy content;
- user skills found in the vacancy;
- city and remote-work compatibility;
- employment type;
- requested and offered salary;
- experience level.

It is a ranking aid, not a guarantee that the user meets every employer
requirement.

## Data and security

- Tokens are loaded from `.env`.
- `.env`, SQLite databases, virtual environments, and cache files are excluded
  from Git.
- Never publish a real bot token or Jooble key.
- If a token is exposed, revoke it and create a new one.

## Current limitations

- Scheduled notifications work only while the Python process is running.
- Some vacancy sources do not provide every filter or salary.
- The match score uses transparent local rules rather than a language model.
- External APIs and feeds may temporarily become unavailable.

## Possible next steps

- Deployment to an always-on server
- Configurable notification schedule
- Pagination and a “show more” button
- User feedback for personalized ranking
- CV upload and analysis
- Optional LLM-based vacancy matching and cover-letter generation
- Automated tests and structured logging

## Status

Working MVP suitable for testing, demonstration, and further product
development.
