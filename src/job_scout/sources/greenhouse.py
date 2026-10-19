"""Greenhouse job board API.

Public, no auth. Most US-based AI companies (Anthropic, Databricks, Celonis)
use the global endpoint; some EU-first companies (Parloa) use the EU one.
"""

import re
from datetime import datetime

import httpx

from job_scout.models import JobPosting

_TAG_RE = re.compile(r"<[^>]+>")

_BASE_URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "greenhouse_eu": "https://boards-api.eu.greenhouse.io/v1/boards/{slug}/jobs",
}


def _strip_html(html: str) -> str:
    return _TAG_RE.sub(" ", html or "").strip()


def fetch(
    client: httpx.Client, company_name: str, slug: str, *, ats: str = "greenhouse"
) -> list[JobPosting]:
    url = _BASE_URLS[ats].format(slug=slug)
    response = client.get(url, params={"content": "true"}, timeout=20)
    response.raise_for_status()
    payload = response.json()

    postings = []
    for job in payload.get("jobs", []):
        location = (job.get("location") or {}).get("name")
        posted_at = None
        if job.get("updated_at"):
            posted_at = datetime.fromisoformat(job["updated_at"])
        postings.append(
            JobPosting(
                source=ats,
                external_id=str(job["id"]),
                company_name=company_name,
                title=job["title"],
                url=job.get("absolute_url", ""),
                location=location,
                remote="remote" in (location or "").lower(),
                description=_strip_html(job.get("content", "")),
                posted_at=posted_at,
            )
        )
    return postings
