"""SupabaseRepo against a minimal fake client (query-builder chain, no network)."""

from typing import Any

import httpx
import pytest

from job_scout.repo import SupabaseRepo


class _Query:
    """Just enough of the postgrest query builder: gt, order, limit, range."""

    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def select(self, *_a: Any, **_k: Any) -> "_Query":
        return self

    def gte(self, *_a: Any, **_k: Any) -> "_Query":
        return self

    def eq(self, column: str, value: Any) -> "_Query":
        return _Query([r for r in self._rows if r.get(column) == value])

    def gt(self, column: str, value: Any) -> "_Query":
        return _Query([r for r in self._rows if r[column] > value])

    def order(self, column: str) -> "_Query":
        return _Query(sorted(self._rows, key=lambda r: r[column]))

    def limit(self, n: int) -> "_Query":
        return _Query(self._rows[:n])

    def execute(self) -> Any:
        return type("R", (), {"data": self._rows})()


class _Client:
    def __init__(self, tables: dict[str, list[dict[str, Any]]] | None = None):
        self._tables = tables or {}
        self.upserts: list[tuple[str, int]] = []
        self.payloads: list[tuple[str, Any]] = []

    def table(self, name: str) -> _Query:
        query = _Query(self._tables.get(name, []))
        query.upsert = lambda rows, **_k: self._record(name, rows)  # type: ignore[attr-defined]
        return query

    def _record(self, name: str, rows: list[dict[str, Any]]) -> "_Query":
        self.upserts.append((name, len(rows)))
        self.payloads.append((name, rows))
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


class _Flaky:
    def __init__(self, failures: int):
        self.failures = failures
        self.calls = 0

    def execute(self) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            raise httpx.RemoteProtocolError("Server disconnected")
        return "ok"


def test_transient_network_errors_are_retried(monkeypatch):
    monkeypatch.setattr("job_scout.repo.time.sleep", lambda _s: None)
    query = _Flaky(failures=2)
    assert SupabaseRepo(_Client())._run(query) == "ok"
    assert query.calls == 3


def test_persistent_network_errors_are_raised(monkeypatch):
    monkeypatch.setattr("job_scout.repo.time.sleep", lambda _s: None)
    with pytest.raises(httpx.RemoteProtocolError):
        SupabaseRepo(_Client())._run(_Flaky(failures=99))


def test_all_rows_are_read_across_pages():
    rows = [{"id": f"{i:05d}"} for i in range(2500)]
    client = _Client({"jobs": rows})
    assert len(SupabaseRepo(client)._all(lambda: client.table("jobs"))) == 2500


def test_private_profile_returns_the_yaml_text():
    client = _Client({"profile_private": [{"id": "main", "yaml": "person: {}"}]})
    assert SupabaseRepo(client).private_profile() == "person: {}"
    assert SupabaseRepo(_Client()).private_profile() is None


def test_save_package_sets_status_paket_but_never_moves_back():
    new = _Client({"applications": [{"job_id": "j1", "status": "gemerkt"}]})
    SupabaseRepo(new).save_package(
        "j1", cv_pdf_path="p.pdf", letter_pdf_path="l.pdf", cover_letter="x", gaps=[]
    )
    assert new.payloads[-1][1]["status"] == "paket"
    assert new.payloads[-1][1]["letter_pdf_path"] == "l.pdf"

    advanced = _Client({"applications": [{"job_id": "j2", "status": "beworben"}]})
    SupabaseRepo(advanced).save_package(
        "j2", cv_pdf_path="p.pdf", letter_pdf_path="l.pdf", cover_letter="x", gaps=[]
    )
    assert advanced.payloads[-1][1]["status"] == "beworben"
