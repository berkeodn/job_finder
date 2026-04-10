"""Generic form adapter — attempts to fill any application form."""
import asyncio
import logging

from playwright.async_api import Page

from .base import ApplicantProfile, ApplyResult, BaseAdapter, match_field_to_profile
from .question_answerer import answer_question

logger = logging.getLogger(__name__)


class GenericAdapter(BaseAdapter):

    @staticmethod
    def can_handle(url: str) -> bool:
        return True

    async def apply(
        self,
        page: Page,
        url: str,
        profile: ApplicantProfile,
        job_description: str,
    ) -> ApplyResult:
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        filled_count = 0

        # Fill all visible text/email/tel inputs
        inputs = page.locator(
            "input[type='text']:visible, input[type='email']:visible, "
            "input[type='tel']:visible, input[type='url']:visible"
        )
        for i in range(await inputs.count()):
            inp = inputs.nth(i)
            if (await inp.input_value()).strip():
                continue

            label_text = await self._get_label(page, inp)
            if not label_text:
                continue

            value = match_field_to_profile(label_text, profile)
            if not value:
                value = answer_question(label_text, [], profile.summary, job_description[:500])
            if value:
                await inp.fill(value)
                filled_count += 1

        # Textareas
        textareas = page.locator("textarea:visible")
        for i in range(await textareas.count()):
            ta = textareas.nth(i)
            if (await ta.input_value()).strip():
                continue
            label_text = await self._get_label(page, ta)
            if label_text:
                value = answer_question(label_text, [], profile.summary, job_description[:500])
                if value:
                    await ta.fill(value)
                    filled_count += 1

        # Selects
        selects = page.locator("select:visible")
        for i in range(await selects.count()):
            sel = selects.nth(i)
            label_text = await self._get_label(page, sel)
            options = await sel.locator("option").all_inner_texts()
            options = [o.strip() for o in options if o.strip() and "select" not in o.lower()]
            if label_text and options:
                answer = answer_question(label_text, options, profile.summary, job_description[:500])
                if answer:
                    try:
                        await sel.select_option(label=answer)
                        filled_count += 1
                    except Exception:
                        pass

        # CV upload
        await self._upload_cv(page, profile)

        if filled_count == 0:
            screenshot = await self._screenshot(page, "generic_empty")
            return ApplyResult(
                success=False,
                message="Could not fill any fields on this form",
                screenshot_path=screenshot,
            )

        # Try to submit
        submit = page.locator(
            "button[type='submit']:visible, input[type='submit']:visible, "
            "button:has-text('Submit'):visible, button:has-text('Apply'):visible"
        )
        if await submit.count() > 0:
            await submit.first.click()
            await asyncio.sleep(3)

            screenshot = await self._screenshot(page, "generic_post_submit")
            return ApplyResult(
                success=True,
                message=f"Submitted via generic adapter ({filled_count} fields filled)",
                screenshot_path=screenshot,
            )

        screenshot = await self._screenshot(page, "generic_no_submit")
        return ApplyResult(
            success=False,
            message=f"Filled {filled_count} fields but no submit button found",
            screenshot_path=screenshot,
        )

    async def _get_label(self, page: Page, element) -> str:
        """Try to find the label for a form element."""
        el_id = await element.get_attribute("id") or ""
        if el_id:
            label = page.locator(f"label[for='{el_id}']")
            if await label.count() > 0:
                return (await label.first.inner_text()).strip()

        for attr in ("aria-label", "placeholder", "name"):
            val = await element.get_attribute(attr)
            if val:
                return val.strip()
        return ""
