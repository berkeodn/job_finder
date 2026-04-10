"""Orchestrator: poll Telegram, pick adapter, apply, report result."""
import asyncio
import logging
import sys
from datetime import datetime, timezone

import yaml
from playwright.async_api import async_playwright

from config import settings
from src.db.database import get_session, init_db
from src.db.models import Job
from src.notifier.telegram import send_alert

from .base import ApplicantProfile, ApplyResult, BaseAdapter
from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter
from .linkedin_easy_apply import LinkedInEasyApplyAdapter
from .generic import GenericAdapter
from .telegram_poll import poll_apply_callbacks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

ADAPTERS: list[BaseAdapter] = [
    LinkedInEasyApplyAdapter(),
    LeverAdapter(),
    GreenhouseAdapter(),
    GenericAdapter(),
]


def _load_applicant_profile() -> ApplicantProfile:
    raw = yaml.safe_load(open("profile.yaml", encoding="utf-8"))
    personal = raw.get("personal", {})
    return ApplicantProfile(
        first_name=personal.get("first_name", ""),
        last_name=personal.get("last_name", ""),
        email=settings.applicant_email,
        phone=settings.applicant_phone,
        linkedin_url=personal.get("linkedin_url", ""),
        location=personal.get("location", ""),
        education=personal.get("education", ""),
        university=personal.get("university", ""),
        experience_years=raw.get("experience_years", 0),
        summary=raw.get("summary", ""),
        skills=raw.get("skills", []),
        cv_path=settings.cv_path,
    )


def _pick_adapter(url: str) -> BaseAdapter:
    for adapter in ADAPTERS:
        if adapter.can_handle(url):
            return adapter
    return ADAPTERS[-1]


async def _apply_to_job(job: Job, profile: ApplicantProfile) -> ApplyResult:
    adapter = _pick_adapter(job.url)
    adapter_name = type(adapter).__name__

    logger.info("Applying to '%s @ %s' via %s", job.title, job.company, adapter_name)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        try:
            result = await adapter.apply(page, job.url, profile, job.description or "")
        except Exception as e:
            logger.error("Apply failed with exception: %s", e)
            result = ApplyResult(success=False, message=f"Exception: {e}")
        finally:
            await browser.close()

    return result


async def run() -> None:
    logger.info("=== Apply Runner Starting ===")
    init_db()

    # 1. Poll Telegram for new approvals
    approved = poll_apply_callbacks()
    logger.info("New approvals from Telegram: %d", len(approved))

    # 2. Load all approved jobs
    session = get_session()
    try:
        jobs_to_apply = (
            session.query(Job)
            .filter(Job.apply_status == "approved")
            .all()
        )
        if not jobs_to_apply:
            logger.info("No approved jobs to apply. Done.")
            return

        logger.info("Found %d approved jobs to apply", len(jobs_to_apply))
        profile = _load_applicant_profile()

        applied = 0
        failed = 0

        for job in jobs_to_apply:
            job.apply_status = "applying"
            session.commit()

            result = await _apply_to_job(job, profile)

            if result.success:
                job.apply_status = "applied"
                job.applied_at = datetime.now(timezone.utc)
                applied += 1
                logger.info("✓ Applied: %s @ %s — %s", job.title, job.company, result.message)
                send_alert(f"✅ Applied: {job.title} @ {job.company}\n{result.message}\n{job.url}")
            else:
                job.apply_status = "failed"
                failed += 1
                logger.warning("✗ Failed: %s @ %s — %s", job.title, job.company, result.message)
                send_alert(f"❌ Failed: {job.title} @ {job.company}\n{result.message}\n{job.url}")

            session.commit()

        logger.info("=== Apply Summary: %d applied, %d failed ===", applied, failed)

    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(run())
