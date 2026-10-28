"""Render the CV LaTeX from the master profile.

The profile is the only source of facts. An optional `selection` (from the package
pipeline) may pick bullets, reorder them and swap in rewritten wording, but it can
only refer to bullet ids that exist in the profile.
"""

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates"

_MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
           "September", "Oktober", "November", "Dezember"]
_LATEX_SPECIAL = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}
_SKILL_LABELS = [
    ("languages", "Programmiersprachen"),
    ("tools", "Tools & Frameworks"),
    ("cicd", "CI/CD"),
    ("cloud", "Cloud & Hosting"),
    ("os", "Betriebssysteme"),
]


def latex_escape(text: object) -> str:
    return "".join(_LATEX_SPECIAL.get(ch, ch) for ch in str(text))


def _escape_url(url: object) -> str:
    return str(url).replace("%", r"\%").replace("#", r"\#")


def _month(value: object) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{2})", str(value))
    if not match:
        return str(value)
    return f"{_MONTHS[int(match.group(2)) - 1]} {match.group(1)}"


def format_range(start: object, end: object) -> str:
    if str(end).lower() == "present":
        return f"seit {_month(start)}"
    return f"{_month(start)} - {_month(end)}"


def _link(url: str) -> str:
    shown = re.sub(r"^https?://(www\.)?", "", url).rstrip("/")
    return rf"\href{{{_escape_url(url)}}}{{{latex_escape(shown)}}}"


def _contact_rows(person: dict[str, Any]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if person.get("address"):
        rows.append(("Adresse", latex_escape(person["address"])))
    if person.get("phone"):
        rows.append(("Telefon", latex_escape(person["phone"])))
    if person.get("email"):
        mail = person["email"]
        rows.append(("E-Mail", rf"\href{{mailto:{_escape_url(mail)}}}{{{latex_escape(mail)}}}"))
    if person.get("github"):
        rows.append(("GitHub", _link(person["github"])))
    if person.get("linkedin"):
        rows.append(("LinkedIn", _link(person["linkedin"])))
    if person.get("birthdate"):
        rows.append(("Geburtsdatum", latex_escape(person["birthdate"])))
    if person.get("nationality"):
        rows.append(("Nationalität", latex_escape(person["nationality"])))
    return rows


def _bullets(entry: dict[str, Any], selection: dict[str, Any] | None) -> list[dict[str, str]]:
    bullets = {b["id"]: b["text"] for b in entry.get("bullets", [])}
    if not selection:
        return [{"id": i, "text": t} for i, t in bullets.items()]
    order = selection.get("bullets", {}).get(entry["id"])
    ids = [i for i in (order if order is not None else list(bullets)) if i in bullets]
    rewrites = selection.get("rewrites", {})
    return [{"id": i, "text": rewrites.get(i, bullets[i])} for i in ids]


def build_context(
    profile: dict[str, Any], selection: dict[str, Any] | None = None, has_photo: bool = False
) -> dict[str, Any]:
    person = profile["person"]
    experience = []
    for job in profile.get("experience", []):
        bullets = _bullets(job, selection)
        if selection and not bullets:
            continue
        experience.append({
            "title": job["title"], "company": job["company"], "place": job.get("place", ""),
            "range": format_range(job["start"], job["end"]), "bullets": bullets,
        })
    education = [
        {"degree": e["degree"], "school": e["school"], "focus": e.get("focus"),
         "thesis": e.get("thesis"), "range": format_range(e["start"], e["end"])}
        for e in profile.get("education", [])
    ]
    projects = []
    chosen_projects = (selection or {}).get("projects_chosen")
    for p in profile.get("projects", []):
        if chosen_projects is not None and p["id"] not in chosen_projects:
            continue
        bullets = _bullets(p, selection)
        if bullets:
            projects.append({"name": p["name"], "url": p.get("url"),
                             "text": " ".join(b["text"] for b in bullets)})
    skills = profile.get("skills", {})
    skill_rows = [
        (label, ", ".join(skills[key])) for key, label in _SKILL_LABELS if skills.get(key)
    ]
    spoken = profile.get("target", {}).get("languages")
    if spoken:
        skill_rows.append(("Sprachen", ", ".join(spoken)))
    if skills.get("soft"):
        skill_rows.append(("Soft Skills", ", ".join(skills["soft"])))
    summary = (selection or {}).get("summary") or profile.get("summary", "")
    return {
        "person": person,
        "headline": (selection or {}).get("headline") or person.get("headline"),
        "contact_rows": _contact_rows(person), "photo": has_photo,
        "summary": " ".join(str(summary).split()), "experience": experience,
        "education": education, "projects": projects, "skill_rows": skill_rows,
        "other": profile.get("other", []),
    }


def render_cv(
    profile: dict[str, Any], selection: dict[str, Any] | None = None, has_photo: bool = False
) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        block_start_string=r"\BLOCK{", block_end_string="}",
        variable_start_string=r"\VAR{", variable_end_string="}",
        comment_start_string=r"\#{", comment_end_string="}",
        trim_blocks=True, lstrip_blocks=True, undefined=StrictUndefined, autoescape=False,
    )
    env.filters["e"] = latex_escape
    env.filters["eurl"] = _escape_url
    return env.get_template("cv.tex.j2").render(**build_context(profile, selection, has_photo))
