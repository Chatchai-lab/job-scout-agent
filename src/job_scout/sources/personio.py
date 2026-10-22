"""Personio careers feed: https://<slug>.jobs.personio.de/xml (public XML, no auth)."""

import xml.etree.ElementTree as ET
from datetime import datetime

import httpx

from job_scout.models import JobPosting
from job_scout.sources.greenhouse import _strip_html

_FEED = "https://{slug}.jobs.personio.de/xml"
_JOB_URL = "https://{slug}.jobs.personio.de/job/{id}"


def _text(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _parse_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def fetch(client: httpx.Client, company_name: str, slug: str) -> list[JobPosting]:
    response = client.get(_FEED.format(slug=slug), params={"language": "de"}, timeout=20)
    response.raise_for_status()
    postings = []
    for position in ET.fromstring(response.content).findall("position"):
        job_id = _text(position, "id")
        sections = [
            _strip_html(_text(item, "value"))
            for item in position.findall("jobDescriptions/jobDescription")
        ]
        postings.append(
            JobPosting(
                source="personio",
                external_id=job_id,
                company_name=company_name,
                title=_text(position, "name"),
                url=_JOB_URL.format(slug=slug, id=job_id),
                location=_text(position, "office") or None,
                remote=False,
                description=" ".join(s for s in sections if s),
                posted_at=_parse_time(_text(position, "createdAt")),
            )
        )
    return postings
