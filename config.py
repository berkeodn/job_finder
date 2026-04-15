from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    db_url: str = "sqlite:///jobs.db"

    # Gemma 4 26B via Gemini API (free tier)
    gemini_model: str = "gemma-4-26b-a4b-it"

    # Gemma 4 free-tier rate limits
    gemini_rpm: int = 15      # requests per minute
    gemini_rpd: int = 1500    # requests per day
    pipeline_runs_per_day: int = 4  # how many times pipeline runs daily
    gemini_max_per_run: int = 375   # rpd / runs_per_day

    # Only notify if match score >= this value
    score_threshold: int = 60

    # Content dedup: ignore duplicates only within this window (days).
    # If the same title+company was notified more than N days ago, treat as new.
    dedup_days: int = 7

    # Scraping settings — keep close to per-run scoring budget
    min_filtered_jobs: int = 50
    scrape_delay_min: float = 2.0
    scrape_delay_max: float = 5.0

    # Auto-apply settings
    linkedin_email: str = ""
    linkedin_password: str = ""
    applicant_email: str = ""
    applicant_phone: str = ""
    cv_path: str = "assets/BERKE ODEN CV.pdf"
    max_daily_applications: int = 20
    headless: bool = True

    # browser-use BrowserProfile (see browser_use.browser.profile.BrowserProfile model_fields)
    browser_use_cross_origin_iframes: bool = True
    browser_use_max_iframes: int = 120
    browser_use_max_iframe_depth: int = 8
    browser_use_min_wait_page_load_time: float = 0.35
    browser_use_wait_network_idle_page_load_time: float = 0.75
    browser_use_wait_between_actions: float = 0.15
    browser_use_accept_downloads: bool = True

    # browser-use Agent: local loop fingerprint (hard-stop) + optional mid-run loop prompt
    agent_loop_watchdog_enabled: bool = True
    agent_loop_window_actions: int = 24
    agent_loop_max_identical_in_window: int = 6
    agent_loop_max_consecutive_identical: int = 5
    # If True, register_should_stop_callback stops the run when thresholds hit (aggressive).
    # If False, rely on browser-use loop_detection nudges + optional mid-run prompt below.
    agent_loop_hard_stop: bool = False
    # When ActionLoopDetector.get_nudge_message() is non-empty (same as browser-use loop nudge),
    # append our extra UserMessage once per agent run. Env: AGENT_LOOP_MID_RUN_PROMPT_ENABLED
    agent_loop_mid_run_prompt_enabled: bool = True

    # IMAP settings for LinkedIn email verification code
    imap_server: str = "imap.gmail.com"
    imap_email: str = ""  # defaults to linkedin_email if empty
    imap_password: str = ""  # Gmail App Password

    # Fallback only if TCMB + backup FX API both fail (TRY per 1 USD / 1 EUR)
    try_usd_rate_fallback: float = 44.5959
    try_eur_rate_fallback: float = 52.1683

    # Rough net→gross for Turkey when forms ask brüt/gross (exact depends on tax bracket)
    salary_net_to_gross_multiplier: float = 1.47

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
