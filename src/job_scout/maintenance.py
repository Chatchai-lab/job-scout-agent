"""Fixed, allow-listed data fixes that need DELETE rights. Run by the Maintenance workflow.

Each task is a named function with no free-form input, so the workflow can only do what is
listed here.
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from job_scout.prefilter import prefilter
from job_scout.repo import SupabaseRepo
from job_scout.triage import posting_from_row

_BATCH = 50
_DEV_TITLE = re.compile(
    r"developer|entwickl|software engineer|fullstack|full stack|backend|frontend|devops|engineer",
    re.IGNORECASE,
)
_LOOKBACK_DAYS = 14  # triage only picks up unscored jobs seen within this window


def rescore_candidates(
    scores: list[dict[str, Any]], jobs: list[dict[str, Any]], now: datetime | None = None
) -> list[str]:
    """Job ids of unseen, open developer postings whose score was low (fit 3 to 5)."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=_LOOKBACK_DAYS)
    by_id = {j["id"]: j for j in jobs}
    ids = []
    for score in scores:
        job = by_id.get(score["job_id"])
        if (
            job
            and score.get("notified_at") is None
            and 3 <= score["fit"] <= 5
            and not job.get("closed_at")
            and datetime.fromisoformat(job["first_seen_at"]) > cutoff
            and _DEV_TITLE.search(job["title"])
        ):
            ids.append(job["id"])
    return ids


def rescore_dev_jobs(repo: SupabaseRepo) -> int:
    """Delete low scores of developer postings so the next triage run scores them again."""
    db = repo.db
    scores = repo._all(
        lambda: db.table("scores").select("job_id,fit,notified_at").gte("fit", 3).lte("fit", 5),
        key="job_id",
    )
    jobs: list[dict[str, Any]] = []
    ids = [s["job_id"] for s in scores]
    for start in range(0, len(ids), _BATCH):
        batch = ids[start : start + _BATCH]
        query = db.table("jobs").select("id,title,closed_at,first_seen_at").in_("id", batch)
        jobs.extend(repo._run(query).data)
    targets = rescore_candidates(scores, jobs)
    for start in range(0, len(targets), _BATCH):
        batch = targets[start : start + _BATCH]
        repo._run(db.table("scores").delete().in_("job_id", batch))
    return len(targets)


def _reprocess(repo: SupabaseRepo, job_ids: list[str]) -> int:
    """Remove the prefilter drop and refresh first_seen_at so the next triage run re-checks them."""
    db = repo.db
    ids = list(dict.fromkeys(job_ids))
    for start in range(0, len(ids), _BATCH):
        batch = ids[start : start + _BATCH]
        repo._run(db.table("prefilter_drops").delete().in_("job_id", batch))
        now = datetime.now(UTC).isoformat()
        repo._run(db.table("jobs").update({"first_seen_at": now}).in_("id", batch))
    return len(ids)


def reprocess_working_students(repo: SupabaseRepo) -> int:
    """Working-student postings dropped before they were wanted."""
    db = repo.db
    jobs = repo._all(
        lambda: db.table("jobs")
        .select("id,title")
        .is_("closed_at", "null")
        .or_("title.ilike.%werkstudent%,title.ilike.%working student%,title.ilike.%studentische%"),
    )
    return _reprocess(repo, [j["id"] for j in jobs])


def reprocess_outside_germany(repo: SupabaseRepo) -> int:
    """Open postings dropped as 'outside_germany' that the fixed place check now accepts."""
    db = repo.db
    drops = repo._all(
        lambda: db.table("prefilter_drops").select("job_id").eq("reason", "outside_germany"),
        key="job_id",
    )
    ids = [d["job_id"] for d in drops]
    keep: list[str] = []
    for start in range(0, len(ids), _BATCH):
        batch = ids[start : start + _BATCH]
        query = db.table("jobs").select("*").in_("id", batch).is_("closed_at", "null")
        for row in repo._run(query).data:
            posting = posting_from_row(row)
            if prefilter(posting) != "outside_germany":
                keep.append(row["id"])
    return _reprocess(repo, keep)


TASKS = {
    "rescore-dev-jobs": rescore_dev_jobs,
    "reprocess-working-students": reprocess_working_students,
    "reprocess-outside-germany": reprocess_outside_germany,
}
