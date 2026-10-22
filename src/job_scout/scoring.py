"""LLM scoring of one job posting via forced tool use (structured JSON)."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from job_scout.models import JobPosting
from job_scout.pricing import Usage

MAX_DESCRIPTION_CHARS = 6000


class ScoreResult(BaseModel):
    fit: int = Field(ge=0, le=10)
    reach: int = Field(ge=0, le=10)
    ring: Literal["kern", "nah", "beratung", "raus"]
    sales_share: float | None = Field(default=None, ge=0, le=1)
    start_ok: bool | None = None
    salary: str | None = None
    reason: str


SCORE_TOOL: dict[str, Any] = {
    "name": "submit_score",
    "description": "Submit the evaluation of this job posting for the candidate.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fit": {
                "type": "integer",
                "minimum": 0,
                "maximum": 10,
                "description": "How well tasks and tech match the candidate's profile and goals.",
            },
            "reach": {
                "type": "integer",
                "minimum": 0,
                "maximum": 10,
                "description": (
                    "Seniority match: 10 = clearly open to a graduate/junior with this "
                    "experience, 5 = stretch (about 3 years asked), 0 = needs far more."
                ),
            },
            "ring": {
                "type": "string",
                "enum": ["kern", "nah", "beratung", "raus"],
                "description": (
                    "kern = Forward Deployed Engineer style; nah = adjacent customer-facing "
                    "AI/engineering or regular software/IT developer roles; "
                    "beratung = technical delivery at a consultancy; "
                    "raus = sales, pre-sales or quota-carrying."
                ),
            },
            "sales_share": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Estimated share of the role that is selling (0 to 1).",
            },
            "start_ok": {
                "type": ["boolean", "null"],
                "description": (
                    "False only if the posting demands a full-time start before March 2027; "
                    "null if unclear."
                ),
            },
            "salary": {
                "type": ["string", "null"],
                "description": "Salary as stated in the posting, or null.",
            },
            "reason": {
                "type": "string",
                "description": "Two sentences in German: why this score, incl. the main doubt.",
            },
        },
        "required": ["fit", "reach", "ring", "reason"],
    },
}

INSTRUCTIONS = """\
Du bewertest Stellenanzeigen für einen Informatik-Studenten (Bachelor-Abschluss Februar 2027, \
frühester Einstieg März 2027, Erfahrung als Werkstudent/Praktikant in KI und Prozess-\
automatisierung). Ziel sind Forward-Deployed-Engineer-artige Rollen in Deutschland: Kunden-\
nahe technische Umsetzung, Applied AI, Solutions/Customer/Implementation Engineering sowie \
technische Delivery-Rollen bei Beratungen. Kein Vertrieb, kein Pre-Sales, keine Quota.

Gleichwertig gewünscht sind normale Software- und IT-Entwicklerstellen für Berufseinsteiger: \
Backend, Fullstack, Cloud/DevOps, Automatisierung und KI-Anwendungen. Bewerte sie nach der \
Passung von Aufgaben und Technik zum Profil (Python, Cloud, Container, Automatisierung, KI), \
nicht danach, ob die Rolle kundennah ist. Fehlender Kundenkontakt senkt den Fit dann nicht. \
Ein klar verlangter Kern-Stack ohne Beleg im Profil (zum Beispiel reines Golang) und echte \
Senior-Anforderungen senken ihn weiterhin. Solche Rollen bekommen die Stufe "nah".

Sprachen und Werkzeuge in der Skill-Liste und unter "skills_detail" gelten als belegte \
Kenntnisse aus Studium und Projekten, auch wenn sie nicht aus einer Anstellung stammen. Für \
Berufseinsteiger-Stellen reichen sie aus. Fordert eine Anzeige ausdrücklich mehrjährige \
Berufserfahrung in einem Stack, senkt das den Fit, aber nur dort. Was unter "skills_detail" \
als nicht vorhanden steht (zum Beispiel Java), gilt als fehlend.

Regeln:
- Junior/Graduate passt immer; "Stretch" bis ca. 3 Jahre Erfahrung ist noch okay (reach mittel).
- Reisebereitschaft, Branche (auch Defense), Sprache (Deutsch/Englisch), Vertragsart und \
Gehalt sind KEINE Ausschlussgründe und beeinflussen den Score kaum.
- Bewerte nur anhand der Anzeige und des Profils. Erfinde nichts.
- Antworte ausschließlich über das Tool submit_score.
"""


def build_system(profile_text: str, rules: list[str]) -> str:
    parts = [INSTRUCTIONS, "## Profil des Kandidaten\n" + profile_text]
    if rules:
        parts.append("## Freigegebene Präferenzregeln\n" + "\n".join(f"- {r}" for r in rules))
    return "\n\n".join(parts)


def build_user(job: JobPosting) -> str:
    description = (job.description or "")[:MAX_DESCRIPTION_CHARS]
    return (
        f"Firma: {job.company_name}\n"
        f"Titel: {job.title}\n"
        f"Ort: {job.location or 'unbekannt'}{' (remote)' if job.remote else ''}\n"
        f"Link: {job.url}\n\n"
        f"Beschreibung:\n{description or '(keine)'}"
    )


def parse_response(response: Any) -> ScoreResult:
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "submit_score":
            return ScoreResult(**block.input)
    raise ValueError("model did not call submit_score")


def usage_from(response: Any) -> Usage:
    u = response.usage
    return Usage(
        input_tokens=getattr(u, "input_tokens", 0) or 0,
        cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        output_tokens=getattr(u, "output_tokens", 0) or 0,
    )


def score_job(client: Any, model: str, system: str, job: JobPosting) -> tuple[ScoreResult, Usage]:
    """The system block is marked cacheable: the profile is identical for every job."""
    response = client.messages.create(
        model=model,
        max_tokens=600,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        tools=[SCORE_TOOL],
        tool_choice={"type": "tool", "name": "submit_score"},
        messages=[{"role": "user", "content": build_user(job)}],
    )
    return parse_response(response), usage_from(response)
