"""Free, rule-based filter that runs before any LLM call.

Hard dealbreakers: Senior/Staff/Lead-only titles, US-only and other non-German
locations (unless abroad is explicitly enabled), and quota-carrying sales roles.
On top of that the title must look like a development/engineering role and must
not be research, support, a business function or a non-full-time role (internship,
working student, thesis, apprenticeship). Everything else — travel,
industry, language, salary — is left to the LLM score.
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

# Development focus: the candidate's CV is software/AI engineering, so a title has to
# match TITLE_KEYWORDS (FDE-style roles) or this broader engineering net.
DEV_TITLE = re.compile(
    r"engineer|developer|entwickl|software|architect|devops|machine learning|\bllm\b|"
    r"automation|technical consultant|it[- ]consultant|berater|consultant",
    re.IGNORECASE,
)

# Never wanted, even when the title also says "engineer".
EXCLUDED_TITLE = re.compile(
    r"research|forschung|support|designer|\bdesign\b|\baccount\b|accountant|recruit|"
    r"counsel|legal|marketing|financ|\bhr\b|\bpeople\b|payroll|compensation|talent|"
    r"\bwriter\b|mechanical|electrical|electronic|hardware|mechatronic|optical|camera|"
    r"manufacturing|propulsion|structural|\brf\b|"
    r"praktik|\bintern\b|internship|werkstudent|working student|\bthesis\b|abschlussarbeit|"
    r"bachelorarbeit|masterarbeit|ausbildung|apprentice|duales studium|studierende|studenten",
    re.IGNORECASE,
)

# Open applications without a concrete role. They skip the "looks like a developer role" test
# and are collected for the /initiativ list instead of being scored.
INITIATIVE_TITLE = re.compile(
    r"initiativ|spontan|open application|general application|talent pool|talent community|"
    r"talent wanted|join our (?:talent|team)|bewerberpool|blind application",
    re.IGNORECASE,
)

SENIOR_TITLE = re.compile(
    r"\b(senior|sr\.?|staff|lead|principal|head of|director|manager)\b", re.IGNORECASE
)

SALES_TITLE = re.compile(r"\b(account executive|sales|business development)\b", re.IGNORECASE)

US_ONLY = re.compile(r"\bus[\s-]?only\b|united states only", re.IGNORECASE)

# Places that mean "not Germany". Checked in title and location, and ignored when the
# same text also names a German place ("Berlin or London"). EMEA is deliberately absent:
# it includes Germany.
NON_DE_PLACES = re.compile(
    r"singapore|tokyo|japan|korea|seoul|india|bengaluru|bangalore|sydney|australia|\banz\b|"
    r"\bapac\b|latam|north america|canada|toronto|vancouver|mexico|brazil|san francisco|"
    r"new york|\bnyc\b|seattle|austin|boston|chicago|los angeles|washington|united states|"
    r"united kingdom|london|dublin|ireland|paris|france|amsterdam|netherlands|zurich|"
    r"z\u00fcrich|switzerland|madrid|spain|barcelona|warsaw|poland|stockholm|sweden|"
    r"copenhagen|tel aviv|israel|dubai|\buae\b|china|colombia|belgrade|serbia|portugal|"
    r"lisbon|italy|milan|rome|vienna|austria|prague|czech|bucharest|romania|budapest|hungary|"
    r"helsinki|finland|oslo|norway|brussels|belgium|argentina|chile|peru|turkey|istanbul|"
    r"south africa|nigeria|egypt|saudi|pakistan|philippines|vietnam|thailand|indonesia|"
    r"malaysia|taiwan|hong kong|new zealand|texas|colorado|california|illinois|florida|"
    r"virginia|georgia|massachusetts|oregon|arizona|ohio|michigan|minnesota|pennsylvania|"
    r"north carolina|utah|new jersey|atlanta|denver|dallas|houston|miami|philadelphia|"
    r"pittsburgh|portland|san jose|palo alto|mountain view|sunnyvale|menlo park|"
    r"redwood city|bay area|silicon valley",
    re.IGNORECASE,
)
NON_DE_CODES = re.compile(r"\b(US|USA|UK|DC)\b")

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

    if EXCLUDED_TITLE.search(title):
        return DropReason("title_excluded")
    if not (
        TITLE_KEYWORDS.search(title)
        or DEV_TITLE.search(title)
        or INITIATIVE_TITLE.search(title)
    ):
        return DropReason("title_not_dev")

    if not include_abroad:
        place = f"{title} {job.location or ''}"
        german = any(hint in place.lower() for hint in _EU_HINTS if hint != "remote")
        foreign = NON_DE_PLACES.search(place) or NON_DE_CODES.search(place)
        if foreign and not german:
            return DropReason("outside_germany")
        if job.location and not job.remote:
            if not any(hint in job.location.lower() for hint in _EU_HINTS):
                return DropReason("outside_germany")

    return None
