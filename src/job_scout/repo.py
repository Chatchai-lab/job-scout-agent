"""All database access, behind one small interface so the pipelines are testable."""

import time
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx


class Repo(Protocol):
    def active_companies(self) -> list[dict[str, Any]]: ...
    def mark_polled(self, company_id: str) -> None: ...
    def known_jobs(self) -> tuple[set[tuple[str, str]], set[str]]:
        """(source, external_id) pairs and dedup_keys already stored."""
        ...
    def insert_jobs(self, rows: list[dict[str, Any]]) -> None: ...
    def unscored_jobs(self) -> list[dict[str, Any]]:
        """Recent jobs that have neither a score nor a prefilter drop."""
        ...
    def insert_drops(self, rows: list[dict[str, Any]]) -> None: ...
    def save_score(self, row: dict[str, Any]) -> None: ...
    def log_usage(self, row: dict[str, Any]) -> None: ...
    def month_cost_usd(self) -> float: ...
    def approved_rules(self) -> list[str]: ...
    def unnotified(self) -> list[dict[str, Any]]:
        """Score rows joined with their job, notified_at is null."""
        ...
    def mark_notified(self, job_ids: list[str]) -> None: ...


_PAGE = 1000
_RETRIES = 3  # extra attempts after a dropped connection (idle HTTP/2 links get closed)
_WRITE_BATCH = 100  # job rows carry full descriptions; one big upsert hits the statement timeout
_LOOKBACK_DAYS = 14


class SupabaseRepo:
    def __init__(self, client: Any):
        self.db = client

    def _run(self, query: Any) -> Any:
        """Execute a query, retrying transient network errors with a short backoff."""
        for attempt in range(_RETRIES + 1):
            try:
                return query.execute()
            except httpx.TransportError:
                if attempt == _RETRIES:
                    raise
                time.sleep(2**attempt)

    def _all(self, query_fn: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        start = 0
        while True:
            batch = self._run(query_fn().range(start, start + _PAGE - 1)).data
            rows.extend(batch)
            if len(batch) < _PAGE:
                return rows
            start += _PAGE

    def _ids(self, table: str) -> set[str]:
        return {r["job_id"] for r in self._all(lambda: self.db.table(table).select("job_id"))}

    def active_companies(self) -> list[dict[str, Any]]:
        return self._all(lambda: self.db.table("companies").select("*").eq("active", True))

    def mark_polled(self, company_id: str) -> None:
        query = self.db.table("companies").update({"last_polled_at": _now()}).eq("id", company_id)
        self._run(query)

    def known_jobs(self) -> tuple[set[tuple[str, str]], set[str]]:
        rows = self._all(lambda: self.db.table("jobs").select("source,external_id,dedup_key"))
        return (
            {(r["source"], r["external_id"]) for r in rows},
            {r["dedup_key"] for r in rows},
        )

    def insert_jobs(self, rows: list[dict[str, Any]]) -> None:
        for start in range(0, len(rows), _WRITE_BATCH):
            batch = rows[start : start + _WRITE_BATCH]
            self._run(self.db.table("jobs").upsert(batch, on_conflict="source,external_id"))

    def unscored_jobs(self) -> list[dict[str, Any]]:
        since = (datetime.now(UTC) - timedelta(days=_LOOKBACK_DAYS)).isoformat()
        jobs = self._all(
            lambda: self.db.table("jobs").select("*").gte("first_seen_at", since)
        )
        scored = self._ids("scores")
        dropped = self._ids("prefilter_drops")
        return [j for j in jobs if j["id"] not in scored and j["id"] not in dropped]

    def insert_drops(self, rows: list[dict[str, Any]]) -> None:
        for start in range(0, len(rows), _WRITE_BATCH):
            batch = rows[start : start + _WRITE_BATCH]
            self._run(self.db.table("prefilter_drops").upsert(batch, on_conflict="job_id"))

    def save_score(self, row: dict[str, Any]) -> None:
        self._run(self.db.table("scores").upsert(row, on_conflict="job_id"))

    def log_usage(self, row: dict[str, Any]) -> None:
        self._run(self.db.table("llm_usage").insert(row))

    def month_cost_usd(self) -> float:
        month = datetime.now(UTC).date().replace(day=1).isoformat()
        rows = self._run(self.db.table("monthly_cost").select("cost_usd").eq("month", month)).data
        return float(rows[0]["cost_usd"]) if rows else 0.0

    def approved_rules(self) -> list[str]:
        rows = (
            self._run(self.db.table("preferences").select("rule").eq("status", "freigegeben")).data
        )
        return [r["rule"] for r in rows]

    def unnotified(self) -> list[dict[str, Any]]:
        rows = self._all(
            lambda: self.db.table("scores").select("*, jobs(*)").is_("notified_at", "null")
        )
        return [r for r in rows if r.get("jobs")]

    def mark_notified(self, job_ids: list[str]) -> None:
        if job_ids:
            query = self.db.table("scores").update({"notified_at": _now()}).in_("job_id", job_ids)
            self._run(query)


def _now() -> str:
    return datetime.now(UTC).isoformat()
