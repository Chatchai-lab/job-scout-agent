from fakes import FakeNotifier, FakeRepo, posting, score

from job_scout.config import Settings
from job_scout.digest import resend_job, run_digest, select_digest
from job_scout.triage import is_instant, qualifies


def _row(fit, reach, ring="kern", start_ok=None):
    return {"job_id": f"{fit}{reach}{ring}", "fit": fit, "reach": reach, "ring": ring,
            "start_ok": start_ok}


def test_qualifies_applies_thresholds_ring_and_start():
    s = Settings()
    assert qualifies(_row(7, 6), s)
    assert not qualifies(_row(5, 9), s)
    assert qualifies(_row(8, 5), s)  # reach 5 = stretch, still ok
    assert not qualifies(_row(9, 4), s)
    assert not qualifies(_row(9, 9, ring="raus"), s)
    assert not qualifies(_row(9, 9, start_ok=False), s)


def test_instant_push_needs_high_fit_and_reach_6():
    s = Settings()
    assert is_instant(_row(9, 6), s)
    assert not is_instant(_row(9, 5), s)  # stretch goes to the digest, not a push
    assert not is_instant(_row(8, 9), s)


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


def test_resend_sends_the_job_again_with_buttons_and_marker():
    repo = FakeRepo()
    repo.insert_jobs([{**_job(1)}])
    repo.save_score({"job_id": "job-1", **score(fit=8, reach=7).model_dump()})
    repo.mark_notified(["job-1"])
    notifier = FakeNotifier()
    assert resend_job(repo, notifier, "job-1") is True
    text, job_id = notifier.sent[0]
    assert text.startswith("🔁") and "Software Engineer 1" in text and job_id == "job-1"


def test_resend_unknown_job_sends_nothing():
    notifier = FakeNotifier()
    assert resend_job(FakeRepo(), notifier, "nope") is False
    assert notifier.sent == []
