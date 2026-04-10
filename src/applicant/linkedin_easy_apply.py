"""LinkedIn Easy Apply adapter using Playwright + cookie auth."""
import asyncio
import json
import logging

from playwright.async_api import Page

from config import settings
from .base import ApplicantProfile, ApplyResult, BaseAdapter, match_field_to_profile
from .question_answerer import answer_question

logger = logging.getLogger(__name__)


class LinkedInEasyApplyAdapter(BaseAdapter):

    @staticmethod
    def can_handle(url: str) -> bool:
        return "linkedin.com/jobs/view" in url

    async def apply(
        self,
        page: Page,
        url: str,
        profile: ApplicantProfile,
        job_description: str,
    ) -> ApplyResult:
        cookies = self._load_cookies()
        if not cookies:
            return ApplyResult(success=False, message="LinkedIn cookies not configured")

        await page.context.add_cookies(cookies)
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # Check if logged in
        if "login" in page.url or "authwall" in page.url:
            return ApplyResult(success=False, message="LinkedIn cookies expired — please re-export")

        # Find and click Easy Apply button
        easy_apply_btn = page.locator("button.jobs-apply-button, button:has-text('Easy Apply')")
        try:
            await easy_apply_btn.first.click(timeout=5000)
        except Exception:
            screenshot = await self._screenshot(page, "no_easy_apply")
            return ApplyResult(
                success=False,
                message="Easy Apply button not found — may require external application",
                screenshot_path=screenshot,
            )

        await asyncio.sleep(2)

        # Walk through multi-step form
        max_steps = 10
        for step in range(max_steps):
            await self._fill_visible_fields(page, profile, job_description)

            # Check for submit button
            submit = page.locator("button[aria-label='Submit application'], button:has-text('Submit')")
            if await submit.count() > 0:
                await submit.first.click()
                await asyncio.sleep(3)

                # Check for success
                success_el = page.locator(
                    "div:has-text('Your application was sent'), "
                    "h2:has-text('Application submitted')"
                )
                if await success_el.count() > 0:
                    return ApplyResult(success=True, message="Application submitted via Easy Apply")

                screenshot = await self._screenshot(page, f"submit_step_{step}")
                return ApplyResult(success=True, message="Submitted (unconfirmed)", screenshot_path=screenshot)

            # Click Next / Review
            next_btn = page.locator(
                "button[aria-label='Continue to next step'], "
                "button:has-text('Next'), "
                "button:has-text('Review')"
            )
            if await next_btn.count() > 0:
                await next_btn.first.click()
                await asyncio.sleep(2)
            else:
                break

        screenshot = await self._screenshot(page, "stuck")
        return ApplyResult(success=False, message="Got stuck in form flow", screenshot_path=screenshot)

    async def _fill_visible_fields(self, page: Page, profile: ApplicantProfile, job_desc: str) -> None:
        """Fill all visible form fields on the current step."""
        # Text inputs
        inputs = page.locator("input[type='text']:visible, input[type='email']:visible, input[type='tel']:visible")
        for i in range(await inputs.count()):
            inp = inputs.nth(i)
            current_val = await inp.input_value()
            if current_val.strip():
                continue

            label_text = ""
            inp_id = await inp.get_attribute("id") or ""
            if inp_id:
                label = page.locator(f"label[for='{inp_id}']")
                if await label.count() > 0:
                    label_text = await label.first.inner_text()
            if not label_text:
                label_text = await inp.get_attribute("aria-label") or await inp.get_attribute("placeholder") or ""

            if not label_text:
                continue

            value = match_field_to_profile(label_text, profile)
            if not value:
                value = answer_question(label_text, [], profile.summary, job_desc[:500])
            if value:
                await inp.fill(value)
                logger.info("Filled '%s' = '%s'", label_text, value[:50])

        # Textareas
        textareas = page.locator("textarea:visible")
        for i in range(await textareas.count()):
            ta = textareas.nth(i)
            if (await ta.input_value()).strip():
                continue
            label_text = await ta.get_attribute("aria-label") or await ta.get_attribute("placeholder") or ""
            if label_text:
                value = answer_question(label_text, [], profile.summary, job_desc[:500])
                if value:
                    await ta.fill(value)

        # File upload (CV)
        file_inputs = page.locator("input[type='file']:visible, input[type='file']")
        if await file_inputs.count() > 0:
            await self._upload_cv(page, profile)

        # Selects / dropdowns
        selects = page.locator("select:visible")
        for i in range(await selects.count()):
            sel = selects.nth(i)
            label_text = await sel.get_attribute("aria-label") or ""
            options = await sel.locator("option").all_inner_texts()
            options = [o.strip() for o in options if o.strip() and o.strip() != "Select an option"]
            if label_text and options:
                value = match_field_to_profile(label_text, profile)
                if not value:
                    value = answer_question(label_text, options, profile.summary, job_desc[:500])
                if value:
                    try:
                        await sel.select_option(label=value)
                        logger.info("Selected '%s' for '%s'", value, label_text)
                    except Exception:
                        pass

    def _load_cookies(self) -> list[dict]:
        raw = settings.linkedin_cookies_json
        if not raw:
            return []
        try:
            cookies = json.loads(raw)
            playwright_cookies = []
            for c in cookies:
                pc = {
                    "name": c.get("name", ""),
                    "value": c.get("value", ""),
                    "domain": c.get("domain", ".linkedin.com"),
                    "path": c.get("path", "/"),
                }
                if c.get("expirationDate"):
                    pc["expires"] = c["expirationDate"]
                playwright_cookies.append(pc)
            return playwright_cookies
        except (json.JSONDecodeError, TypeError) as e:
            logger.error("Failed to parse LinkedIn cookies: %s", e)
            return []
