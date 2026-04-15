# Job Finder

Automated LinkedIn job scraping pipeline with AI-powered matching, Telegram notifications, and autonomous job application via an AI agent.

```
LinkedIn search → SQLite → Pre-filter → Gemini AI scoring → Telegram alert → Apply/Reject → AI Agent auto-apply
```

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows
pip install -r requirements.txt
playwright install chromium
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
| `LINKEDIN_EMAIL` | Your LinkedIn login email |
| `LINKEDIN_PASSWORD` | Your LinkedIn login password |
| `IMAP_EMAIL` | Email for LinkedIn 2FA code fetching (IMAP) |
| `IMAP_PASSWORD` | App Password for the IMAP email account |

### 3. Edit your profile

Open `profile.yaml` and customize:

- **summary** — describe yourself (used by the AI scorer)
- **skills** — your tech stack
- **searches** — LinkedIn search queries to run
- **must_have_any / deal_breakers** — fast keyword pre-filter rules
- **salary_expectation, english_proficiency, work_authorization** — used by the AI agent when filling forms

### 4. Save LinkedIn session (recommended)

Run once to save login cookies and avoid repeated CAPTCHA challenges:

```bash
python save_linkedin_session.py
```

This creates `linkedin_session.json` which the agent reuses for subsequent runs.

### 5. Run locally

```bash
# Scrape + score + notify
python -m src.main

# Auto-apply to approved jobs
python -m src.applicant.runner
```

### 6. Deploy to GitHub Actions

