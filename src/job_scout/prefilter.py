"""Free, rule-based filter that runs before any LLM call.

Only drops what Entscheidung 11 in the design doc marks as a hard
dealbreaker: Senior/Staff/Lead-only titles, US-only locations (unless
abroad is explicitly enabled), and quota-carrying sales roles. Everything
else — travel, industry, language, contract type, salary — is left to the
LLM score, never filtered here.
"""

import re

from job_scout.models import JobPosting

# Titles only: a wide net so the LLM sees every real candidate. The LLM
# decides fit from the description, not this list.
TITLE_KEYWORDS = re.compile(
    r"forward deployed|solutions? engineer|customer engineer|"
    r"implementation engineer|deployment engineer|deployment strategist|"
    r"applied ai|ai engineer|field engineer|technical consultant",
    re.IGNORECASE,
)

SENIOR_TITLE = re.compile(
    r"\b(senior|sr\.?|staff|lead|principal|head of|director|manager)\b", re.IGNORECASE
)

SALES_TITLE = re.compile(r"\b(account executive|sales|business development)\b", re.IGNORECASE)

US_ONLY = re.compile(r"\bus[\s-]?only\b|united states only", re.IGNORECASE)

_EU_HINTS = (
    "germany",
    "deutschland",
    "berlin",
    "munich",
    "münchen",
    "hamburg",
    "frankfurt",
    "cologne",
    "köln",
    "stuttgart",
    "remote",
)


class DropReason(str):
    """Readable reason stored in prefilter_drops.reason."""


def prefilter(job: JobPosting, *, include_abroad: bool = False) -> DropReason | None:
    """Return a drop reason, or None if the job should go to the LLM."""
    title = job.title or ""

    if SENIOR_TITLE.search(title):
        return DropReason("senior_title")

    if SALES_TITLE.search(title) and not TITLE_KEYWORDS.search(title):
        return DropReason("sales_title")

    text = f"{title} {job.location or ''} {job.description or ''}"
    if US_ONLY.search(text):
        return DropReason("us_only")

    if not include_abroad and job.location and not job.remote:
        location = job.location.lower()
        if not any(hint in location for hint in _EU_HINTS):
            return DropReason("outside_germany")

    return None
