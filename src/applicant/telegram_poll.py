"""Poll Telegram for 'apply' callback queries and mark jobs as approved."""
import json
import logging
from pathlib import Path

import httpx

from config import settings
from src.db.database import get_session
from src.db.models import Job

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}"
OFFSET_FILE = Path("telegram_offset.txt")


def _get_offset() -> int:
    if OFFSET_FILE.exists():
        return int(OFFSET_FILE.read_text().strip())
    return 0


def _save_offset(offset: int) -> None:
    OFFSET_FILE.write_text(str(offset))


def _answer_callback(callback_query_id: str, text: str) -> None:
    url = f"{TELEGRAM_API.format(token=settings.telegram_bot_token)}/answerCallbackQuery"
    try:
        httpx.post(url, json={"callback_query_id": callback_query_id, "text": text}, timeout=10)
    except Exception as e:
        logger.warning("Failed to answer callback: %s", e)


def poll_apply_callbacks() -> list[str]:
    """Fetch pending apply callbacks from Telegram. Returns list of job_ids approved."""
    if not settings.telegram_bot_token:
        return []

    offset = _get_offset()
    url = f"{TELEGRAM_API.format(token=settings.telegram_bot_token)}/getUpdates"

    try:
        resp = httpx.post(
            url,
            json={"offset": offset, "timeout": 5, "allowed_updates": ["callback_query"]},
            timeout=15,
        )
        data = resp.json()
    except Exception as e:
        logger.error("Failed to poll Telegram: %s", e)
        return []

    if not data.get("ok"):
        logger.error("Telegram getUpdates error: %s", data)
        return []

    approved_job_ids: list[str] = []
    session = get_session()

    try:
        for update in data.get("result", []):
            _save_offset(update["update_id"] + 1)

            callback = update.get("callback_query")
            if not callback:
                continue

            cb_data = callback.get("data", "")
            if not cb_data.startswith("apply:"):
                continue

            job_id = cb_data.split(":", 1)[1]
            job = session.query(Job).filter(Job.job_id == job_id).first()
            if not job:
                _answer_callback(callback["id"], "❌ Job not found in DB")
                continue

            if job.apply_status == "applied":
                _answer_callback(callback["id"], "✅ Already applied!")
                continue

            if job.apply_status == "approved":
                _answer_callback(callback["id"], "⏳ Already in queue")
                continue

            job.apply_status = "approved"
            session.commit()
            approved_job_ids.append(job_id)

            _answer_callback(callback["id"], "📨 Queued for application!")
            logger.info("Job approved for apply: %s @ %s", job.title, job.company)

    finally:
        session.close()

    return approved_job_ids
