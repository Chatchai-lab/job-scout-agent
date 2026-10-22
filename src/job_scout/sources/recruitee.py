"""Recruitee careers API: https://<slug>.recruitee.com/api/offers/ (public, no auth)."""

from datetime import datetime

import httpx

from job_scout.models import JobPosting
from job_scout.sources.greenhouse import _strip_html

_URL = "https://{slug}.recruitee.com/api/offers/"


def _parse_time(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def fetch(client: httpx.Client, company_name: str, slug: str) -> list[JobPosting]:
    response = client.get(_URL.format(slug=slug), timeout=20)
    response.raise_for_status()
    postings = []
    for offer in response.json().get("offers", []):
        if offer.get("status") not in (None, "published"):
            continue
        location = offer.get("location") or ", ".join(
            part for part in (offer.get("city"), offer.get("country")) if part
        )
        description = " ".join(
            _strip_html(offer.get(key, "")) for key in ("description", "requirements")
        ).strip()
        postings.append(
            JobPosting(
                source="recruitee",
                external_id=str(offer["id"]),
                company_name=company_name,
                title=offer.get("title", ""),
                url=offer.get("careers_url", ""),
                location=location or None,
                remote=bool(offer.get("remote")),
                description=description,
                posted_at=_parse_time(offer.get("published_at") or offer.get("created_at")),
            )
        )
    return postings
