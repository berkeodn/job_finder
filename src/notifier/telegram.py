import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _format_message(
    title: str,
    company: str,
    location: str,
    url: str,
    score: int,
    reasons: list[str],
    missing_skills: list[str],
) -> str:
    reasons_text = "\n".join(f"  • {r}" for r in reasons)
    missing_text = ", ".join(missing_skills) if missing_skills else "None"

    return (
        f"🎯 *Match Score: {score}/100*\n\n"
        f"*{_escape_md(title)}*\n"
        f"🏢 {_escape_md(company)}\n"
        f"📍 {_escape_md(location)}\n\n"
        f"*Why it matches:*\n{_escape_md(reasons_text)}\n\n"
        f"*Missing skills:* {_escape_md(missing_text)}\n\n"
        f"[View Job]({url})"
    )


def _escape_md(text: str) -> str:
    """Escape Telegram MarkdownV2 special chars."""
    special = r"_[]()~`>#+-=|{}.!"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


def send_alert(message: str) -> bool:
    """Send a plain-text alert (rate limits, errors, etc.)."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return False

    api_url = TELEGRAM_API.format(token=settings.telegram_bot_token)
    try:
        resp = httpx.post(
            api_url,
            json={
                "chat_id": settings.telegram_chat_id,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        return resp.status_code == 200
    except Exception:
        return False


def send_job_notification(
    title: str,
    company: str,
    location: str,
    url: str,
    score: int,
    reasons: list[str],
    missing_skills: list[str],
) -> bool:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("Telegram credentials not configured, skipping notification")
        return False

    message = _format_message(title, company, location, url, score, reasons, missing_skills)
    api_url = TELEGRAM_API.format(token=settings.telegram_bot_token)

    try:
        resp = httpx.post(
            api_url,
            json={
                "chat_id": settings.telegram_chat_id,
                "text": message,
                "parse_mode": "MarkdownV2",
                "disable_web_page_preview": False,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            logger.info("Telegram notification sent for: %s", title)
            return True
        else:
            logger.error("Telegram API error %d: %s", resp.status_code, resp.text)
            return False
    except Exception as e:
        logger.error("Failed to send Telegram message: %s", e)
        return False
