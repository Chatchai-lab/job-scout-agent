"""Application package: tailored CV selection, cover letter draft and gap analysis.

Flow: Sonnet drafts (forced tool call) -> selection is validated against the profile ->
deterministic and LLM fact check -> flagged parts fall back to the profile wording; a flagged
cover letter is regenerated once. The profile stays the only source of facts.
"""

import html
import re
import shutil
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, Field

from job_scout.config import Settings
from job_scout.cvrender import render_cv
from job_scout.factcheck import deterministic_problems, llm_check, profile_corpus
from job_scout.letterrender import render_letter
from job_scout.pricing import Usage, cost_usd
from job_scout.toolcall import call_tool

MAX_DESCRIPTION_CHARS = 6000
PHOTO_BUCKET = "cv-assets"
_STATUS_ICON = {"erfüllt": "✅", "teilweise": "🟡", "fehlt": "❌"}


class GapItem(BaseModel):
    requirement: str
    status: Literal["erfüllt", "teilweise", "fehlt"]
    note: str


class BulletPick(BaseModel):
    entry_id: str
    bullet_ids: list[str]


class Rewrite(BaseModel):
    bullet_id: str
    text: str


class Draft(BaseModel):
    headline: str
    summary: str
    picks: list[BulletPick]
    rewrites: list[Rewrite] = Field(default_factory=list)
    cover_letter: str
    gaps: list[GapItem]


DRAFT_TOOL: dict[str, Any] = {
    "name": "submit_package",
    "description": "Submit the tailored CV selection, cover letter and gap analysis.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "description": "CV tagline: 'Angehender <role of the job>', max 6 words.",
            },
            "summary": {"type": "string", "description": "CV profile text, 2-3 sentences."},
            "picks": {
                "type": "array",
                "description": "Per experience/project id: bullet ids in display order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "entry_id": {"type": "string"},
                        "bullet_ids": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["entry_id", "bullet_ids"],
                    "additionalProperties": False,
                },
            },
            "rewrites": {
                "type": "array",
                "description": "Reworded bullets (same facts, other emphasis).",
                "items": {
                    "type": "object",
                    "properties": {"bullet_id": {"type": "string"}, "text": {"type": "string"}},
                    "required": ["bullet_id", "text"],
                    "additionalProperties": False,
                },
            },
            "cover_letter": {"type": "string"},
            "gaps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "requirement": {"type": "string"},
                        "status": {"type": "string", "enum": ["erfüllt", "teilweise", "fehlt"]},
                        "note": {"type": "string"},
                    },
                    "required": ["requirement", "status", "note"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["headline", "summary", "picks", "rewrites", "cover_letter", "gaps"],
        "additionalProperties": False,
    },
}

INSTRUCTIONS = """\
Du erstellst Bewerbungsunterlagen für den Kandidaten im Profil unten. Das Profil ist die EINZIGE \
Faktenquelle.

Harte Regeln:
- Erfinde nichts: keine Erfahrungen, Zahlen, Technologien, Firmen, Ergebnisse, Titel oder \
Zertifikate, die nicht im Profil stehen.
- Wähle und ordne nur vorhandene Stichpunkte (über ihre IDs). Mit "rewrites" darfst du Wortwahl \
und Betonung anpassen, nie den Inhalt. Begriffe aus der Anzeige nur verwenden, wenn der \
Originalstichpunkt dasselbe meint.
- Jede Station (experience-ID) behält mindestens einen Stichpunkt, die relevantesten zuerst. \
Wenig relevante Stichpunkte darfst du weglassen.
- Projekte: Wähle 2 bis 3 Projekte, die zur Stelle passen, mit den passenden Stichpunkten. \
Projekte mit "highlight: true" im Profil gehören bei Stellen mit KI-, Automatisierungs-, \
Applied-AI-, Forward-Deployed- oder Solutions-Bezug immer in "picks". Bei anderen Stellen nimmst \
du sie nur, wenn sie zur Anzeige passen.
- headline: Die Überschrift unter dem Namen. "Angehender " plus die Rollenbezeichnung der Stelle, \
ohne Firma, Ort, (m/w/d) und Seniorität, höchstens 6 Wörter, z. B. "Angehender Forward Deployed \
Engineer". Das ist die Zielrolle, keine behauptete Erfahrung.
- summary: 2 bis 3 Sätze. Der erste Satz beginnt mit derselben Rollenbezeichnung wie die headline \
und nennt Studiengang und Hochschule aus dem Profil ("Angehender … (B.Sc. …, …)"). Danach 1 bis 2 \
Sätze mit den für DIESE Stelle relevantesten belegten Stärken (Projekte, Praxis, Technik). Nur \
belegte Fakten.
- cover_letter: Deutsch, formell, 180 bis 230 Wörter. Beginnt mit \
"Sehr geehrte Damen und Herren,", endet mit "Mit freundlichen Grüßen" und dem Namen aus dem \
Profil. Nenne Firma und Stelle, 2 bis 3 belegte Gründe für die Passung, den frühesten Start \
(März 2027) und den Bachelor-Abschluss im Februar 2027. Sei ehrlich bei Lücken (z. B. wenig \
Berufserfahrung), ohne zu übertreiben. Keine Platzhalter wie [Name]. Nenne höchstens EIN Projekt \
aus dem Profil in ein bis zwei Sätzen, nur als Beleg für etwas, das die Stelle verlangt, und nur \
bei KI-, Automatisierungs- oder Engineering-Stellen. Der Brief handelt von der Firma und dem \
Kandidaten, nicht von seinen Projekten.
- gaps: 4 bis 8 zentrale Anforderungen der Anzeige, je mit Status (erfüllt, teilweise, fehlt) und \
kurzer Begründung mit Bezug auf das Profil.
Antworte ausschließlich über das Tool submit_package."""


