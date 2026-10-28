"""In-memory stand-ins so the pipelines can be tested without network or database."""

from datetime import UTC, datetime
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
        self.profile_text: str | None = None
        self.assets: dict[tuple[str, str], bytes] = {}
        self.uploads: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.packages: dict[str, dict[str, Any]] = {}
        self.applications: list[dict[str, Any]] = []
        self.state: dict[str, str] = {}

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
        return [
            j for j in self.jobs
            if j["id"] not in self.scores and j["id"] not in self.drops and not j.get("closed_at")
        ]

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

    def private_profile(self):
        return self.profile_text

    def download_asset(self, bucket, name):
        return self.assets[(bucket, name)]

    def upload_asset(self, bucket, path, data, content_type):
        self.uploads[(bucket, path)] = (data, content_type)

    def save_package(self, job_id, *, cv_pdf_path, letter_pdf_path, cover_letter, gaps):
        self.packages[job_id] = {"cv_pdf_path": cv_pdf_path, "letter_pdf_path": letter_pdf_path,
                                 "cover_letter": cover_letter, "gaps": gaps}

    def mark_initiative(self, job_ids):
        for job in self.jobs:
            if job["id"] in job_ids:
                job["kind"] = "initiative"

    def package_job(self, job_id):
        return next((j for j in self.jobs if j["id"] == job_id), None)

    def get_state(self, key):
        return self.state.get(key)

    def job_presence(self):
        return [
            {"missing_runs": 0, "closed_at": None, "company_id": None, **j} for j in self.jobs
        ]

    def set_job_presence(self, job_ids, *, missing_runs, closed):
        for job in self.jobs:
            if job["id"] in job_ids:
                job["missing_runs"] = missing_runs
                job["closed_at"] = "now" if closed else None

    def mark_reminded(self, job_ids):
        for app in self.applications:
            if app.get("job_id") in job_ids:
                app["reminded_at"] = datetime.now(UTC).isoformat()

    def open_applications(self):
        return [a for a in self.applications if a["status"] in ("beworben", "interview")]

    def scored_job(self, job_id):
        by_id = {j["id"]: j for j in self.jobs}
        if job_id not in self.scores or job_id not in by_id:
            return None
        return {**self.scores[job_id], "jobs": by_id[job_id]}


class FakeNotifier:
    def __init__(self):
        self.sent: list[tuple[str, str | None]] = []
        self.reminders: list[tuple[str, str]] = []
        self.docs: list[tuple[str, str | None]] = []

    def send_document(self, path, caption=None):
        self.docs.append((path.name, caption))

    def send(self, text, job_id=None):
        self.sent.append((text, job_id))

    def send_reminder(self, text, job_id):
        self.reminders.append((text, job_id))


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


class ScriptedClient:
    """Stands in for the Anthropic client: returns queued tool inputs per forced tool."""

    def __init__(self, drafts: list[dict[str, Any]], checks: list[list[dict[str, str]]]):
        self.drafts = list(drafts)
        self.checks = list(checks)
        self.calls: list[tuple[str, str]] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        assert kwargs["tool_choice"] == {"type": "auto"}  # forced tool_choice 400s on Sonnet 5.5
        assert kwargs["tools"][0]["strict"] is True
        name = kwargs["tools"][0]["name"]
        self.calls.append((name, kwargs["messages"][0]["content"]))
        payload = self.drafts.pop(0) if name == "submit_package" else {"issues": self.checks.pop(0)}
        usage = SimpleNamespace(
            input_tokens=100, output_tokens=50, cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        return SimpleNamespace(
            content=[SimpleNamespace(type="thinking", thinking=""),
                     SimpleNamespace(type="tool_use", name=name, input=payload)],
            usage=usage, stop_reason="tool_use",
        )
