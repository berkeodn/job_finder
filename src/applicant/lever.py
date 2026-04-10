"""Lever ATS form adapter (jobs.lever.co)."""
import asyncio
import logging

from playwright.async_api import Page

from .base import ApplicantProfile, ApplyResult, BaseAdapter, match_field_to_profile
from .question_answerer import answer_question

logger = logging.getLogger(__name__)


class LeverAdapter(BaseAdapter):

    @staticmethod
    def can_handle(url: str) -> bool:
        return "lever.co" in url or "jobs.lever.co" in url

    async def apply(
        self,
        page: Page,
        url: str,
        profile: ApplicantProfile,
        job_description: str,
    ) -> ApplyResult:
        apply_url = url.rstrip("/") + "/apply"
        await page.goto(apply_url, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        if "404" in await page.title() or await page.locator("text=Page not found").count() > 0:
            return ApplyResult(success=False, message="Lever apply page not found")

        # Standard Lever fields
        field_map = {
            "input[name='name']": f"{profile.first_name} {profile.last_name}",
            "input[name='email']": profile.email,
            "input[name='phone']": profile.phone,
            "input[name='org']": "",
            "input[name='urls[LinkedIn]']": profile.linkedin_url,
            "input[name='urls[Portfolio]']": "",
        }

        for selector, value in field_map.items():
            if not value:
                continue
            el = page.locator(selector)
            if await el.count() > 0:
                await el.first.fill(value)

        # CV upload
        await self._upload_cv(page, profile)

        # Custom questions (Lever uses .application-question divs)
        questions = page.locator(".application-question")
        for i in range(await questions.count()):
            q = questions.nth(i)
            label_el = q.locator("label, .application-label")
            if await label_el.count() == 0:
                continue
            label_text = (await label_el.first.inner_text()).strip()
            if not label_text:
                continue

            # Check for text input
            text_input = q.locator("input[type='text'], textarea")
            if await text_input.count() > 0:
                current = await text_input.first.input_value()
                if not current.strip():
                    value = match_field_to_profile(label_text, profile)
                    if not value:
                        value = answer_question(label_text, [], profile.summary, job_description[:500])
                    if value:
                        await text_input.first.fill(value)
                continue

            # Check for select
            select = q.locator("select")
            if await select.count() > 0:
                options = await select.first.locator("option").all_inner_texts()
                options = [o.strip() for o in options if o.strip() and "select" not in o.lower()]
                if options:
                    answer = answer_question(label_text, options, profile.summary, job_description[:500])
                    if answer:
                        try:
                            await select.first.select_option(label=answer)
                        except Exception:
                            pass

        # Submit
        submit = page.locator("button[type='submit'], button:has-text('Submit'), input[type='submit']")
        if await submit.count() > 0:
            await submit.first.click()
            await asyncio.sleep(3)

            success = page.locator("text=Application submitted, text=Thank you, text=received your application")
            if await success.count() > 0:
                return ApplyResult(success=True, message="Applied via Lever")

            screenshot = await self._screenshot(page, "lever_post_submit")
            return ApplyResult(success=True, message="Submitted via Lever (unconfirmed)", screenshot_path=screenshot)

        screenshot = await self._screenshot(page, "lever_no_submit")
        return ApplyResult(success=False, message="Submit button not found on Lever", screenshot_path=screenshot)
