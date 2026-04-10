"""AI-powered answerer for custom ATS questions using Gemma 4."""
import json
import logging

from src.matcher.gemini import _get_client
from config import settings

logger = logging.getLogger(__name__)

_cache: dict[str, str] = {}

ANSWER_PROMPT = """\
You are filling out a job application form. Answer the question below based on the \
candidate profile. Be concise and professional.

If options are provided, return ONLY the best matching option text exactly as given.
If no options, return a short answer (1-2 sentences max).

## Candidate Profile
{profile}

## Job Title
{job_title}

## Question
{question}
{options_text}

Return ONLY the answer, no explanation.
"""


def _cache_key(question: str, options: list[str]) -> str:
    normalized = question.strip().lower()
    opts = "|".join(sorted(o.lower() for o in options))
    return f"{normalized}::{opts}"


def answer_question(
    question: str,
    options: list[str],
    profile_text: str,
    job_title: str,
) -> str:
    """Answer a custom ATS question using AI, with caching."""
    key = _cache_key(question, options)
    if key in _cache:
        logger.info("Cache hit for question: %s", question[:60])
        return _cache[key]

    options_text = ""
    if options:
        options_text = "Options:\n" + "\n".join(f"- {o}" for o in options)

    prompt = ANSWER_PROMPT.format(
        profile=profile_text,
        job_title=job_title,
        question=question,
        options_text=options_text,
    )

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
        )
        answer = response.text.strip()
        if answer.startswith("```"):
            answer = answer.split("\n", 1)[1]
        if answer.endswith("```"):
            answer = answer.rsplit("```", 1)[0]
        answer = answer.strip().strip('"')

        _cache[key] = answer
        logger.info("AI answered '%s' -> '%s'", question[:60], answer[:80])
        return answer
    except Exception as e:
        logger.error("AI failed to answer question '%s': %s", question[:60], e)
        return ""
