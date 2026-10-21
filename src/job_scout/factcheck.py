"""Fact check for generated application texts.

The master profile is the only source of facts. Two layers:
1. Deterministic: every number and every known technology name in a generated text has to
   appear in the profile (or, for the cover letter, in the job posting).
2. LLM: a second call compares the texts against the profile and lists unsupported claims.
Anything flagged falls back to the original profile wording or gets regenerated.
"""

import re
from typing import Any

import yaml

from job_scout.pricing import Usage
from job_scout.toolcall import call_tool

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
# Technologies and tools that must never appear unless the profile mentions them.
TECH_VOCAB = [
    "python", "c++", "c#", "java", "javascript", "typescript", "react", "angular", "vue", "node",
    "next.js", "sql", "postgresql", "mysql", "mongodb", "redis", "kafka", "spark", "snowflake",
    "databricks", "docker", "kubernetes", "terraform", "ansible", "aws", "azure", "gcp",
    "linux", "git", "github actions", "gitlab", "jenkins", "fastapi", "django", "flask",
    "pytorch", "tensorflow", "langchain", "llm", "rag", "n8n", "power bi", "knime", "unity",
    "rust", "golang", "scala", "kotlin", "swift", "graphql", "elasticsearch", "airflow", "dbt",
    "tableau", "salesforce", "sap", "mqtt", "supabase", "vercel",
]


def profile_corpus(profile: dict[str, Any]) -> str:
    """All profile text in one lowercase string for substring checks."""
    return yaml.safe_dump(profile, allow_unicode=True).lower()


def _tech_in(text: str) -> set[str]:
    low = text.lower()
    found = set()
    for term in TECH_VOCAB:
        pattern = r"(?<![a-z0-9+#.])" + re.escape(term) + r"(?![a-z0-9+#])"
        if re.search(pattern, low):
            found.add(term)
    return found


def deterministic_problems(text: str, *sources: str) -> list[str]:
    """Numbers and technologies in `text` that none of the `sources` contain."""
    haystack = " ".join(sources).lower()
    problems = []
    for number in sorted(set(_NUMBER.findall(text))):
        if not re.search(r"(?<![\d.,])" + re.escape(number) + r"(?![\d])", haystack):
            problems.append(f"Zahl '{number}' steht nicht im Profil")
    for term in sorted(_tech_in(text)):
        if term not in _tech_in(haystack):
            problems.append(f"Technologie '{term}' steht nicht im Profil")
    return problems


FACTCHECK_TOOL: dict[str, Any] = {
    "name": "submit_factcheck",
    "description": "Report every claim in the generated texts that the profile does not support.",
    "input_schema": {
        "type": "object",
        "properties": {
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "string",
                            "description": "summary, cover_letter or bullet:<bullet id>",
                        },
                        "problem": {"type": "string", "description": "What is unsupported."},
                    },
                    "required": ["target", "problem"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["issues"],
        "additionalProperties": False,
    },
}

_CHECK_INSTRUCTIONS = """\
Du bist ein strenger Faktenprüfer für Bewerbungsunterlagen. Das Profil unten ist die einzige \
Faktenquelle. Prüfe die generierten Texte gegen das Profil.

Melde einen Fehler, wenn ein Text Folgendes enthält, das das Profil nicht belegt:
- Berufserfahrung, Jahre, Zahlen, Ergebnisse, Verantwortung oder Kunden, die nicht im Profil stehen
- Technologien, Tools oder Zertifikate, die nicht im Profil stehen
- Aufgaben, die über die Stichpunkte im Profil hinausgehen (Übertreibung zählt)
Nicht gemeldet wird: andere Wortwahl, Umstellung der Reihenfolge, Verweise auf die ausgeschriebene \
Stelle und die Firma, allgemeine Motivation, Start im März 2027.
Gib bei "target" an: summary, cover_letter oder bullet:<id>. Wenn alles belegt ist: leere Liste.
Antworte ausschließlich über das Tool submit_factcheck."""


def build_check_system(profile_text: str) -> str:
    return _CHECK_INSTRUCTIONS + "\n\n## Profil (einzige Faktenquelle)\n" + profile_text


def build_check_user(
    *, summary: str, cover_letter: str, rewrites: dict[str, tuple[str, str]], job_text: str
) -> str:
    parts = ["## Stellenanzeige (nur für Verweise auf Stelle und Firma)\n" + job_text[:3000]]
    parts.append("## summary\n" + summary)
    for bullet_id, (original, new) in rewrites.items():
        parts.append(f"## bullet:{bullet_id}\nOriginal: {original}\nNeu: {new}")
    parts.append("## cover_letter\n" + cover_letter)
    return "\n\n".join(parts)


def llm_check(
    client: Any, model: str, profile_text: str, **texts: Any
) -> tuple[list[dict[str, str]], Usage]:
    payload, usage = call_tool(
        client,
        model=model,
        system_text=build_check_system(profile_text),
        tool=FACTCHECK_TOOL,
        user_text=build_check_user(**texts),
        max_tokens=8000,  # thinking tokens count against this limit
    )
    issues = [
        {"target": str(i.get("target", "")), "problem": str(i.get("problem", ""))}
        for i in payload.get("issues", [])
    ]
    return issues, usage
