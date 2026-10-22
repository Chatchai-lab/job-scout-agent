"""BambooHR careers feed: https://<slug>.bamboohr.com/careers/list (public JSON).

The list has no description, so each opening needs one detail call (boards are small).
"""

import httpx

from job_scout.models import JobPosting
from job_scout.sources.greenhouse import _strip_html

_LIST = "https://{slug}.bamboohr.com/careers/list"
_DETAIL = "https://{slug}.bamboohr.com/careers/{id}/detail"
_JOB_URL = "https://{slug}.bamboohr.com/careers/{id}"


def _description(client: httpx.Client, slug: str, job_id: str) -> str:
    try:
        response = client.get(
            _DETAIL.format(slug=slug, id=job_id), headers={"Accept": "application/json"},
            timeout=20,
        )
        response.raise_for_status()
        opening = response.json().get("result", {}).get("jobOpening", {})
        return _strip_html(opening.get("description", ""))
    except (httpx.HTTPError, ValueError):
        return ""  # a missing description still lets the title and location be scored


def fetch(client: httpx.Client, company_name: str, slug: str) -> list[JobPosting]:
    response = client.get(
        _LIST.format(slug=slug), headers={"Accept": "application/json"}, timeout=20
    )
    response.raise_for_status()
    postings = []
    for job in response.json().get("result", []):
        job_id = str(job["id"])
        place = job.get("atsLocation") or job.get("location") or {}
        location = ", ".join(p for p in (place.get("city"), place.get("country")) if p)
        postings.append(
            JobPosting(
                source="bamboohr",
                external_id=job_id,
                company_name=company_name,
                title=job.get("jobOpeningName", ""),
                url=_JOB_URL.format(slug=slug, id=job_id),
                location=location or None,
                remote=bool(job.get("isRemote")),
                description=_description(client, slug, job_id),
            )
        )
    return postings
