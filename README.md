# Job Finder

Automated LinkedIn job scraping pipeline with AI-powered matching and Telegram notifications.

```
LinkedIn search → Store in SQLite → Pre-filter → Gemini AI scoring → Telegram alert
```

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

### 2. Configure API keys

Copy the example env file and fill in your keys:

```bash
cp .env.example .env
```

| Variable | How to get it |
|---|---|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) — free |
| `TELEGRAM_BOT_TOKEN` | Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` |
| `TELEGRAM_CHAT_ID` | Message [@userinfobot](https://t.me/userinfobot) on Telegram to get your chat ID |

### 3. Edit your profile

Open `profile.yaml` and customize:

- **summary** — describe yourself (used by the AI scorer)
- **skills** — your tech stack
- **searches** — LinkedIn search queries to run
- **must_have_any / deal_breakers** — fast keyword pre-filter rules

### 4. Run locally

```bash
python -m src.main
```

### 5. Deploy to GitHub Actions

1. Push this repo to GitHub
2. Go to **Settings → Secrets and variables → Actions**
3. Add these secrets: `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
4. The pipeline runs automatically every 6 hours (configurable in `.github/workflows/scrape.yml`)
5. You can also trigger it manually from the **Actions** tab → **Run workflow**

## How it works

| Stage | What happens | Cost |
|---|---|---|
| **Scrape** | Fetches public LinkedIn job search results using your configured queries | Free |
| **Dedup** | Skips jobs already in the SQLite database | Free |
| **Pre-filter** | Rejects jobs missing required keywords or containing deal-breakers | Free |
| **AI Score** | Sends surviving jobs to Gemini Flash with your profile for 0-100 scoring | Free (within Gemini free tier) |
| **Notify** | Sends jobs scoring above threshold to your Telegram | Free |

## Project structure

```
job_finder/
├── .github/workflows/scrape.yml   # GitHub Actions cron job
├── src/
│   ├── scraper/linkedin.py        # LinkedIn public page scraper
│   ├── db/models.py               # SQLAlchemy Job model
│   ├── db/database.py             # DB engine + session
│   ├── matcher/profile.py         # Profile loader + pre-filter
│   ├── matcher/gemini.py          # Gemini AI scorer
│   ├── notifier/telegram.py       # Telegram bot notifications
│   └── main.py                    # Pipeline orchestrator
├── profile.yaml                   # Your profile & search config
├── config.py                      # App settings (reads .env)
└── requirements.txt
```
