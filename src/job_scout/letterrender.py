"""Render the cover letter LaTeX (same look as the CV) from the generated letter text."""

from datetime import date
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from job_scout.cvrender import _MONTHS, TEMPLATE_DIR, _escape_url, latex_escape


def german_date(day: date) -> str:
    return f"{day.day}. {_MONTHS[day.month - 1]} {day.year}"


def letter_paragraphs(text: str) -> list[str]:
    """Blank-line separated blocks; single line breaks (closing, name) stay as line breaks."""
    blocks = [b.strip() for b in text.replace("\r\n", "\n").split("\n\n") if b.strip()]
    return [r"\\ ".join(latex_escape(line.strip()) for line in b.split("\n")) for b in blocks]


def _contact_line(person: dict[str, Any]) -> str:
    parts = [latex_escape(person[k]) for k in ("address", "phone") if person.get(k)]
    if person.get("email"):
        mail = person["email"]
        parts.append(rf"\href{{mailto:{_escape_url(mail)}}}{{{latex_escape(mail)}}}")
    return r" \;\textbullet\; ".join(parts)


def render_letter(
    profile: dict[str, Any], letter_text: str, job: dict[str, Any], today: date
) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        block_start_string=r"\BLOCK{", block_end_string="}",
        variable_start_string=r"\VAR{", variable_end_string="}",
        comment_start_string=r"\#{", comment_end_string="}",
        trim_blocks=True, lstrip_blocks=True, undefined=StrictUndefined, autoescape=False,
    )
    env.filters["e"] = latex_escape
    person = profile["person"]
    return env.get_template("letter.tex.j2").render(
        person=person,
        contact_line=_contact_line(person),
        date=german_date(today),
        company=job["company_name"],
        place=job.get("location") or "",
        job_title=" ".join(str(job["title"]).split()),
        paragraphs=letter_paragraphs(letter_text),
    )
