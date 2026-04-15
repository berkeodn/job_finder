"""Orchestrator: apply to jobs marked approved in DB (Telegram ingest runs separately)."""

from __future__ import annotations

import asyncio
import logging
import random
import sys
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from sqlalchemy import func

from config import settings
from src.db.database import engine, get_session, init_db
from src.db.models import Job
from src.notifier.telegram import send_alert

from .adapters import AgentAdapter, GreenhouseAdapter, LeverAdapter
from .base import ApplicantProfile, ApplyResult, load_applicant_profile

logger = logging.getLogger(__name__)

# LinkedIn URLs use AgentAdapter (see _apply_to_job); rule-based LinkedInAdapter is unused here.
_ADAPTERS = {
    "lever": LeverAdapter(),
    "greenhouse": GreenhouseAdapter(),
    "agent": AgentAdapter(),
}


def _unwrap_linkedin_redirect(url: str) -> str:
    """Extract the real destination URL from LinkedIn's /safety/go/ redirect wrapper."""
    parsed = urlparse(url)
    if "linkedin.com" in parsed.netloc and "/safety/go" in parsed.path:
        qs = parse_qs(parsed.query)
        real_urls = qs.get("url", [])
        if real_urls:
            return real_urls[0]
    return url


def _looks_like_already_applied(message: str) -> bool:
    """LinkedIn / ATS says the user already applied; treat as done, not a retryable failure."""
    m = (message or "").lower()
    return any(
        phrase in m
        for phrase in (
            "already applied",
            "already submitted",
            "applied ",  # 'Applied 2 days ago'
            "başvurdunuz",
            "başvurunuz gönderildi",
            "you've applied",
            "you have applied",
        )
    )


def _pick_adapter(url: str) -> str:
    """Choose the best adapter based on the URL domain."""
    url_lower = url.lower()
    if "linkedin.com" in url_lower:
        return "linkedin"
    if "lever.co" in url_lower or "jobs.lever.co" in url_lower:
        return "lever"
    if "greenhouse.io" in url_lower or "boards.greenhouse.io" in url_lower:
        return "greenhouse"
    return "agent"


async def _apply_to_job(
    job: Job, profile: ApplicantProfile, session
) -> ApplyResult:
    """Run the appropriate adapter. Falls back to agent if rule-based fails."""
    target_url = job.url
    adapter_key = _pick_adapter(target_url)

    # LinkedIn jobs go directly to the AI agent (rule-based adapter
    # struggles with login security checks that the agent can handle)
    if adapter_key == "linkedin":
        adapter_key = "agent"

    adapter = _ADAPTERS[adapter_key]
    logger.info("Applying to '%s' @ %s via %s", job.title, job.company, adapter.name)

    result = await adapter.apply(target_url, profile)

    # Handle LinkedIn external redirect -> re-route to the right adapter
    if not result.success and result.message.startswith("external:"):
        external_url = result.message.split("external:", 1)[1]
        target_url = _unwrap_linkedin_redirect(external_url)
        logger.info("External redirect to: %s", target_url)
        adapter_key = _pick_adapter(target_url)
        adapter = _ADAPTERS[adapter_key]
        logger.info("Re-routing to %s adapter", adapter.name)
        result = await adapter.apply(target_url, profile)

    # After all attempts, if captcha is the final result, mark accordingly
    if not result.success and "captcha" in result.message.lower():
        job.apply_status = "captcha"
        session.commit()
        return ApplyResult(
            success=False,
            message=f"captcha:{target_url}",
            adapter_used=result.adapter_used,
        )

    if not result.success and "job_closed" in result.message.lower():
        # Listing gone vs "you already applied" — already-applied counts as applied (not closed).
        if _looks_like_already_applied(result.message):
            job.apply_status = "applied"
            job.applied_at = datetime.now(timezone.utc)
            session.commit()
            logger.info(
                "Already applied on site (job_closed text): %s @ %s", job.title, job.company
            )
            return ApplyResult(
                success=True,
                message="already_applied_on_site",
                adapter_used=result.adapter_used,
            )
        job.apply_status = "closed"
        session.commit()
        logger.info("Job closed/expired: %s @ %s", job.title, job.company)
        return result

    # Agent said failure but page shows prior application — same outcome as success for the DB.
    if not result.success and _looks_like_already_applied(result.message):
        job.apply_status = "applied"
        job.applied_at = datetime.now(timezone.utc)
        session.commit()
        logger.info("Marked applied (already applied on site): %s @ %s", job.title, job.company)
        return ApplyResult(
            success=True,
            message="already_applied_on_site",
            adapter_used=result.adapter_used,
        )

    # Update DB
    if result.success:
        job.apply_status = "applied"
        job.applied_at = datetime.now(timezone.utc)
    else:
        job.apply_status = "failed"
    session.commit()

    return result


