"""SupabaseRepo against a minimal fake client (query-builder chain, no network)."""

from typing import Any

from job_scout.repo import SupabaseRepo


class _Query:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def select(self, *_a: Any, **_k: Any) -> "_Query":
        return self

    def gte(self, *_a: Any, **_k: Any) -> "_Query":
        return self

    def range(self, start: int, end: int) -> "_Query":
        return _Query(self._rows[start : end + 1])

    def execute(self) -> Any:
        return type("R", (), {"data": self._rows})()


class _Client:
    def __init__(self, tables: dict[str, list[dict[str, Any]]] | None = None):
        self._tables = tables or {}
        self.upserts: list[tuple[str, int]] = []

    def table(self, name: str) -> _Query:
        query = _Query(self._tables.get(name, []))
        query.upsert = lambda rows, **_k: self._record(name, rows)  # type: ignore[attr-defined]
        return query

    def _record(self, name: str, rows: list[dict[str, Any]]) -> "_Query":
        self.upserts.append((name, len(rows)))
        return _Query([])


def test_unscored_jobs_excludes_scored_and_dropped():
    client = _Client(
        {
            "jobs": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "scores": [{"job_id": "a"}],
            "prefilter_drops": [{"job_id": "b"}],
        }
    )
    assert [j["id"] for j in SupabaseRepo(client).unscored_jobs()] == ["c"]


def test_insert_jobs_is_batched():
    client = _Client()
    repo = SupabaseRepo(client)
    repo.insert_jobs([{"id": str(i)} for i in range(250)])
    repo.insert_jobs([])
    assert client.upserts == [("jobs", 100), ("jobs", 100), ("jobs", 50)]