1. Push this repo to GitHub
2. Go to **Settings → Secrets and variables → Actions**
3. Add secrets: `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `LINKEDIN_EMAIL`, `LINKEDIN_PASSWORD`, `IMAP_EMAIL`, `IMAP_PASSWORD`
4. **Scrape workflow** runs on GitHub Actions every 6 hours
5. **Apply workflow** runs on a self-hosted runner (residential IP for anti-detection)

## How it works

### Scrape pipeline

| Stage | What happens | Cost |
|---|---|---|
| **Scrape** | Fetches public LinkedIn job search results | Free |
| **Dedup** | Skips jobs already in the SQLite database | Free |
| **Pre-filter** | Rejects jobs missing required keywords or containing deal-breakers | Free |
| **AI Score** | Sends surviving jobs to Gemini for 0-100 scoring | Free (Gemini free tier) |
| **Notify** | Sends scored jobs to Telegram with Apply/Reject buttons | Free |

### Auto-apply pipeline

| Stage | What happens |
|---|---|
| **Telegram callback** | User presses "Apply" on a job notification |
| **DB lookup** | Runner fetches job URL from SQLite by job_id |
| **Adapter selection** | Picks the right adapter based on URL (LinkedIn → AI agent, Lever, Greenhouse) |
| **AI Agent** | Browser-use agent navigates the form, fills fields from `profile.yaml`, submits |
| **Result notification** | Telegram message with result (success / fail with Retry button / captcha / closed) |

### Application statuses

| Status | Meaning |
|---|---|
| `not_applied` | Scraped, awaiting user decision |
| `approved` | User pressed "Apply", queued for agent |
| `applied` | Agent successfully submitted the application |
| `failed` | Agent failed — Retry button available in Telegram |
| `captcha` | CAPTCHA blocked — manual apply needed |
| `closed` | Job no longer accepting applications or already applied |

### Key features

- **Anti-detection**: Random delays between applications, daily limit (configurable), realistic browser fingerprint, LinkedIn session reuse
- **CAPTCHA handling**: Detected across all adapters, user notified via Telegram with manual apply link
- **Retry mechanism**: Failed applications get a Retry button in Telegram, deduplicated to prevent double-apply
- **LinkedIn 2FA**: Automatic email verification code fetching via IMAP
- **DB synchronization**: Apply results preserved across scrape/apply workflow runs via backup-restore mechanism
- **Custom form tools**: CDP-based typing, force click, autocomplete handling for dynamic forms (Workday, etc.)

## Project structure

```
job_finder/
├── .github/workflows/
│   ├── scrape.yml                    # Scrape + score + notify (GitHub Actions)
│   └── apply.yml                     # Auto-apply (self-hosted runner)
├── src/
│   ├── scraper/linkedin.py           # LinkedIn public page scraper
│   ├── db/models.py                  # SQLAlchemy Job model
│   ├── db/database.py                # DB engine + session
│   ├── matcher/profile.py            # Profile loader + pre-filter
│   ├── matcher/gemini.py             # Gemini AI scorer
│   ├── notifier/telegram.py          # Telegram bot notifications
│   ├── applicant/
│   │   ├── runner.py                 # Apply orchestrator (polls Telegram, picks adapter)
│   │   ├── base.py                   # Shared types + profile loader
│   │   ├── telegram_poll.py          # Telegram callback polling
│   │   ├── adapters/                 # Site-specific adapters
│   │   │   ├── agent_adapter.py      # AI agent (browser-use + custom tools)
│   │   │   ├── linkedin_adapter.py   # LinkedIn rule-based adapter
│   │   │   ├── lever_adapter.py      # Lever rule-based adapter
│   │   │   └── greenhouse_adapter.py # Greenhouse rule-based adapter
│   │   ├── browser/                  # Stealth Playwright + email verification
│   │   └── salary/                   # Exchange rates + salary hint text
│   └── main.py                       # Scrape pipeline orchestrator
├── profile.yaml                      # Your profile & search config
├── config.py                         # App settings (reads .env)
├── save_linkedin_session.py          # One-time LinkedIn session saver
└── requirements.txt
```

## Workflows

### Scrape (`scrape.yml`)
- **Runs on**: GitHub Actions (schedule: every 6 hours + manual)
- **Does**: Scrape → Score → Notify via Telegram
- **Artifact**: Uploads `jobs.db` for the apply workflow

### Apply (`apply.yml`)
- **Runs on**: Self-hosted runner (schedule: every 30 minutes + manual)
- **Inputs**: `test_url` — optional direct job URL for testing
- **Does**: Downloads scrape DB → Restores local apply statuses → Processes approved/retried jobs → Uploads updated DB
- **DB sync**: Backs up local `apply_status` before downloading scrape DB, then merges back to preserve apply results

### Local machine: latest scrape DB + Telegram (no full apply here)

GitHub does not push the scrape `jobs-db` artifact to your PC automatically. On your machine you only:

1. **`scripts/sync_local_jobs_db_from_scrape_artifact.ps1`** — pull the latest successful scrape artifact, replace `jobs.db`, merge your existing `apply_status` rows back (`_local_sync_apply_backup.json`). Use `-SkipDownload` if `jobs.db.scrape-artifact` is already fresh.
2. **Telegram ingest** — either run **`scripts/run_telegram_ingest.ps1`** afterward, or pass **`-RunTelegramIngest`** on the sync script so ingest runs immediately after sync. Add **`-AlsoRun`** with `-RunTelegramIngest` if you also want `src.applicant.runner` after ingest.

**Scheduled task:** **`scripts/register_sync_then_ingest_schedule.ps1`** — every tick downloads the **latest** scrape `jobs-db` artifact (`gh`), merges into `jobs.db`, then runs Telegram ingest (hidden: **`sync_then_ingest_silent.vbs`**). Requires **`gh auth login`**. If you still have the legacy task **`job_finder-telegram-ingest`**, remove it: `Unregister-ScheduledTask -TaskName 'job_finder-telegram-ingest' -Confirm:$false`.

That is the end of the local “sync + queue” step. You do **not** run Auto Apply just to upload an artifact.

### Auto Apply Runner (self-hosted) — applies + uploads

**`apply.yml`** on the self-hosted runner (scheduled every ~30 minutes) downloads the latest `jobs-db` artifact, merges apply statuses from **that** machine’s `jobs.db`, runs the LinkedIn applicant, then uploads the updated `jobs-db` artifact. So: **artifact refresh + approvals + applications + upload** happen in that job.

If your dev PC and the self-hosted runner are **not** the same machine, `approved` must exist on the runner’s `jobs.db` (copy DB, or run Telegram ingest on the runner, or rely on the merge step in `apply.yml` if you already sync files).

Inspect any SQLite copy: `python -m src.applicant.inspect_jobs_db` or `--db path/to/jobs.db`.
