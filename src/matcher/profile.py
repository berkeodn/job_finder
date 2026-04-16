from __future__ import annotations

import unicodedata
from pathlib import Path
from dataclasses import dataclass, field

import yaml


@dataclass
class SearchQuery:
    keywords: str
    location: str = ""
    time_posted: str = "r86400"
    work_type: str = ""  # "remote", "onsite", "hybrid", or "" for all


@dataclass
class Profile:
    summary: str = ""
    skills: list[str] = field(default_factory=list)
    experience_years: int = 0
    max_experience_years: int = 0
    preferred_roles: list[str] = field(default_factory=list)
    searches: list[SearchQuery] = field(default_factory=list)
    # If non-empty: keep a scraped job only if its card `location` contains
    # at least one substring (case-insensitive). Empty = disabled.
    location_postfilter: list[str] = field(default_factory=list)
    must_have_any: list[str] = field(default_factory=list)
    deal_breakers: list[str] = field(default_factory=list)
    company_blacklist: list[str] = field(default_factory=list)


def load_profile(path: str = "profile.yaml") -> Profile:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    searches = [SearchQuery(**s) for s in raw.get("searches", [])]
    exp = raw.get("experience_years", 0)

    return Profile(
        summary=raw.get("summary", ""),
        skills=raw.get("skills", []),
        experience_years=exp,
        max_experience_years=raw.get("max_experience_years", exp + 3),
        preferred_roles=raw.get("preferred_roles", []),
        searches=searches,
        must_have_any=[t.lower() for t in raw.get("must_have_any", [])],
        deal_breakers=[t.lower() for t in raw.get("deal_breakers", [])],
        company_blacklist=[c.strip().lower() for c in raw.get("company_blacklist", [])],
        location_postfilter=[str(x).strip() for x in raw.get("location_postfilter", []) if str(x).strip()],
    )


def _fold_location_text(text: str) -> str:
    """casefold + strip combining marks so ASCII patterns match İstanbul / Türkiye spellings."""
    cf = (text or "").casefold()
    nkfd = unicodedata.normalize("NFKD", cf)
    return "".join(ch for ch in nkfd if not unicodedata.combining(ch))


def passes_location_postfilter(location: str, patterns: list[str]) -> bool:
    """Return True if `patterns` is empty, or if folded `location` contains any folded pattern."""
    if not patterns:
        return True
    loc_fold = _fold_location_text(location)
    for p in patterns:
        p = (p or "").strip()
        if not p:
            continue
        if _fold_location_text(p) in loc_fold:
            return True
    return False


def passes_prefilter(title: str, description: str, profile: Profile) -> bool:
    """Fast keyword-based check before sending to the AI scorer."""
    text = f"{title} {description}".lower()

    if any(term in text for term in profile.deal_breakers):
        return False

    if profile.must_have_any and not any(
        term in text for term in profile.must_have_any
    ):
        return False

    return True


def is_blacklisted(company: str, profile: Profile) -> bool:
    """Check if a company is in the blacklist."""
    normalised = company.strip().lower()
    return any(bl in normalised for bl in profile.company_blacklist)
