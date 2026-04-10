"""Greenhouse ATS form adapter (boards.greenhouse.io)."""
import asyncio
import logging

from playwright.async_api import Page

from .base import ApplicantProfile, ApplyResult, BaseAdapter, match_field_to_profile
from .question_answerer import answer_question

logger = logging.getLogger(__name__)


class GreenhouseAdapter(BaseAdapter):

    @staticmethod
    def can_handle(url: str) -> bool:
        return "greenhouse.io" in url or "boards.greenhouse" in url

    async def apply(
        self,
        page: Page,
        url: str,
        profile: ApplicantProfile,
        job_description: str,
    ) -> ApplyResult:
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # Greenhouse standard fields
        field_map = {
            "#first_name": profile.first_name,
            "#last_name": profile.last_name,
            "#email": profile.email,
            "#phone": profile.phone,
        }

        for selector, value in field_map.items():
            if not value:
                continue
            el = page.locator(selector)
            if await el.count() > 0:
                await el.first.fill(value)

        # LinkedIn field (varies)
        linkedin_input = page.locator("input[name*='linkedin'], input[id*='linkedin']")
        if await linkedin_input.count() > 0:
            await linkedin_input.first.fill(profile.linkedin_url)

        # CV upload
        await self._upload_cv(page, profile)

        # Custom questions (Greenhouse uses .field divs with labels)
        fields = page.locator(".field, .custom-question")
        for i in range(await fields.count()):
            field = fields.nth(i)
            label_el = field.locator("label")
            if await label_el.count() == 0:
                continue
            label_text = (await label_el.first.inner_text()).strip()
            if not label_text:
                continue

            text_input = field.locator("input[type='text'], textarea")
            if await text_input.count() > 0:
                current = await text_input.first.input_value()
                if not current.strip():
                    value = match_field_to_profile(label_text, profile)
                    if not value:
                        value = answer_question(label_text, [], profile.summary, job_description[:500])
                    if value:
                        await text_input.first.fill(value)
                continue

            select = field.locator("select")
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
        submit = page.locator("#submit_app, button[type='submit'], input[type='submit']")
        if await submit.count() > 0:
            await submit.first.click()
            await asyncio.sleep(3)

            success = page.locator("text=Application submitted, text=Thank you, text=received")
            if await success.count() > 0:
                return ApplyResult(success=True, message="Applied via Greenhouse")

            screenshot = await self._screenshot(page, "greenhouse_post_submit")
            return ApplyResult(success=True, message="Submitted via Greenhouse (unconfirmed)", screenshot_path=screenshot)

        screenshot = await self._screenshot(page, "greenhouse_no_submit")
        return ApplyResult(success=False, message="Submit button not found on Greenhouse", screenshot_path=screenshot)
