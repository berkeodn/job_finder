"""Base adapter for ATS form filling."""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import Page

logger = logging.getLogger(__name__)


@dataclass
class ApplicantProfile:
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    linkedin_url: str = ""
    location: str = ""
    education: str = ""
    university: str = ""
    experience_years: int = 0
    summary: str = ""
    skills: list[str] = field(default_factory=list)
    cv_path: str = ""
    authorized_to_work_in_turkey: bool = True


@dataclass
class ApplyResult:
    success: bool
    message: str = ""
    screenshot_path: str = ""


# Common field label -> profile attribute mappings
FIELD_MAPPINGS: dict[str, list[str]] = {
    "first_name": ["first name", "given name", "ad", "adınız", "isim"],
    "last_name": ["last name", "family name", "surname", "soyad", "soyadınız"],
    "email": ["email", "e-mail", "e-posta", "mail"],
    "phone": ["phone", "telephone", "mobile", "telefon", "cep"],
    "linkedin_url": ["linkedin", "linkedin url", "linkedin profile"],
    "location": ["location", "city", "address", "konum", "şehir", "adres"],
    "education": ["education", "degree", "eğitim"],
    "university": ["university", "school", "college", "üniversite", "okul"],
}


def match_field_to_profile(label: str, profile: ApplicantProfile) -> str | None:
    """Try to match a form field label to a profile value using rule-based mapping."""
    label_lower = label.strip().lower()
    for attr, keywords in FIELD_MAPPINGS.items():
        if any(kw in label_lower for kw in keywords):
            value = getattr(profile, attr, "")
            if value:
                return str(value)
    if any(kw in label_lower for kw in ("experience", "years", "deneyim", "yıl")):
        return str(profile.experience_years)
    return None


class BaseAdapter(ABC):
    """Base class for ATS form-filling adapters."""

    @staticmethod
    @abstractmethod
    def can_handle(url: str) -> bool:
        """Return True if this adapter handles the given URL."""

    @abstractmethod
    async def apply(
        self,
        page: Page,
        url: str,
        profile: ApplicantProfile,
        job_description: str,
    ) -> ApplyResult:
        """Fill and submit the application form. Returns result."""

    async def _upload_cv(self, page: Page, profile: ApplicantProfile) -> bool:
        """Upload CV to a file input if found."""
        cv = Path(profile.cv_path)
        if not cv.exists():
            logger.warning("CV file not found: %s", profile.cv_path)
            return False
        file_input = page.locator("input[type='file']").first
        try:
            await file_input.set_input_files(str(cv.resolve()))
            logger.info("CV uploaded: %s", cv.name)
            return True
        except Exception as e:
            logger.warning("Failed to upload CV: %s", e)
            return False

    async def _screenshot(self, page: Page, name: str) -> str:
        """Take a debug screenshot."""
        path = f"screenshots/{name}.png"
        Path("screenshots").mkdir(exist_ok=True)
        await page.screenshot(path=path, full_page=True)
        return path
