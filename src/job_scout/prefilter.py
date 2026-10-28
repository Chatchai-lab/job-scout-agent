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
    r"manufacturing|propulsion|structural|\brf\b",
    re.IGNORECASE,
)

# Not a regular full-time job and not a working-student job either.
NOT_FULL_TIME = re.compile(
    r"praktik|\bintern\b|internship|\bthesis\b|abschlussarbeit|bachelorarbeit|masterarbeit|"
    r"ausbildung|apprentice|duales studium|studierende|studenten",
    re.IGNORECASE,
)

# Working-student jobs (part time next to the studies) are wanted near Darmstadt or remote.
WORKING_STUDENT_TITLE = re.compile(
    r"werkstudent|working student|studentische|student assistant|student worker", re.IGNORECASE
)
# "Anything with IT": development, data, support, administration, testing, web, security ...
WORKING_STUDENT_TECH = re.compile(
    r"\bit\b|it-|edv|software|entwickl|developer|engineer|informatik|daten|data|\bai\b|\bki\b|"
    r"\bml\b|llm|python|java|cloud|devops|automat|\bweb|digital|backend|frontend|full[- ]?stack|"
    r"\bqa\b|test|analyst|analytics|system|netz|network|security|sicherheit|\bsap\b|erp|crm|"
    r"\bbi\b|support|helpdesk|admin|infrastruktur|infrastructure|\bapp\b|mobile|\btech|cyber|"
    r"scrum|robot|forschung|research",
    re.IGNORECASE,
)
# Business functions that stay out even for working students. IT support, hardware and research
# are IT-related here, so they are not part of this list; customer-facing support is.
WORKING_STUDENT_EXCLUDED = re.compile(
    r"\baccount\b|accountant|recruit|counsel|legal|marketing|financ|\bhr\b|\bpeople\b|payroll|"
    r"compensation|talent|\bwriter\b|mechanical|electrical|manufacturing|propulsion|structural|"
    r"customer (?:support|success|service)|kundenservice|kundensupport",
    re.IGNORECASE,
)
RHEIN_MAIN = re.compile(
    r"darmstadt|frankfurt|mainz|wiesbaden|offenbach|r(?:ü|ue)sselsheim|heidelberg|mannheim|"
    r"ludwigshafen|weiterstadt|griesheim|bensheim|weinheim|aschaffenburg|hanau|\blangen\b|"
    r"dreieich|neu-isenburg|eschborn|bad homburg|oberursel|kelsterbach|raunheim|gro(?:ß|ss)-gerau|"
    r"worms|hessen|hesse|rhein-main|rhine-main|remote|homeoffice|home office",
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
    "muenchen",
    "hamburg",
    "frankfurt",
    "cologne",
    "köln",
    "koeln",
    "stuttgart",
    "düsseldorf",
    "duesseldorf",
    "dresden",
    "leipzig",
    "hannover",
    "hanover",
    "nürnberg",
    "nuernberg",
    "nuremberg",
    "bremen",
    "dortmund",
    "essen",
    "bonn",
    "karlsruhe",
    "mannheim",
    "heidelberg",
    "darmstadt",
    "mainz",
    "wiesbaden",
    "offenbach",
    "augsburg",
    "regensburg",
    "freiburg",
    "münster",
    "muenster",
    "aachen",
    "kiel",
    "rostock",
    "potsdam",
    "jena",
    "ulm",
    "würzburg",
    "wuerzburg",
    "bielefeld",
    "braunschweig",
    "kassel",
    "erlangen",
    "ingolstadt",
    "wolfsburg",
    "chemnitz",
    "saarbrücken",
    "hessen",
    "bayern",
    "baden-württemberg",
    "nrw",
    "remote",
)


# Whole-word matches, so "ulm" or "kiel" cannot hide inside another word.
_GERMAN_PLACE = re.compile(
    r"\b(?:" + "|".join(re.escape(h) for h in _EU_HINTS if h != "remote") + r")\b", re.IGNORECASE
)
_GERMAN_OR_REMOTE = re.compile(
    r"\b(?:" + "|".join(re.escape(h) for h in _EU_HINTS) + r")\b", re.IGNORECASE
)


class DropReason(str):
    """Readable reason stored in prefilter_drops.reason."""


def prefilter(
    job: JobPosting, *, include_abroad: bool = False, include_working_student: bool = True
) -> DropReason | None:
    """Return a drop reason, or None if the job should go to the LLM."""
    title = job.title or ""
    working_student = bool(WORKING_STUDENT_TITLE.search(title))

    if SENIOR_TITLE.search(title):
        return DropReason("senior_title")

    if SALES_TITLE.search(title) and not TITLE_KEYWORDS.search(title):
        return DropReason("sales_title")

    text = f"{title} {job.location or ''} {job.description or ''}"
    if US_ONLY.search(text):
        return DropReason("us_only")

    if NOT_FULL_TIME.search(title):
        return DropReason("title_excluded")
    excluded = WORKING_STUDENT_EXCLUDED if working_student else EXCLUDED_TITLE
    if excluded.search(title):
        return DropReason("title_excluded")
    if working_student:
        if not include_working_student:
            return DropReason("title_excluded")
        if not WORKING_STUDENT_TECH.search(title):
            return DropReason("title_not_dev")
        near = RHEIN_MAIN.search(f"{title} {job.location or ''}")
        # Arbeitsagentur searches already filter by distance, so any town counts as near.
        trusted_region = job.source == "arbeitsagentur"
        if job.location and not job.remote and not near and not trusted_region:
            return DropReason("working_student_far")
    elif not (
        TITLE_KEYWORDS.search(title)
        or DEV_TITLE.search(title)
        or INITIATIVE_TITLE.search(title)
    ):
        return DropReason("title_not_dev")

    if not include_abroad:
        place = f"{title} {job.location or ''}"
        german = _GERMAN_PLACE.search(place)
        foreign = NON_DE_PLACES.search(place) or NON_DE_CODES.search(place)
        if foreign and not german:
            return DropReason("outside_germany")
        if job.location and not job.remote:
            if not _GERMAN_OR_REMOTE.search(job.location):
                return DropReason("outside_germany")

    return None
