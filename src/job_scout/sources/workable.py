"""Workable widget API: https://apply.workable.com/api/v1/widget/accounts/<slug> (public)."""

from datetime import datetime

import httpx

from job_scout.models import JobPosting
from job_scout.sources.greenhouse import _strip_html

_URL = "https://apply.workable.com/api/v1/widget/accounts/{slug}"


def _parse_time(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def fetch(client: httpx.Client, company_name: str, slug: str) -> list[JobPosting]:
    response = client.get(_URL.format(slug=slug), params={"details": "true"}, timeout=20)
    response.raise_for_status()
    postings = []
    for job in response.json().get("jobs", []):
        location = ", ".join(p for p in (job.get("city"), job.get("country")) if p)
        postings.append(
            JobPosting(
                source="workable",
                external_id=str(job.get("shortcode") or job.get("id")),
                company_name=company_name,
                title=job.get("title", ""),
                url=job.get("url") or job.get("shortlink") or "",
                location=location or None,
                remote=bool(job.get("telecommuting")),
                description=_strip_html(job.get("description", "")),
                posted_at=_parse_time(job.get("published_on") or job.get("created_at")),
            )
        )
    return postings
