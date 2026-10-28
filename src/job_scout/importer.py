"""Import a posting found by hand (link or pasted text): read it, score it, send the card.

The web app stores a placeholder row (closed, so triage and digest skip it) and dispatches this
job. A link is fetched and read by the model; pasted text is used as it is.
"""

import html
import json
import logging
import re
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel

from job_scout.config import Settings
from job_scout.models import JobPosting
from job_scout.notify import Notifier, format_job
from job_scout.prefilter import WORKING_STUDENT_TITLE
from job_scout.pricing import Usage, cost_usd
from job_scout.repo import Repo
from job_scout.scoring import ScoreResult, build_system, usage_from
from job_scout.triage import posting_from_row

log = logging.getLogger(__name__)

MIN_TEXT = 200  # shorter page text means a login wall, a script-only page or an error page
MAX_PAGE_CHARS = 15000
_BROWSER = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
_JSON_LD = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S
)
_DROP_BLOCKS = re.compile(
    r"<(script|style|noscript|svg|nav|footer|header|form)\b.*?</\1>", re.I | re.S
)
_BLOCK_TAG = re.compile(
    r"</?(?:p|div|li|ul|ol|h[1-6]|br|tr|td|section|article|table)\b[^>]*>", re.I
)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")

HELP_UNREADABLE = (
    "🔗 Diese Seite konnte ich nicht lesen (Login, Skript-Seite oder gesperrt).\n"
    "Schick mir stattdessen den kopierten Text der Anzeige:\n"
    "<code>Stelle Firma: Jobtitel</code>\n"
    "und darunter den Text."
)


def _text(markup: str) -> str:
    plain = html.unescape(_TAG.sub("", _BLOCK_TAG.sub("\n", markup or "")))
    plain = "\n".join(_SPACE.sub(" ", line).strip() for line in plain.splitlines())
    return _BLANK_LINES.sub("\n\n", plain).strip()


def _job_posting_nodes(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [n for item in data for n in _job_posting_nodes(item)]
    if not isinstance(data, dict):
        return []
    found = _job_posting_nodes(data.get("@graph", []))
    kind = data.get("@type")
    if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
        found.append(data)
    return found


def _json_ld_text(page: str) -> str:
    for block in _JSON_LD.findall(page):
        try:
            nodes = _job_posting_nodes(json.loads(block.strip()))
        except ValueError:
            continue
        for node in nodes:
            org = node.get("hiringOrganization")
            place = node.get("jobLocation")
            place = place[0] if isinstance(place, list) and place else place
            address = place.get("address") if isinstance(place, dict) else None
            city = address.get("addressLocality") if isinstance(address, dict) else None
            parts = [
                f"Titel: {node.get('title', '')}",
                f"Firma: {org.get('name', '') if isinstance(org, dict) else org or ''}",
                f"Ort: {city or ''}",
                _text(str(node.get("description", ""))),
            ]
            text = "\n".join(p for p in parts if p.split(": ")[-1])
            if len(text) >= MIN_TEXT:
                return text
    return ""


def extract_page_text(page: str) -> str:
    """Structured job data if the page has it, else the visible text without menus and scripts."""
    structured = _json_ld_text(page)
    if structured:
        return structured[:MAX_PAGE_CHARS]
    return _text(_DROP_BLOCKS.sub(" ", page))[:MAX_PAGE_CHARS]


def fetch_page(client: httpx.Client, url: str) -> str:
    if not re.match(r"https?://", url or "", re.I):
        raise ValueError("not an http(s) link")
    response = client.get(
        url, headers={"User-Agent": _BROWSER, "Accept-Language": "de,en;q=0.8"},
        follow_redirects=True, timeout=25,
    )
    response.raise_for_status()
    if "html" not in response.headers.get("content-type", "text/html"):
        raise ValueError("not an HTML page")
    return extract_page_text(response.text[:2_000_000])


class ReadPosting(BaseModel):
    is_job_posting: bool
    company: str = ""
    title: str = ""
    location: str | None = None
    remote: bool = False
    description: str = ""


READ_TOOL: dict[str, Any] = {
    "name": "submit_posting",
    "description": "Return the job posting found in the page text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_job_posting": {"type": "boolean", "description": "False if the page is no job ad."},
            "company": {"type": "string"},
            "title": {"type": "string", "description": "Job title as written in the ad."},
            "location": {"type": ["string", "null"], "description": "City or null."},
            "remote": {"type": "boolean"},
            "description": {
                "type": "string",
                "description": "Tasks, requirements and offer, cleaned, at most 6000 characters.",
            },
        },
        "required": ["is_job_posting", "company", "title", "remote", "description"],
    },
}
READ_SYSTEM = (
    "Du bekommst den Text einer Webseite. Ist es eine Stellenanzeige, gib Firma, Jobtitel, Ort, "
    "Remote-Möglichkeit und die bereinigte Beschreibung zurück (Aufgaben, Anforderungen, Angebot; "
    "ohne Menüs, Cookie-Hinweise und Werbung). Erfinde nichts. Ist es keine Stellenanzeige, "
    "setze is_job_posting auf false."
)


