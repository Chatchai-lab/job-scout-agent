"""In-memory stand-ins so the pipelines can be tested without network or database."""

from types import SimpleNamespace
from typing import Any

from job_scout.models import JobPosting
from job_scout.pricing import Usage
from job_scout.scoring import ScoreResult


class FakeRepo:
    def __init__(self, companies: list[dict[str, Any]] | None = None, spent: float = 0.0):
        self.companies = companies or []
        self.jobs: list[dict[str, Any]] = []
        self.scores: dict[str, dict[str, Any]] = {}
        self.drops: dict[str, str] = {}
        self.usage: list[dict[str, Any]] = []
        self.rules: list[str] = []
        self.polled: list[str] = []
        self.spent = spent

    def active_companies(self):
        return self.companies

    def mark_polled(self, company_id):
        self.polled.append(company_id)

    def known_jobs(self):
        return (
            {(j["source"], j["external_id"]) for j in self.jobs},
            {j["dedup_key"] for j in self.jobs},
        )

    def insert_jobs(self, rows):
        for r in rows:
            self.jobs.append({**r, "id": f"job-{len(self.jobs) + 1}"})

    def unscored_jobs(self):
        return [j for j in self.jobs if j["id"] not in self.scores and j["id"] not in self.drops]

    def insert_drops(self, rows):
        for r in rows:
            self.drops[r["job_id"]] = r["reason"]

    def save_score(self, row):
        self.scores[row["job_id"]] = {**row, "notified_at": None}

    def log_usage(self, row):
        self.usage.append(row)
        self.spent += row["cost_usd"]

    def month_cost_usd(self):
        return self.spent

    def approved_rules(self):
        return self.rules

    def unnotified(self):
        by_id = {j["id"]: j for j in self.jobs}
        return [
            {**s, "jobs": by_id[jid]} for jid, s in self.scores.items() if s["notified_at"] is None
        ]

    def mark_notified(self, job_ids):
        for jid in job_ids:
            self.scores[jid]["notified_at"] = "now"


class FakeNotifier:
    def __init__(self):
        self.sent: list[tuple[str, str | None]] = []

    def send(self, text, job_id=None):
        self.sent.append((text, job_id))


def posting(title="Forward Deployed Engineer", ext="1", location="Berlin, Germany", **kw):
    return JobPosting(
        source="greenhouse",
        external_id=ext,
        company_name=kw.pop("company_name", "Example AI"),
        title=title,
        url=f"https://example.com/{ext}",
        location=location,
        description=kw.pop("description", "Work with customers."),
        **kw,
    )


def score(fit=8, reach=8, ring="kern", **kw):
    return ScoreResult(fit=fit, reach=reach, ring=ring, reason="Passt gut.", **kw)


def usage(inp=1000, out=100, cache_read=0):
    return Usage(input_tokens=inp, output_tokens=out, cache_read_tokens=cache_read)


def llm_response(payload: dict[str, Any] | None, usage_obj: Any = None):
    block = (
        SimpleNamespace(type="tool_use", name="submit_score", input=payload)
        if payload is not None
        else SimpleNamespace(type="text", text="hi")
    )
    return SimpleNamespace(
        content=[block],
        usage=usage_obj
        or SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            cache_read_input_tokens=None,
            cache_creation_input_tokens=3,
        ),
    )
