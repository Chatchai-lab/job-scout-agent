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
    def private_profile(self) -> str | None:
        """Full master profile YAML (with contact data) from profile_private."""
        ...
    def download_asset(self, bucket: str, name: str) -> bytes: ...
    def upload_asset(self, bucket: str, path: str, data: bytes, content_type: str) -> None: ...
    def save_package(
        self,
        job_id: str,
        *,
        cv_pdf_path: str,
        letter_pdf_path: str,
        cover_letter: str,
        gaps: list[dict[str, str]],
    ) -> None: ...
    def scored_job(self, job_id: str) -> dict[str, Any] | None:
        """One score row joined with its job (same shape as unnotified), or None."""
        ...
    def open_applications(self) -> list[dict[str, Any]]:
        """Applications still waiting for an answer (status beworben or interview)."""
        ...
    def get_state(self, key: str) -> str | None:
        """Value of an app_state switch, or None if it is not set."""
        ...
    def set_state(self, key: str, value: str) -> None:
        """Create or change an app_state value."""
        ...
    def mark_kind(self, job_ids: list[str], kind: str) -> None:
        """Set jobs.kind (initiative or working_student) for these postings."""
        ...
    def package_job(self, job_id: str) -> dict[str, Any] | None:
        """One job row by id (scored or not), or None."""
        ...
    def update_job(self, job_id: str, fields: dict[str, Any]) -> None:
        """Set columns on one job row."""
        ...
    def delete_job(self, job_id: str) -> None:
        """Remove one job row (and what hangs on it)."""
        ...
    def job_presence(self) -> list[dict[str, Any]]:
        """id, company_id, source, external_id, missing_runs, closed_at of every stored job."""
        ...
    def set_job_presence(
        self, job_ids: list[str], *, missing_runs: int, closed: bool
    ) -> None: ...
    def mark_reminded(self, job_ids: list[str]) -> None: ...


NOTIFICATIONS_PAUSED = "notifications_paused"
LAST_DIGEST_ON = "last_digest_on"

_PAGE = 1000
_RETRIES = 3  # extra attempts after a dropped connection (idle HTTP/2 links get closed)
_WRITE_BATCH = 100  # job rows carry full descriptions; one big upsert hits the statement timeout
_LOOKBACK_DAYS = 14


