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

_BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc"
_SEARCH = f"{_BASE}/v6/jobs"
_DETAILS = f"{_BASE}/v4/jobdetails"  # v6 has no details route (403), v4 still answers
_HEADERS = {"X-API-Key": "jobboerse-jobsuche"}  # public key from the agency's documentation
_PAGE = 50
_MAX_PAGES = 3
_JOB_URL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"


def _parse_time(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


# Overlapping searches return the same postings; each posting's text is fetched once per run.
_DESCRIPTIONS: dict[str, str] = {}


def _description(client: httpx.Client, refnr: str) -> str:
    if refnr in _DESCRIPTIONS:
        return _DESCRIPTIONS[refnr]
    encoded = base64.b64encode(refnr.encode()).decode()
    try:
        response = client.get(f"{_DETAILS}/{encoded}", headers=_HEADERS, timeout=20)
        response.raise_for_status()
        text = _strip_html(response.json().get("stellenangebotsBeschreibung", ""))
    except (httpx.HTTPError, ValueError):
        return ""  # title and place can still be scored; a failed fetch is tried again later
    _DESCRIPTIONS[refnr] = text
    return text


def fetch(client: httpx.Client, company_name: str, slug: str) -> list[JobPosting]:
    what, where, radius = (slug.split("|") + ["", "", "50"])[:3]
    postings: list[JobPosting] = []
    for page in range(1, _MAX_PAGES + 1):
        response = client.get(
            _SEARCH,
            params={"was": what, "wo": where, "umkreis": radius or "50", "size": _PAGE,
                    "page": page},
            headers=_HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        items = response.json().get("ergebnisliste", [])
        for item in items:
            # Werkstudent postings are filed as "PRAKTIKUM_TRAINEE", so the type is not filtered;
            # apprenticeships are not wanted.
            if "AUSBILDUNG" in (item.get("stellenangebotsart") or ""):
                continue
            refnr = item["referenznummer"]
            places = item.get("stellenlokationen") or []
            place = (places[0].get("adresse") or {}).get("ort") if places else None
            postings.append(
                JobPosting(
                    source="arbeitsagentur",
                    external_id=refnr,
                    company_name=item.get("firma") or company_name,
                    title=item.get("stellenangebotsTitel") or item.get("hauptberuf") or "",
                    url=_JOB_URL.format(refnr=refnr),
                    location=f"{place}, Deutschland" if place else None,
                    remote=False,
                    description=_description(client, refnr),
                    posted_at=_parse_time(
                        item.get("datumErsteVeroeffentlichung") or item.get("aenderungsdatum")
                    ),
                )
            )
        if len(items) < _PAGE:
            break
    return postings
