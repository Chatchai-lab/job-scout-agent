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
    assert qualifies(_row(5, 9), s)  # fit 5 is the lower edge
    assert not qualifies(_row(4, 9), s)
    assert qualifies(_row(8, 5), s)  # reach 5 = stretch, still ok
    assert qualifies(_row(9, 4), s)  # reach 4 is the lower edge
    assert not qualifies(_row(9, 3), s)
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


def test_open_applications_line_counts_and_dates():
    from datetime import UTC, datetime

    from job_scout.digest import open_applications_line

    now = datetime(2026, 11, 20, 10, tzinfo=UTC)
    apps = [
        {"applied_at": "2026-11-08T10:00:00+00:00", "updated_at": "2026-11-08T10:00:00+00:00"},
        {"applied_at": None, "updated_at": "2026-11-18T10:00:00+00:00"},
    ]
    assert open_applications_line(apps, now) == "📨 2 offene Bewerbungen, älteste seit 12 Tagen"
    assert open_applications_line(apps[:1], now).startswith("📨 1 offene Bewerbung,")
    assert open_applications_line([], now) is None


def test_digest_mentions_open_applications():
    repo = FakeRepo()
    repo.applications = [
        {"status": "beworben", "applied_at": "2026-01-01T00:00:00+00:00",
         "updated_at": "2026-01-01T00:00:00+00:00"},
        {"status": "gemerkt", "applied_at": None, "updated_at": "2026-01-01T00:00:00+00:00"},
    ]
    notifier = FakeNotifier()
    run_digest(repo, Settings(), notifier)
    assert "📨 1 offene Bewerbung," in notifier.sent[0][0]


def _app(job_id, applied, reminded=None, status="beworben"):
    return {"job_id": job_id, "status": status, "applied_at": applied, "reminded_at": reminded,
            "updated_at": applied, "jobs": {"company_name": "Example AI", "title": "FDE"}}


def test_due_reminders_after_14_days_without_recent_reminder():
    from datetime import UTC, datetime

    from job_scout.digest import due_reminders

    now = datetime(2026, 11, 30, tzinfo=UTC)
    apps = [
        _app("a", "2026-11-10T00:00:00+00:00"),  # 20 days: due
        _app("b", "2026-11-20T00:00:00+00:00"),  # 10 days: too early
        _app("c", "2026-11-01T00:00:00+00:00", reminded="2026-11-25T00:00:00+00:00"),  # recent
        _app("d", "2026-10-01T00:00:00+00:00", reminded="2026-11-05T00:00:00+00:00"),  # again
        _app("e", "2026-10-01T00:00:00+00:00", status="interview"),  # not waiting
    ]
    assert [a["job_id"] for a in due_reminders(apps, 14, now)] == ["a", "d"]


def test_digest_sends_reminder_once_and_marks_it():
    repo = FakeRepo()
    repo.applications = [_app("job-x", "2020-01-01T00:00:00+00:00")]
    notifier = FakeNotifier()
    run_digest(repo, Settings(), notifier)
    run_digest(repo, Settings(), notifier)
    assert len(notifier.reminders) == 1
    assert "Nachfassen" in notifier.reminders[0][0]
    assert notifier.reminders[0][1] == "job-x"


def test_digest_skips_closed_jobs():
    repo = FakeRepo()
    repo.insert_jobs([_job(1)])
    repo.save_score({"job_id": "job-1", **score().model_dump()})
    repo.jobs[0]["closed_at"] = "2026-10-20T00:00:00+00:00"
    notifier = FakeNotifier()
    assert run_digest(repo, Settings(), notifier) == 0


def _repo_with_one_job():
    repo = FakeRepo()
    repo.insert_jobs([_job(1)])
    repo.save_score({"job_id": "job-1", **score().model_dump()})
    return repo


def test_paused_digest_sends_and_marks_nothing():
    repo = _repo_with_one_job()
    repo.state["notifications_paused"] = "true"
    notifier = FakeNotifier()
    assert run_digest(repo, Settings(), notifier) == 0
    assert notifier.sent == [] and repo.scores["job-1"]["notified_at"] is None


def test_paused_digest_still_sends_when_forced_for_testing():
    repo = _repo_with_one_job()
    repo.state["notifications_paused"] = "true"
    notifier = FakeNotifier()
    assert run_digest(repo, Settings(), notifier, ignore_pause=True) == 1


def test_working_student_jobs_qualify_with_a_lower_fit():
    s = Settings()
    row = _row(3, 9)
    assert not qualifies(row, s)
    assert qualifies({**row, "jobs": {"kind": "working_student"}}, s)
    assert not qualifies({**_row(2, 9), "jobs": {"kind": "working_student"}}, s)
