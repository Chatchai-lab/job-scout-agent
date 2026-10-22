"""SmartRecruiters posting API (public, no auth).

The list endpoint has no description, so each posting needs one detail call. To keep that
cheap, only postings in Germany are requested; remote roles elsewhere are out of scope anyway.
"""

from datetime import datetime

import httpx

from job_scout.models import JobPosting
from job_scout.sources.greenhouse import _strip_html

_LIST = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
_JOB_URL = "https://jobs.smartrecruiters.com/{slug}/{id}"
_PAGE = 100


def _parse_time(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def _description(client: httpx.Client, slug: str, posting_id: str) -> str:
    response = client.get(f"{_LIST.format(slug=slug)}/{posting_id}", timeout=20)
    response.raise_for_status()
    sections = response.json().get("jobAd", {}).get("sections", {})
    return " ".join(
        _strip_html(section.get("text", "")) for section in sections.values()
    ).strip()


def fetch(client: httpx.Client, company_name: str, slug: str) -> list[JobPosting]:
    items: list[dict] = []
    while True:
        response = client.get(
            _LIST.format(slug=slug),
            params={"limit": _PAGE, "offset": len(items), "country": "de"},
            timeout=20,
        )
        response.raise_for_status()
        page = response.json().get("content", [])
        items.extend(page)
        if len(page) < _PAGE:
            break
    postings = []
    for item in items:
        place = item.get("location", {})
        location = ", ".join(p for p in (place.get("city"), place.get("country", "").upper()) if p)
        postings.append(
            JobPosting(
                source="smartrecruiters",
                external_id=str(item["id"]),
                company_name=company_name,
                title=item.get("name", ""),
                url=_JOB_URL.format(slug=slug, id=item["id"]),
                location=location or None,
                remote=bool(place.get("remote")),
                description=_description(client, slug, str(item["id"])),
                posted_at=_parse_time(item.get("releasedDate")),
            )
        )
    return postings
