"""Fixed, allow-listed data fixes that need DELETE rights. Run by the Maintenance workflow.

Each task is a named function with no free-form input, so the workflow can only do what is
listed here.
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from job_scout.repo import SupabaseRepo

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


TASKS = {"rescore-dev-jobs": rescore_dev_jobs}
