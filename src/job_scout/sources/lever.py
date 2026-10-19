"""Lever job board API.

Public, no auth. An empty company (e.g. unused slug, or a company that
removed its public board) returns `[]`, not an error.
"""

from datetime import UTC, datetime

import httpx

from job_scout.models import JobPosting

_BASE_URL = "https://api.lever.co/v0/postings/{slug}"


def fetch(client: httpx.Client, company_name: str, slug: str) -> list[JobPosting]:
    response = client.get(_BASE_URL.format(slug=slug), params={"mode": "json"}, timeout=20)
    response.raise_for_status()
    postings = []
    for job in response.json():
        categories = job.get("categories", {})
        posted_at = None
        if job.get("createdAt"):
            posted_at = datetime.fromtimestamp(job["createdAt"] / 1000, tz=UTC)
        postings.append(
            JobPosting(
                source="lever",
                external_id=job["id"],
                company_name=company_name,
                title=job.get("text", ""),
                url=job.get("hostedUrl", ""),
                location=categories.get("location"),
                remote=categories.get("workplaceType") == "remote",
                description=job.get("descriptionPlain") or job.get("description"),
                posted_at=posted_at,
            )
        )
    return postings
