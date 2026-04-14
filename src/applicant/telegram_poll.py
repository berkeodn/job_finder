"""Telegram Bot API: getUpdates for apply callbacks, optional DB-backed drain."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from config import settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}"

# Safety cap so one run cannot loop forever if Telegram keeps sending updates.
_MAX_DRAIN_BATCHES = 50


def drain_telegram_callbacks_to_db(session: "Session") -> int:
    """
    Repeatedly call getUpdates until no more apply:* callbacks in a batch.
    For each callback: set Job.apply_status='approved' if the job exists, commit,
    answerCallbackQuery, then ack the batch. Telegram is only the signal source; DB is the queue.
    """
    if not settings.telegram_bot_token:
        return 0

    from src.db.models import Job

    base = TELEGRAM_API.format(token=settings.telegram_bot_token)
    total = 0
    batches = 0

    while batches < _MAX_DRAIN_BATCHES:
        batches += 1
        try:
            resp = httpx.get(
                f"{base}/getUpdates",
                params={"allowed_updates": '["callback_query"]', "timeout": 5},
                timeout=15,
            )
            data = resp.json()
        except Exception as e:
            logger.error("getUpdates failed: %s", e)
            break

        if not data.get("ok"):
            logger.error("getUpdates API error: %s", data)
            break

        updates = data.get("result", [])
        if not updates:
            break

        max_update_id = 0
        for update in updates:
            uid = update.get("update_id", 0)
            if uid > max_update_id:
                max_update_id = uid

            cb = update.get("callback_query")
            if not cb:
                continue

            cb_data = cb.get("data", "")
            if not cb_data.startswith("apply:"):
                continue

            job_id = cb_data.split(":", 1)[1]
            cb_qid = cb["id"]
            job = session.query(Job).filter(Job.job_id == job_id).first()
            if job:
                job.apply_status = "approved"
                session.commit()
                answer_callback(cb_qid, "Queued — applying on schedule.")
                total += 1
                logger.info("Ingest: queued apply for %s @ %s", job.title, job.company)
            else:
                answer_callback(cb_qid, "Job not found in database.")
                logger.warning("Ingest: unknown job_id from Telegram: %s", job_id)

        if max_update_id:
            httpx.get(
                f"{base}/getUpdates",
                params={"offset": max_update_id + 1},
                timeout=10,
            )
        else:
            break

    if batches >= _MAX_DRAIN_BATCHES:
        logger.warning("drain_telegram_callbacks_to_db: hit max batches (%s)", _MAX_DRAIN_BATCHES)

    return total


def get_pending_applications() -> list[dict]:
    """Legacy: single-batch getUpdates without DB (unused by runner when using ingest+apply split)."""
    if not settings.telegram_bot_token:
        return []

    base = TELEGRAM_API.format(token=settings.telegram_bot_token)
    results: list[dict] = []

    try:
        resp = httpx.get(
            f"{base}/getUpdates",
            params={"allowed_updates": '["callback_query"]', "timeout": 5},
            timeout=15,
        )
        data = resp.json()
        if not data.get("ok"):
            logger.error("getUpdates failed: %s", data)
            return []

        updates = data.get("result", [])
        max_update_id = 0

        for update in updates:
            uid = update.get("update_id", 0)
            if uid > max_update_id:
                max_update_id = uid

            cb = update.get("callback_query")
            if not cb:
                continue

            cb_data = cb.get("data", "")
            if not cb_data.startswith("apply:"):
                continue

            job_id = cb_data.split(":", 1)[1]
            results.append({
                "job_id": job_id,
                "callback_query_id": cb["id"],
            })

        if max_update_id:
            httpx.get(
                f"{base}/getUpdates",
                params={"offset": max_update_id + 1},
                timeout=10,
            )

    except Exception as e:
        logger.error("Error polling Telegram: %s", e)

    return results


def answer_callback(callback_query_id: str, text: str) -> None:
    if not settings.telegram_bot_token:
        return
    base = TELEGRAM_API.format(token=settings.telegram_bot_token)
    try:
        r = httpx.post(
            f"{base}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text},
            timeout=10,
        )
        if r.status_code != 200:
            # Common: 400 if already answered or query expired (duplicate ingest / old click)
            logger.warning(
                "answerCallbackQuery HTTP %s: %s",
                r.status_code,
                (r.text or "")[:500],
            )
    except Exception as e:
        logger.error("Error answering callback: %s", e)
