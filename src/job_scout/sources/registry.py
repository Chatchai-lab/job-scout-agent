"""Maps an `ats` value (as stored in companies.ats) to its fetch function."""

from collections.abc import Callable

import httpx

from job_scout.models import JobPosting
from job_scout.sources import (
    ashby,
    bamboohr,
    greenhouse,
    lever,
    personio,
    recruitee,
    smartrecruiters,
    workable,
)

FetchFn = Callable[[httpx.Client, str, str], list[JobPosting]]

_REGISTRY: dict[str, FetchFn] = {
    "greenhouse": greenhouse.fetch,
    "greenhouse_eu": lambda c, n, s: greenhouse.fetch(c, n, s, ats="greenhouse_eu"),
    "lever": lever.fetch,
    "ashby": ashby.fetch,
    "personio": personio.fetch,
    "recruitee": recruitee.fetch,
    "smartrecruiters": smartrecruiters.fetch,
    "workable": workable.fetch,
    "bamboohr": bamboohr.fetch,
}


def fetch_for(ats: str, client: httpx.Client, company_name: str, slug: str) -> list[JobPosting]:
    fn = _REGISTRY.get(ats)
    if fn is None:
        raise ValueError(f"no fetcher registered for ats={ats!r}")
    return fn(client, company_name, slug)


def supported_ats() -> list[str]:
    return sorted(_REGISTRY)
