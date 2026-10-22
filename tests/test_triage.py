import httpx
from fakes import FakeNotifier, FakeRepo, posting, score, usage

from job_scout.config import Settings
from job_scout.triage import run_triage

COMPANY = {"id": "c1", "name": "Example AI", "ats": "greenhouse", "ats_slug": "exampleai"}


def _run(repo, postings, score_fn=None, notifier=None, settings=None, fetch=None):
    settings = settings or Settings()
    return run_triage(
        repo,
        settings,
        fetch=fetch or (lambda ats, client, name, slug: postings),
        score_fn=score_fn or (lambda system, job: (score(), usage())),
        profile_text="person: test",
        notifier=notifier,
        client=httpx.Client(),
    )


def test_new_job_is_scored_and_stored():
    repo = FakeRepo([COMPANY])
    stats = _run(repo, [posting()])
    assert stats.new_jobs == 1 and stats.scored == 1
    assert len(repo.scores) == 1
    assert repo.usage[0]["purpose"] == "match"
    assert repo.polled == ["c1"]


def test_second_run_does_not_rescore_known_jobs():
    repo = FakeRepo([COMPANY])
    _run(repo, [posting()])
    stats = _run(repo, [posting()])
    assert stats.new_jobs == 0 and stats.scored == 0


def test_same_job_from_two_ids_is_deduplicated_by_key():
    repo = FakeRepo([COMPANY])
    stats = _run(repo, [posting(ext="1"), posting(ext="2")])
    assert stats.new_jobs == 1


def test_prefiltered_job_is_dropped_without_llm_call():
    repo = FakeRepo([COMPANY])
    calls = []

    def score_fn(system, job):
        calls.append(job)
        return score(), usage()

    stats = _run(repo, [posting(title="Senior Forward Deployed Engineer")], score_fn)
    assert stats.dropped == 1 and not calls
    assert list(repo.drops.values()) == ["senior_title"]


def test_failing_company_does_not_stop_the_run():
    repo = FakeRepo([{**COMPANY, "id": "bad", "name": "Bad"}, COMPANY])

    def fetch(ats, client, name, slug):
        if name == "Bad":
            raise httpx.ConnectError("boom")
        return [posting()]

    stats = _run(repo, [], fetch=fetch)
    assert stats.companies_failed == 1 and stats.scored == 1


def test_companies_without_board_are_skipped():
    repo = FakeRepo([{"id": "c2", "name": "X", "ats": "none", "ats_slug": None}])
    stats = _run(repo, [posting()])
    assert stats.companies_polled == 0 and stats.new_jobs == 0


def test_scoring_error_leaves_job_for_retry():
    repo = FakeRepo([COMPANY])

    def boom(system, job):
        raise ValueError("no tool call")

    stats = _run(repo, [posting()], boom)
    assert stats.score_errors == 1 and not repo.scores
    assert len(repo.unscored_jobs()) == 1


def test_budget_exhausted_pauses_scoring_and_warns():
    repo = FakeRepo([COMPANY], spent=100.0)
    notifier = FakeNotifier()
    stats = _run(repo, [posting()], notifier=notifier)
    assert stats.budget_stopped and not repo.scores
    assert any("Budget" in text or "budget" in text for text, _ in notifier.sent)


def test_top_hit_is_pushed_instantly_and_marked_notified():
    repo = FakeRepo([COMPANY])
    notifier = FakeNotifier()
    stats = _run(repo, [posting()], lambda s, j: (score(fit=9, reach=8), usage()), notifier)
    assert stats.instant_pushed == 1
    assert notifier.sent[0][1] == "job-1"
    assert repo.scores["job-1"]["notified_at"] == "now"


def test_normal_hit_waits_for_digest():
    repo = FakeRepo([COMPANY])
    notifier = FakeNotifier()
    _run(repo, [posting()], lambda s, j: (score(fit=7, reach=7), usage()), notifier)
    assert notifier.sent == []
    assert repo.scores["job-1"]["notified_at"] is None


def test_approved_rules_reach_the_system_prompt():
    repo = FakeRepo([COMPANY])
    repo.rules = ["Keine Rollen mit Außendienst-Vertrieb"]
    seen = []

    def score_fn(system, job):
        seen.append(system)
        return score(), usage()

    _run(repo, [posting()], score_fn)
    assert "Keine Rollen mit Außendienst-Vertrieb" in seen[0]
    assert "person: test" in seen[0]


def _closed(repo):
    return {j["external_id"]: j.get("closed_at") for j in repo.jobs}


def test_job_missing_twice_in_a_row_is_closed():
    repo = FakeRepo([COMPANY])
    _run(repo, [posting(ext="1"), posting(ext="2", title="Solutions Engineer")])
    _run(repo, [posting(ext="1")])
    assert _closed(repo) == {"1": None, "2": None}  # first miss only counts
    stats = _run(repo, [posting(ext="1")])
    assert _closed(repo) == {"1": None, "2": "now"}
    assert stats.closed_jobs == 1


def test_job_that_reappears_is_reset():
    repo = FakeRepo([COMPANY])
    _run(repo, [posting(ext="1"), posting(ext="2", title="Solutions Engineer")])
    _run(repo, [posting(ext="1")])
    _run(repo, [posting(ext="1"), posting(ext="2", title="Solutions Engineer")])
    job = next(j for j in repo.jobs if j["external_id"] == "2")
    assert job["missing_runs"] == 0 and job["closed_at"] is None


def test_empty_or_failed_board_closes_nothing():
    repo = FakeRepo([COMPANY])
    _run(repo, [posting(ext="1")])
    for _ in range(3):
        _run(repo, [])
    assert _closed(repo) == {"1": None}

    def boom(ats, client, name, slug):
        raise RuntimeError("down")

    for _ in range(3):
        _run(repo, [], fetch=boom)
    assert _closed(repo) == {"1": None}