async def run_applicant() -> None:
    """Process jobs with apply_status=approved (set by telegram-ingest or test workflow)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    # Suppress noisy browser-use storage_state+user_data_dir warnings
    logging.getLogger("browser_use.utils").setLevel(logging.ERROR)

    logger.info("=== Auto-Apply Runner Starting ===")
    init_db()
    logger.info("Using SQLite: %s", engine.url)
    profile = load_applicant_profile()
    session = get_session()

    # trim() avoids missing rows if the column ever has accidental whitespace
    pending_jobs = (
        session.query(Job)
        .filter(func.trim(Job.apply_status) == "approved")
        .all()
    )

    if not pending_jobs:
        total = session.query(Job).count()
        by_status = dict(
            session.query(Job.apply_status, func.count(Job.id))
            .group_by(Job.apply_status)
            .all()
        )
        logger.info(
            "No pending applications (trim(apply_status) == 'approved'). "
            "total_jobs=%s by_status=%s",
            total,
            by_status,
        )
        session.close()
        return

    # Check daily limit
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    applied_today = (
        session.query(Job)
        .filter(Job.apply_status == "applied", Job.applied_at >= today_start)
        .count()
    )
    remaining_budget = max(0, settings.max_daily_applications - applied_today)

    if remaining_budget == 0:
        logger.warning(
            "Daily application limit reached: %d/%d applied today (UTC). "
            "Pending approved jobs wait until UTC midnight or higher max_daily_applications.",
            applied_today,
            settings.max_daily_applications,
        )
        session.close()
        return

    logger.info(
        "Processing %d applications (budget: %d/%d)",
        min(len(pending_jobs), remaining_budget),
        remaining_budget,
        settings.max_daily_applications,
    )

    applied_count = 0
    try:
        for job in pending_jobs:
            if applied_count >= remaining_budget:
                break

            result = await _apply_to_job(job, profile, session)
            applied_count += 1

            job_url = job.url or ""

            if result.message.startswith("job_closed"):
                reason = result.message.split(":", 1)[1].strip() if ":" in result.message else "Job is no longer available"
                logger.info("Job closed: %s @ %s — %s", job.title, job.company, reason)
                send_alert(
                    f"\U0001f6ab Job unavailable\n\n"
                    f"{job.title} @ {job.company}\n"
                    f"{reason}",
                    buttons=[[{"text": "\U0001f517 View Job", "url": job_url}]] if job_url else None,
                )
                continue
            elif result.success:
                logger.info("Applied: %s @ %s via %s", job.title, job.company, result.adapter_used)
                send_alert(
                    f"\u2705 Applied successfully!\n\n"
                    f"{job.title} @ {job.company}\n"
                    f"via {result.adapter_used}",
                    buttons=[[{"text": "\U0001f517 View Job", "url": job_url}]] if job_url else None,
                )
            elif result.message.startswith("captcha:"):
                captcha_url = result.message.split("captcha:", 1)[1]
                logger.warning("Captcha blocked: %s @ %s", job.title, job.company)
                send_alert(
                    f"\U0001f512 Captcha detected\n\n"
                    f"{job.title} @ {job.company}\n"
                    f"Form filled but captcha blocked submission.",
                    buttons=[[{"text": "\U0001f4dd Apply Manually", "url": captcha_url}]],
                )
            else:
                logger.warning("Failed: %s @ %s - %s", job.title, job.company, result.message)
                buttons = [
                    [{"text": "\U0001f504 Retry", "callback_data": f"apply:{job.job_id}"}],
                ]
                if job_url:
                    buttons.append([{"text": "\U0001f517 View Job", "url": job_url}])
                send_alert(
                    f"\u274c Application failed\n\n"
                    f"{job.title} @ {job.company}\n"
                    f"{result.message[:200]}",
                    buttons=buttons,
                )

            # Random delay between applications for ban prevention
            if applied_count < remaining_budget and applied_count < len(pending_jobs):
                delay = random.uniform(30, 90)
                logger.info("Waiting %.0fs before next application...", delay)
                await asyncio.sleep(delay)

    finally:
        session.close()

    logger.info("=== Auto-Apply Runner Finished (%d applied) ===", applied_count)


if __name__ == "__main__":
    asyncio.run(run_applicant())
