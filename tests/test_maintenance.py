from datetime import UTC, datetime

from job_scout.maintenance import TASKS, rescore_candidates

NOW = datetime(2026, 10, 22, tzinfo=UTC)


def _job(job_id, title="Backend Engineer", seen="2026-10-20T00:00:00+00:00", closed=None):
    return {"id": job_id, "title": title, "first_seen_at": seen, "closed_at": closed}


def _score(job_id, fit=4, notified=None):
    return {"job_id": job_id, "fit": fit, "notified_at": notified}


def test_only_unseen_open_recent_dev_jobs_with_low_fit_are_reset():
    jobs = [
        _job("a"),
        _job("b", title="Account Manager"),
        _job("c", closed="2026-10-21T00:00:00+00:00"),
        _job("d", seen="2026-09-01T00:00:00+00:00"),
        _job("e"),
        _job("f"),
    ]
    scores = [
        _score("a"), _score("b"), _score("c"), _score("d"),
        _score("e", notified="2026-10-21T00:00:00+00:00"),
        _score("f", fit=7),
    ]
    assert rescore_candidates(scores, jobs, NOW) == ["a"]


def test_task_list_is_fixed():
    assert set(TASKS) == {"rescore-dev-jobs"}
