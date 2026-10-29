"""English version of a finished German package: a translation, never a rewrite.

The German package stays the master (its selection and letter are stored with the application).
The CV context and the letter are translated in one model call; numbers and technologies in
the English text must already appear in the German source, otherwise the call is repeated.
"""

from typing import Any

from job_scout.factcheck import deterministic_problems
from job_scout.pricing import Usage
from job_scout.toolcall import call_tool

MAX_TRIES = 3

TRANSLATE_TOOL: dict[str, Any] = {
    "name": "submit_translation",
    "description": "Return the English translation of every text, under the same key.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"key": {"type": "string"}, "text": {"type": "string"}},
                    "required": ["key", "text"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    },
}

SYSTEM = """\
Du übersetzt Bewerbungstexte vom Deutschen ins Englische (britisch-neutrales Business-Englisch).
Regeln:
- Nur übersetzen. Nichts hinzufügen, nichts weglassen, nichts abmildern oder verstärken.
- Zahlen, Jahre, Firmennamen, Eigennamen, Produkt- und Technologienamen bleiben unverändert.
- Berufsbezeichnungen und Studiengänge mit der üblichen englischen Entsprechung \
(Werkstudent = Working Student, Praktikant = Intern, B.Sc. Informatik = B.Sc. Computer Science).
- Zeitformen bleiben erhalten (beendete Stationen im Past Tense).
- "Sehr geehrte Damen und Herren," wird "Dear Sir or Madam,", "Mit freundlichen Grüßen" wird \
"Kind regards,". Absätze (Leerzeilen) und Zeilenumbrüche im Brief bleiben wie im Original.
- Gib zu jedem Schlüssel genau eine Übersetzung zurück, unter demselben Schlüssel."""


def context_units(ctx: dict[str, Any]) -> dict[str, str]:
    """Every German text the CV shows, keyed by its place in the render context."""
    units: dict[str, str] = {}
    if ctx.get("headline"):
        units["headline"] = ctx["headline"]
    if ctx.get("summary"):
        units["summary"] = ctx["summary"]
    for i, job in enumerate(ctx["experience"]):
        units[f"exp.{i}.title"] = job["title"]
        for j, bullet in enumerate(job["bullets"]):
            units[f"exp.{i}.b.{j}"] = bullet["text"]
    for i, ed in enumerate(ctx["education"]):
        for field in ("degree", "focus", "thesis"):
            if ed.get(field):
                units[f"edu.{i}.{field}"] = ed[field]
    for i, project in enumerate(ctx["projects"]):
        units[f"proj.{i}.text"] = project["text"]
    for i, item in enumerate(ctx.get("other", [])):
        units[f"other.{i}"] = item
    for i, (_label, value) in enumerate(ctx["skill_rows"]):
        if i >= ctx.get("tech_rows", len(ctx["skill_rows"])):
            units[f"skill.{i}"] = value  # spoken languages and soft skills
    return units


def apply_units(ctx: dict[str, Any], english: dict[str, str]) -> dict[str, Any]:
    """The same context with the translated texts put in; everything else unchanged."""
    out = {**ctx}
    for key in ("headline", "summary"):
        if key in english:
            out[key] = english[key]
    out["experience"] = [
        {
            **job,
            "title": english.get(f"exp.{i}.title", job["title"]),
            "bullets": [
                {**b, "text": english.get(f"exp.{i}.b.{j}", b["text"])}
                for j, b in enumerate(job["bullets"])
            ],
        }
        for i, job in enumerate(ctx["experience"])
    ]
    out["education"] = [
        {**ed, **{f: english[f"edu.{i}.{f}"] for f in ("degree", "focus", "thesis")
                  if f"edu.{i}.{f}" in english}}
        for i, ed in enumerate(ctx["education"])
    ]
    out["projects"] = [
        {**p, "text": english.get(f"proj.{i}.text", p["text"])}
        for i, p in enumerate(ctx["projects"])
    ]
    out["other"] = [english.get(f"other.{i}", item) for i, item in enumerate(ctx.get("other", []))]
    out["skill_rows"] = [
        (label, english.get(f"skill.{i}", value))
        for i, (label, value) in enumerate(ctx["skill_rows"])
    ]
    return out


def _problems(german: dict[str, str], english: dict[str, str]) -> list[str]:
    problems = []
    for key, source in german.items():
        if not english.get(key, "").strip():
            problems.append(f"{key}: Übersetzung fehlt")
            continue
        for p in deterministic_problems(english[key], source):
            problems.append(f"{key}: {p.replace('im Profil', 'im Original')}")
    return problems


def translate_units(
    client: Any, model: str, units: dict[str, str]
) -> tuple[dict[str, str], list[tuple[str, Usage]]]:
    """Translate all units, retrying with the findings until the guard is satisfied."""
    usage: list[tuple[str, Usage]] = []
    feedback = ""
    for _ in range(MAX_TRIES):
        listing = "\n\n".join(f"[{key}]\n{text}" for key, text in units.items())
        payload, u = call_tool(
            client,
            model=model,
            system_text=SYSTEM,
            tool=TRANSLATE_TOOL,
            user_text=f"Übersetze diese Texte:\n\n{listing}{feedback}",
            max_tokens=16000,
        )
        usage.append((model, u))
        english = {item["key"]: item["text"].strip() for item in payload.get("items", [])}
        problems = _problems(units, english)
        if not problems:
            return english, usage
        feedback = (
            "\n\nDie vorige Übersetzung enthielt Abweichungen vom Original: "
            + "; ".join(problems[:8])
            + ". Übersetze noch einmal, genau und ohne Zusätze."
        )
    raise ValueError("translation kept adding facts: " + "; ".join(problems[:3]))
