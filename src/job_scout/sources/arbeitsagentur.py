"""Job board of the Bundesagentur für Arbeit (public API, key published by the agency).

One "company" row stands for one search: the slug is `what|where|radius_km`, e.g.
`Werkstudent Informatik|Darmstadt|50`. The employers come from the postings, so companies
without any own career system of the supported vendors show up too.
"""

import base64
from datetime import datetime

import httpx

from job_scout.models import JobPosting
from job_scout.sources.greenhouse import _strip_html

_BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4"
_HEADERS = {"X-API-Key": "jobboerse-jobsuche"}  # public key from the agency's documentation
_PAGE = 50
_MAX_PAGES = 2
_JOB_URL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"


def _parse_time(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def _description(client: httpx.Client, refnr: str) -> str:
    encoded = base64.b64encode(refnr.encode()).decode()
    try:
        response = client.get(f"{_BASE}/jobdetails/{encoded}", headers=_HEADERS, timeout=20)
        response.raise_for_status()
        return _strip_html(response.json().get("stellenbeschreibung", ""))
    except (httpx.HTTPError, ValueError):
        return ""  # title and place can still be scored


def fetch(client: httpx.Client, company_name: str, slug: str) -> list[JobPosting]:
    what, where, radius = (slug.split("|") + ["", "", "50"])[:3]
    postings: list[JobPosting] = []
    for page in range(1, _MAX_PAGES + 1):
        response = client.get(
            f"{_BASE}/jobs",
            params={"was": what, "wo": where, "umkreis": radius or "50", "size": _PAGE,
                    "page": page, "angebotsart": 1},
            headers=_HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        items = response.json().get("stellenangebote", [])
        for item in items:
            refnr = item["refnr"]
            place = (item.get("arbeitsort") or {}).get("ort")
            postings.append(
                JobPosting(
                    source="arbeitsagentur",
                    external_id=refnr,
                    company_name=item.get("arbeitgeber") or company_name,
                    title=item.get("titel") or item.get("beruf") or "",
                    url=_JOB_URL.format(refnr=refnr),
                    location=f"{place}, Deutschland" if place else None,
                    remote=False,
                    description=_description(client, refnr),
                    posted_at=_parse_time(item.get("aktuelleVeroeffentlichungsdatum")),
                )
            )
        if len(items) < _PAGE:
            break
    return postings