class SupabaseRepo:
    def __init__(self, client: Any):
        self.db = client

    def _retry(self, call: Any) -> Any:
        """Run a call, retrying transient network errors with a short backoff."""
        for attempt in range(_RETRIES + 1):
            try:
                return call()
            except httpx.TransportError:
                if attempt == _RETRIES:
                    raise
                time.sleep(2**attempt)

    def _run(self, query: Any) -> Any:
        return self._retry(query.execute)

    def _all(self, query_fn: Any, key: str = "id") -> list[dict[str, Any]]:
        """Read every row with keyset paging: stable under ties and server-side row caps."""
        rows: list[dict[str, Any]] = []
        last = None
        while True:
            query = query_fn()
            if last is not None:
                query = query.gt(key, last)
            batch = self._run(query.order(key).limit(_PAGE)).data
            rows.extend(batch)
            if len(batch) < _PAGE:
                return rows
            last = batch[-1][key]

    def _ids(self, table: str) -> set[str]:
        rows = self._all(lambda: self.db.table(table).select("job_id"), key="job_id")
        return {r["job_id"] for r in rows}

    def active_companies(self) -> list[dict[str, Any]]:
        return self._all(lambda: self.db.table("companies").select("*").eq("active", True))

    def mark_polled(self, company_id: str) -> None:
        query = self.db.table("companies").update({"last_polled_at": _now()}).eq("id", company_id)
        self._run(query)

    def known_jobs(self) -> tuple[set[tuple[str, str]], set[str]]:
        rows = self._all(lambda: self.db.table("jobs").select("id,source,external_id,dedup_key"))
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
            lambda: self.db.table("jobs")
            .select("*")
            .gte("first_seen_at", since)
            .is_("closed_at", "null")
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
            lambda: self.db.table("scores").select("*, jobs(*)").is_("notified_at", "null"),
            key="job_id",
        )
        return [r for r in rows if r.get("jobs")]

    def private_profile(self) -> str | None:
        rows = self._run(self.db.table("profile_private").select("yaml").eq("id", "main")).data
        return rows[0]["yaml"] if rows else None

    def download_asset(self, bucket: str, name: str) -> bytes:
        return self._retry(lambda: self.db.storage.from_(bucket).download(name))

    def upload_asset(self, bucket: str, path: str, data: bytes, content_type: str) -> None:
        options = {"content-type": content_type, "upsert": "true"}
        self._retry(lambda: self.db.storage.from_(bucket).upload(path, data, options))

    def save_package(
        self,
        job_id: str,
        *,
        cv_pdf_path: str,
        letter_pdf_path: str,
        cover_letter: str,
        gaps: list[dict[str, str]],
    ) -> None:
        current = self._run(
            self.db.table("applications").select("status").eq("job_id", job_id).limit(1)
        ).data
        status = current[0]["status"] if current else None
        keep = status not in (None, "gemerkt", "paket")  # never move an application backwards
        row = {
            "job_id": job_id,
            "status": status if keep else "paket",
            "cv_pdf_path": cv_pdf_path,
            "letter_pdf_path": letter_pdf_path,
            "cover_letter": cover_letter,
            "gaps": gaps,
            "updated_at": _now(),
        }
        self._run(self.db.table("applications").upsert(row, on_conflict="job_id"))

    def scored_job(self, job_id: str) -> dict[str, Any] | None:
        rows = self._run(
            self.db.table("scores").select("*, jobs(*)").eq("job_id", job_id).limit(1)
        ).data
        return rows[0] if rows and rows[0].get("jobs") else None

    def mark_kind(self, job_ids: list[str], kind: str) -> None:
        for start in range(0, len(job_ids), _WRITE_BATCH):
            batch = job_ids[start : start + _WRITE_BATCH]
            self._run(self.db.table("jobs").update({"kind": kind}).in_("id", batch))

    def package_job(self, job_id: str) -> dict[str, Any] | None:
        rows = self._run(self.db.table("jobs").select("*").eq("id", job_id).limit(1)).data
        return rows[0] if rows else None

    def update_job(self, job_id: str, fields: dict[str, Any]) -> None:
        self._run(self.db.table("jobs").update(fields).eq("id", job_id))

    def delete_job(self, job_id: str) -> None:
        self._run(self.db.table("jobs").delete().eq("id", job_id))

    def get_state(self, key: str) -> str | None:
        rows = self._run(self.db.table("app_state").select("value").eq("key", key)).data
        return rows[0]["value"] if rows else None

    def set_state(self, key: str, value: str) -> None:
        row = {"key": key, "value": value, "updated_at": _now()}
        self._run(self.db.table("app_state").upsert(row, on_conflict="key"))

    def job_presence(self) -> list[dict[str, Any]]:
        columns = "id,company_id,source,external_id,missing_runs,closed_at"
        return self._all(lambda: self.db.table("jobs").select(columns))

    def set_job_presence(self, job_ids: list[str], *, missing_runs: int, closed: bool) -> None:
        values = {"missing_runs": missing_runs, "closed_at": _now() if closed else None}
        for start in range(0, len(job_ids), _WRITE_BATCH):
            batch = job_ids[start : start + _WRITE_BATCH]
            self._run(self.db.table("jobs").update(values).in_("id", batch))

    def open_applications(self) -> list[dict[str, Any]]:
        query = (
            self.db.table("applications")
            .select("job_id,status,applied_at,updated_at,reminded_at,jobs(company_name,title)")
            .in_("status", ["beworben", "interview"])
        )
        return self._run(query).data

    def mark_reminded(self, job_ids: list[str]) -> None:
        if job_ids:
            query = self.db.table("applications").update({"reminded_at": _now()})
            self._run(query.in_("job_id", job_ids))

    def mark_notified(self, job_ids: list[str]) -> None:
        if job_ids:
            query = self.db.table("scores").update({"notified_at": _now()}).in_("job_id", job_ids)
            self._run(query)


def _now() -> str:
    return datetime.now(UTC).isoformat()
