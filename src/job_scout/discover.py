"""Find the public job board of candidate companies.

For every candidate name, likely board slugs are tried against each supported ATS vendor.
The first board with open postings wins and the company is added to `companies`.
Candidates live in Supabase (`company_candidates`), never in the repository.
"""

import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from job_scout.models import JobPosting, normalize_company
from job_scout.sources import fetch_for

# Most common vendors for German tech companies first.
ATS_ORDER = [
    "greenhouse", "greenhouse_eu", "ashby", "lever", "personio", "recruitee", "smartrecruiters",
    "workable", "bamboohr",
]
_SR_LIST = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"


@dataclass
class Match:
    ats: str
    slug: str
    open_jobs: int
    sample_titles: list[str]


class CandidateStore(Protocol):
    def pending(self) -> list[str]: ...
    def save_found(self, name: str, match: Match) -> None: ...
    def save_not_found(self, name: str) -> None: ...


def slug_variants(name: str) -> list[str]:
    """'Aleph Alpha GmbH' -> ['alephalpha', 'aleph-alpha']."""
    words = normalize_company(name).split("-")
    variants = ["".join(words)]
    if len(words) > 1:
        variants.append("-".join(words))
    return [v for v in variants if v]


def _probe(client: httpx.Client, ats: str, slug: str, name: str) -> Match | None:
    try:
        if ats == "smartrecruiters":
            response = client.get(
                _SR_LIST.format(slug=slug), params={"limit": 5, "country": "de"}, timeout=10
            )
            response.raise_for_status()
            titles = [p.get("name", "") for p in response.json().get("content", [])]
            total = int(response.json().get("totalFound", len(titles)))
        else:
            postings: list[JobPosting] = fetch_for(ats, client, name, slug)
            titles = [p.title for p in postings[:5]]
            total = len(postings)
    except (httpx.HTTPError, ET.ParseError, ValueError, KeyError):
        return None
    return Match(ats, slug, total, titles[:3]) if total > 0 else None


def find_board(client: httpx.Client, name: str) -> Match | None:
    for slug in slug_variants(name):
        for ats in ATS_ORDER:
            match = _probe(client, ats, slug, name)
            if match:
                return match
    return None


def run_discover(client: httpx.Client, store: CandidateStore, workers: int = 8) -> tuple[int, int]:
    """Probe all pending candidates. Returns (found, not_found)."""
    names = store.pending()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        matches = list(pool.map(lambda n: find_board(client, n), names))
    found = 0
    for name, match in zip(names, matches, strict=True):
        if match:
            store.save_found(name, match)
            found += 1
        else:
            store.save_not_found(name)
    return found, len(names) - found


class SupabaseCandidateStore:
    def __init__(self, db: Any):
        self.db = db

    def pending(self) -> list[str]:
        rows = self.db.table("company_candidates").select("name").eq("status", "pending").execute()
        return [r["name"] for r in rows.data]

    def save_found(self, name: str, match: Match) -> None:
        self.db.table("companies").upsert(
            {"name": name, "ats": match.ats, "ats_slug": match.slug, "source": "discover"},
            on_conflict="ats,ats_slug",
        ).execute()
        self._mark(name, "found", match)

    def save_not_found(self, name: str) -> None:
        self._mark(name, "not_found", None)

    def _mark(self, name: str, status: str, match: Match | None) -> None:
        self.db.table("company_candidates").update(
            {
                "status": status,
                "ats": match.ats if match else None,
                "ats_slug": match.slug if match else None,
                "open_jobs": match.open_jobs if match else None,
                "sample_titles": match.sample_titles if match else None,
                "checked_at": datetime.now(UTC).isoformat(),
            }
        ).eq("name", name).execute()
