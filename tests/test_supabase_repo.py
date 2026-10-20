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
    def __init__(self, tables: dict[str, list[dict[str, Any]]]):
        self._tables = tables

    def table(self, name: str) -> _Query:
        return _Query(self._tables.get(name, []))


def test_unscored_jobs_excludes_scored_and_dropped():
    client = _Client(
        {
            "jobs": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "scores": [{"job_id": "a"}],
            "prefilter_drops": [{"job_id": "b"}],
        }
    )
    assert [j["id"] for j in SupabaseRepo(client).unscored_jobs()] == ["c"]
