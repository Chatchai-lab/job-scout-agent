"""Ashby job board API.

Public, no auth. Unlisted jobs (`isListed: false`) are excluded.
"""

from datetime import datetime

import httpx

from job_scout.models import JobPosting

_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def fetch(client: httpx.Client, company_name: str, slug: str) -> list[JobPosting]:
    response = client.get(
        _URL.format(slug=slug), params={"includeCompensation": "false"}, timeout=20
    )
    response.raise_for_status()
    payload = response.json()

    postings = []
    for job in payload.get("jobs", []):
        if not job.get("isListed", True):
            continue
        posted_at = None
        if job.get("publishedAt"):
            posted_at = datetime.fromisoformat(job["publishedAt"].replace("Z", "+00:00"))
        postings.append(
            JobPosting(
                source="ashby",
                external_id=job["id"],
                company_name=company_name,
                title=job.get("title", ""),
                url=job.get("jobUrl", ""),
                location=job.get("location"),
                remote=bool(job.get("isRemote")),
                description=job.get("descriptionPlain") or job.get("descriptionHtml"),
                posted_at=posted_at,
            )
        )
    return postings
