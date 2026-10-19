"""Common interface for all job sources."""

from typing import Protocol

import httpx

from job_scout.models import JobPosting


class Source(Protocol):
    name: str

    def fetch(self, client: httpx.Client, company_name: str, slug: str) -> list[JobPosting]:
        """Return all open postings for one company board."""
        ...
