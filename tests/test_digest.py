from fakes import FakeNotifier, FakeRepo, posting, score

from job_scout.config import Settings
from job_scout.digest import run_digest, select_digest
from job_scout.triage import qualifies


def _row(fit, reach, ring="kern", start_ok=None):
    return {"job_id": f"{fit}{reach}{ring}", "fit": fit, "reach": reach, "ring": ring,
            "start_ok": start_ok}


def test_qualifies_applies_thresholds_ring_and_start():
    s = Settings()
    assert qualifies(_row(7, 6), s)
    assert not qualifies(_row(5, 9), s)
    assert not qualifies(_row(9, 5), s)
    assert not qualifies(_row(9, 9, ring="raus"), s)
    assert not qualifies(_row(9, 9, start_ok=False), s)


def test_digest_is_ranked_and_capped():
    s = Settings(digest_max_jobs=2)
    rows = [_row(6, 6), _row(9, 8), _row(8, 8), _row(3, 3)]
    chosen = select_digest(rows, s)
    assert [(r["fit"], r["reach"]) for r in chosen] == [(9, 8), (8, 8)]


def test_digest_marks_only_sent_jobs_and_keeps_overflow():
    repo = FakeRepo()
    for i in range(3):
        repo.insert_jobs([{**_job(i)}])
        repo.save_score({"job_id": f"job-{i + 1}", **score(fit=7 + i, reach=7).model_dump()})
    notifier = FakeNotifier()
    sent = run_digest(repo, Settings(digest_max_jobs=2), notifier)
    assert sent == 2
    assert repo.scores["job-1"]["notified_at"] is None  # lowest, left for tomorrow
    assert repo.scores["job-3"]["notified_at"] == "now"


def test_empty_digest_still_says_so():
    notifier = FakeNotifier()
    assert run_digest(FakeRepo(), Settings(), notifier) == 0
    assert "nichts" in notifier.sent[0][0]


def _job(i):
    p = posting(ext=str(i), title=f"Software Engineer {i}")
    return {
        "source": p.source, "external_id": p.external_id, "company_name": p.company_name,
        "title": p.title, "url": p.url, "location": p.location, "remote": False,
        "dedup_key": p.dedup_key,
    }


def test_digest_skips_jobs_the_current_prefilter_would_drop():
    s = Settings()
    ok = {**_row(8, 8), "jobs": {**_job(1), "location": "Munich, Germany"}}
    stale = {**_row(9, 9), "jobs": {**_job(2), "location": "Singapore", "remote": True}}
    assert select_digest([stale, ok], s) == [ok]