MAX_WARNING_ISSUES = 3


def build_draft_system(profile_text: str) -> str:
    return INSTRUCTIONS + "\n\n## Profil (einzige Faktenquelle)\n" + profile_text


INITIATIVE_NOTE = """\
INITIATIVBEWERBUNG: Es gibt keine ausgeschriebene Stelle. Der Kandidat bewirbt sich aus eigener \
Initiative bei der Firma unten.
- Zielrolle: Wähle aus target.roles im Profil die Rolle, die zu den Angaben zur Firma und zum \
Profil am besten passt. headline und summary nutzen diese Rolle ("Angehender <Rolle>").
- cover_letter: Betreff-Gedanke "Initiativbewerbung als <Rolle>". Nenne die Firma, aber behaupte \
NICHTS über die Firma, das nicht in den Angaben unten steht (keine Produkte, Kunden, Werte oder \
Projekte erfinden). Nenne 2 bis 3 belegte Gründe aus dem Profil, warum der Kandidat für diese \
Rolle passt, und frage nach einem Gespräch. Frühester Start März 2027.
- gaps: 4 bis 8 typische Anforderungen der Zielrolle (nicht der Firma) mit Status und Begründung \
aus dem Profil."""


WORKING_STUDENT_NOTE = """\
WERKSTUDENTENSTELLE: Der Kandidat bewirbt sich neben dem Studium (B.Sc. Informatik, Hochschule \
Darmstadt, Abschluss Februar 2027) auf eine Teilzeitstelle. Abweichend von den Regeln oben:
- cover_letter: Nenne statt des Vollzeitstarts im März 2027 die Verfügbarkeit aus \
target.availability_werkstudent im Profil (Stunden pro Woche, Start). Erwähne das laufende \
Studium und den Bezug der Stelle zum Studium. Erfinde keine Verfügbarkeit.
- headline: "Informatikstudent (B.Sc.)" plus Fachgebiet der Stelle, höchstens 6 Wörter.
- summary: erster Satz beginnt mit "Informatikstudent (B.Sc. …, Hochschule Darmstadt)".
"""


def job_text(job: dict[str, Any]) -> str:
    description = (job.get("description") or "")[:MAX_DESCRIPTION_CHARS]
    if job.get("kind") == "working_student":
        return WORKING_STUDENT_NOTE + "\n" + (
            f"Firma: {job['company_name']}\nTitel: {job['title']}\n"
            f"Ort: {job.get('location') or 'unbekannt'}\nLink: {job['url']}\n\n"
            f"Beschreibung:\n{description or '(keine)'}"
        )
    if job.get("kind") == "initiative":
        return (
            INITIATIVE_NOTE + "\n\n"
            f"Firma: {job['company_name']}\nAnzeige/Link: {job.get('url') or '(keiner)'}\n"
            f"Angaben zur Firma:\n{description or '(keine, schreibe allgemein)'}"
        )
    return (
        f"Firma: {job['company_name']}\nTitel: {job['title']}\n"
        f"Ort: {job.get('location') or 'unbekannt'}\nLink: {job['url']}\n\n"
        f"Beschreibung:\n{description or '(keine)'}"
    )


def build_draft_user(job: dict[str, Any], feedback: list[str] | None) -> str:
    text = job_text(job)
    if feedback:
        text += (
            "\n\nDie vorige Fassung des Anschreibens enthielt unbelegte Angaben: "
            + "; ".join(feedback)
            + ". Schreibe es neu und lasse diese Angaben weg."
        )
    return text