def read_posting(client: Any, model: str, text: str, url: str) -> tuple[ReadPosting, Usage]:
    response = client.messages.create(
        model=model,
        max_tokens=3000,
        system=READ_SYSTEM,
        tools=[READ_TOOL],
        tool_choice={"type": "tool", "name": "submit_posting"},
        messages=[{"role": "user", "content": f"Link: {url}\n\nSeitentext:\n{text}"}],
    )
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "submit_posting":
            return ReadPosting(**block.input), usage_from(response)
    raise ValueError("model did not call submit_posting")


def _log_usage(repo: Repo, settings: Settings, purpose: str, usage: Usage, cost: float) -> None:
    repo.log_usage(
        {
            "purpose": purpose,
            "model": settings.model_match,
            "input_tokens": usage.input_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": round(cost, 6),
        }
    )


def run_import(
    repo: Repo,
    settings: Settings,
    notifier: Notifier,
    job_id: str,
    *,
    fetch_fn: Callable[[str], str],
    read_fn: Callable[[str, str], tuple[ReadPosting, Usage]],
    score_fn: Callable[[str, JobPosting], tuple[ScoreResult, Usage]],
    profile_text: str,
) -> str:
    """Returns sent, resent, unreadable, not_a_posting, budget or unknown."""
    row = repo.package_job(job_id)
    if row is None:
        return "unknown"
    known = repo.scored_job(job_id)
    if known is not None and not known["jobs"].get("closed_at"):
        notifier.send("🔁 " + format_job(known["jobs"], known), job_id)
        return "resent"

    budget_usd = settings.monthly_budget_eur / settings.eur_per_usd
    if repo.month_cost_usd() >= budget_usd:
        notifier.send("💶 Monatsbudget erreicht, die Stelle wurde nicht gelesen.")
        repo.delete_job(job_id)
        return "budget"

    fields: dict[str, Any] = {"closed_at": None}
    if not (row.get("description") or "").strip():
        try:
            text = fetch_fn(row["url"])
        except Exception as exc:
            log.warning("fetch failed: %s", type(exc).__name__)
            text = ""
        if len(text) < MIN_TEXT:
            notifier.send(HELP_UNREADABLE)
            repo.delete_job(job_id)
            return "unreadable"
        read, usage = read_fn(text, row["url"])
        _log_usage(repo, settings, "import", usage, cost_usd(settings.model_match, usage))
        if not read.is_job_posting or not read.description.strip() or not read.title.strip():
            notifier.send("🔗 Das sieht nicht nach einer Stellenanzeige aus.\n" + HELP_UNREADABLE)
            repo.delete_job(job_id)
            return "not_a_posting"
        fields.update(
            company_name=read.company.strip() or row["company_name"],
            title=read.title.strip(),
            location=read.location,
            remote=read.remote,
            description=read.description.strip(),
        )
    merged = {**row, **fields}
    fields["dedup_key"] = posting_from_row(merged).dedup_key
    if WORKING_STUDENT_TITLE.search(merged["title"] or ""):
        fields["kind"] = "working_student"
    repo.update_job(job_id, fields)

    posting = posting_from_row({**merged, **fields})
    result, usage = score_fn(build_system(profile_text, repo.approved_rules()), posting)
    cost = cost_usd(settings.model_match, usage)
    repo.save_score(
        {"job_id": job_id, **result.model_dump(), "model": settings.model_match,
         "cost_usd": round(cost, 6)}
    )
    _log_usage(repo, settings, "match", usage, cost)
    repo.mark_notified([job_id])  # the card below is the notification, not the digest
    scored = repo.scored_job(job_id)
    if scored is not None:
        notifier.send("🔗 " + format_job(scored["jobs"], scored), job_id)
    return "sent"