def draft_package(
    client: Any, model: str, profile_text: str, job: dict[str, Any],
    feedback: list[str] | None = None,
) -> tuple[Draft, Usage]:
    payload, usage = call_tool(
        client,
        model=model,
        system_text=build_draft_system(profile_text),
        tool=DRAFT_TOOL,
        user_text=build_draft_user(job, feedback),
        max_tokens=16000,  # thinking tokens count against this limit
    )
    return Draft(**payload), usage


def _entries(profile: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """experience/project id -> its bullets, straight from the profile."""
    found: dict[str, list[dict[str, str]]] = {}
    for section in ("experience", "projects"):
        for entry in profile.get(section, []):
            found[entry["id"]] = entry.get("bullets", [])
    return found


def build_selection(draft: Draft, profile: dict[str, Any]) -> dict[str, Any]:
    """Turn a draft into a renderer selection; unknown ids are dropped, never invented."""
    entries = _entries(profile)
    original = {b["id"]: b["text"] for bullets in entries.values() for b in bullets}
    chosen: dict[str, list[str]] = {}
    for pick in draft.picks:
        valid = {b["id"] for b in entries.get(pick.entry_id, [])}
        ids = list(dict.fromkeys(i for i in pick.bullet_ids if i in valid))
        if ids:
            chosen[pick.entry_id] = ids
    shown = {i for ids in chosen.values() for i in ids}
    rewrites = {
        r.bullet_id: " ".join(r.text.split())
        for r in draft.rewrites
        if r.bullet_id in shown and r.bullet_id in original and r.text.strip()
        and " ".join(r.text.split()) != original[r.bullet_id]
    }
    project_ids = {p["id"] for p in profile.get("projects", [])}
    return {
        "headline": " ".join(draft.headline.split()) or None,
        "summary": " ".join(draft.summary.split()) or None,
        "bullets": chosen,
        "rewrites": rewrites,
        "projects_chosen": [e for e in chosen if e in project_ids],
    }


@dataclass
class PackageResult:
    selection: dict[str, Any]
    cover_letter: str
    gaps: list[dict[str, str]]
    warnings: list[str] = field(default_factory=list)
    usage: list[tuple[str, Usage]] = field(default_factory=list)

    def cost_usd(self) -> float:
        return sum(cost_usd(model, u) for model, u in self.usage)


def create_package(
    client: Any, settings: Settings, profile_text: str, job: dict[str, Any]
) -> PackageResult:
    profile = yaml.safe_load(profile_text)
    corpus = profile_corpus(profile)
    posting = job_text(job)
    original = {
        b["id"]: b["text"] for bullets in _entries(profile).values() for b in bullets
    }
    usage: list[tuple[str, Usage]] = []
    feedback: list[str] | None = None

    for attempt in range(2):
        draft, u = draft_package(client, settings.model_package, profile_text, job, feedback)
        usage.append((settings.model_package, u))
        selection = build_selection(draft, profile)
        rewrites = selection["rewrites"]

        bad_rewrites = {i for i, text in rewrites.items() if deterministic_problems(text, corpus)}
        summary_bad = bool(selection["summary"]) and bool(
            deterministic_problems(selection["summary"], corpus)
        )
        headline_bad = bool(selection["headline"]) and bool(
            deterministic_problems(selection["headline"], corpus, posting)
        )
        letter_problems = deterministic_problems(draft.cover_letter, corpus, posting)

        issues, u2 = llm_check(
            client,
            settings.model_package,
            profile_text,
            headline=selection["headline"] or "",
            summary=selection["summary"] or profile.get("summary", ""),
            cover_letter=draft.cover_letter,
            rewrites={i: (original[i], t) for i, t in rewrites.items()},
            job_text=posting,
        )
        usage.append((settings.model_package, u2))
        for issue in issues:
            target = issue["target"]
            if target.startswith("bullet:"):
                bad_rewrites.add(target.split(":", 1)[1])
            elif target == "summary":
                summary_bad = True
            elif target == "headline":
                headline_bad = True
            elif target == "cover_letter":
                letter_problems.append(issue["problem"])

        for bullet_id in bad_rewrites:
            rewrites.pop(bullet_id, None)  # fall back to the profile wording
        if summary_bad:
            selection["summary"] = None  # renderer then uses the profile summary
        if headline_bad:
            selection["headline"] = None  # renderer then uses the profile headline
        if letter_problems and attempt == 0:
            feedback = letter_problems
            continue
        warnings = [f"Anschreiben: {p}" for p in letter_problems[:MAX_WARNING_ISSUES]]
        if bad_rewrites:
            warnings.append(
                f"{len(bad_rewrites)} umformulierte Stichpunkte verworfen (Originaltext bleibt)"
            )
        return PackageResult(
            selection=selection,
            cover_letter=draft.cover_letter.strip(),
            gaps=[g.model_dump() for g in draft.gaps],
            warnings=warnings,
            usage=usage,
        )
    raise AssertionError("unreachable")  # pragma: no cover


class PackageNotifier(Protocol):
    def send(self, text: str, job_id: str | None = None) -> None: ...
    def send_document(self, path: Path, caption: str | None = None) -> None: ...


BuildPdf = Callable[..., Path]  # (tex, photo, workdir, name="cv") -> pdf path


def file_slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", ascii_text).strip("_") or "Datei"


def _berlin_today() -> date:
    try:
        return datetime.now(ZoneInfo("Europe/Berlin")).date()
    except ZoneInfoNotFoundError:
        return date.today()


def _named_copy(source: Path, name: str) -> Path:
    """The PDF under the file name the user will later send to the employer."""
    target = source.with_name(name)
    shutil.copyfile(source, target)
    return target


def format_gaps(gaps: list[dict[str, str]]) -> str:
    lines = ["🔍 <b>Gap-Analyse</b>", ""]
    for g in gaps:
        icon = _STATUS_ICON.get(g["status"], "•")
        lines.append(f"{icon} <b>{html.escape(g['requirement'])}</b>\n{html.escape(g['note'])}")
    return "\n".join(lines)[:4000]


def run_package(
    repo: Any,
    settings: Settings,
    client: Any,
    notifier: PackageNotifier,
    job_id: str,
    *,
    build_pdf: BuildPdf,
    workdir: Path,
    today: date | None = None,
) -> bool:
    """Build and deliver the package for one job. Returns False if the job is unknown."""
    job = repo.package_job(job_id)
    if job is None:
        notifier.send("📦 Paket: Diese Stelle ist nicht bekannt.")
        return False
    profile_text = repo.private_profile()
    if not profile_text:
        raise RuntimeError("profile_private has no row 'main'")
    profile = yaml.safe_load(profile_text)

    result = create_package(client, settings, profile_text, job)
    # Log the spend right away: a later failure must not hide what the API calls cost.
    for model, u in result.usage:
        repo.log_usage(
            {
                "purpose": "package",
                "model": model,
                "input_tokens": u.input_tokens,
                "cache_read_tokens": u.cache_read_tokens,
                "output_tokens": u.output_tokens,
                "cost_usd": round(cost_usd(model, u), 6),
            }
        )

    photo: bytes | None = None
    photo_name = profile.get("person", {}).get("photo")
    if photo_name:
        try:
            photo = repo.download_asset(PHOTO_BUCKET, photo_name)
        except Exception:  # the CV still builds without a photo
            result.warnings.append("Foto konnte nicht geladen werden, CV ohne Foto")

    tex = render_cv(profile, result.selection, has_photo=photo is not None)
    cv_pdf = build_pdf(tex, photo, workdir)
    letter_tex = render_letter(profile, result.cover_letter, job, today or _berlin_today())
    letter_pdf = build_pdf(letter_tex, None, workdir, "letter")

    person = file_slug(profile["person"]["name"])
    cv_file = _named_copy(cv_pdf, f"Lebenslauf_{person}.pdf")
    letter_file = _named_copy(
        letter_pdf, f"Anschreiben_{file_slug(job['company_name'])}_{person}.pdf"
    )
    label = f"{job['company_name']} – {job['title']}"
    notifier.send_document(cv_file, caption=f"📦 CV für {label}"[:1000])
    notifier.send_document(letter_file, caption=f"✉️ Anschreiben für {label}"[:1000])
    notifier.send(format_gaps(result.gaps))

    # Persisting comes after delivery: the user gets the package even if storage fails.
    stored_cv = f"packages/{job_id}/{cv_file.name}"
    stored_letter = f"packages/{job_id}/{letter_file.name}"
    try:
        repo.upload_asset(PHOTO_BUCKET, stored_cv, cv_file.read_bytes(), "application/pdf")
        repo.upload_asset(PHOTO_BUCKET, stored_letter, letter_file.read_bytes(), "application/pdf")
        repo.save_package(
            job_id,
            cv_pdf_path=stored_cv,
            letter_pdf_path=stored_letter,
            cover_letter=result.cover_letter,
            gaps=result.gaps,
        )
    except Exception as exc:
        result.warnings.append(f"Speichern in Supabase fehlgeschlagen ({type(exc).__name__})")
    if result.warnings:
        lines = "\n".join(html.escape(w) for w in result.warnings)
        notifier.send("⚠️ <b>Bitte prüfen</b>\n" + lines)
    return True
