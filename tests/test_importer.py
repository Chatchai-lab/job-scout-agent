import json

import httpx
import pytest
from fakes import FakeNotifier, FakeRepo

from job_scout.config import Settings
from job_scout.importer import (
    HELP_UNREADABLE,
    ReadPosting,
    extract_page_text,
    fetch_page,
    run_import,
)
from job_scout.pricing import Usage
from job_scout.scoring import ScoreResult

USAGE = Usage(input_tokens=1000, cache_read_tokens=0, cache_write_tokens=0, output_tokens=100)
LONG = "Aufgaben: Entwicklung von KI-Anwendungen mit Python. " * 8


def placeholder(**over):
    return {
        "source": "manual", "external_id": "x1", "company_name": "Link-Import",
        "title": "Stelle wird gelesen", "url": "https://firma.de/jobs/1", "description": None,
        "kind": "posting", "closed_at": "2026-10-28T20:00:00Z", "dedup_key": "manual|x1", **over,
    }


def result(**over):
    base = dict(fit=7, reach=6, ring="nah", sales_share=0.0, start_ok=True, salary=None,
                reason="Passt gut.")
    return ScoreResult(**{**base, **over})


def setup(row=None):
    repo = FakeRepo()
    repo.insert_jobs([row or placeholder()])
    return repo, repo.jobs[0]["id"], FakeNotifier()


def run(repo, job_id, notifier, *, page=LONG, read=None, score=None):
    calls = {"read": 0, "score": 0, "fetch": 0}

    def fetch_fn(url):
        calls["fetch"] += 1
        if isinstance(page, Exception):
            raise page
        return page

    def read_fn(text, url):
        calls["read"] += 1
        return read or ReadPosting(
            is_job_posting=True, company="Beispiel GmbH", title="Software Engineer (m/w/d)",
            location="Darmstadt", remote=False, description=LONG,
        ), USAGE

    def score_fn(system, posting):
        calls["score"] += 1
        return score or result(), USAGE

    outcome = run_import(
        repo, Settings(), notifier, job_id,
        fetch_fn=fetch_fn, read_fn=read_fn, score_fn=score_fn, profile_text="profil",
    )
    return outcome, calls


def test_link_is_read_scored_and_sent_with_buttons():
    repo, job_id, notifier = setup()
    outcome, calls = run(repo, job_id, notifier)
    job = repo.jobs[0]
    assert outcome == "sent" and calls == {"fetch": 1, "read": 1, "score": 1}
    assert (job["company_name"], job["title"], job["location"]) == (
        "Beispiel GmbH", "Software Engineer (m/w/d)", "Darmstadt",
    )
    assert job["closed_at"] is None
    assert job["dedup_key"].startswith("beispiel")
    assert job_id in repo.scores
    text, sent_id = notifier.sent[-1]
    assert sent_id is None, "no card with buttons, the digest shows the job"
    assert "Beispiel GmbH" in text and "Fit 7/10" in text and "Digest" in text
    assert repo.scores[job_id]["notified_at"] is None
    # llm_usage only allows match, package and feedback as purpose
    assert [u["purpose"] for u in repo.usage] == ["match", "match"]


def test_pasted_text_skips_fetching_and_reading():
    row = placeholder(company_name="Acme", title="Werkstudent IT", description=LONG, url="")
    repo, job_id, notifier = setup(row)
    outcome, calls = run(repo, job_id, notifier)
    assert outcome == "sent" and calls == {"fetch": 0, "read": 0, "score": 1}
    assert repo.jobs[0]["kind"] == "working_student"
    assert repo.jobs[0]["closed_at"] is None
    assert "Acme" in notifier.sent[-1][0]


def test_unreadable_page_asks_for_pasted_text_and_removes_the_placeholder():
    repo, job_id, notifier = setup()
    outcome, calls = run(repo, job_id, notifier, page="Bitte einloggen")
    assert outcome == "unreadable" and calls["score"] == 0
    assert repo.jobs == []
    assert notifier.sent[-1][0] == HELP_UNREADABLE


def test_fetch_error_is_handled_like_an_unreadable_page():
    repo, job_id, notifier = setup()
    outcome, _ = run(repo, job_id, notifier, page=httpx.ConnectError("boom"))
    assert outcome == "unreadable" and repo.jobs == []


def test_page_that_is_no_job_ad_is_rejected():
    repo, job_id, notifier = setup()
    read = ReadPosting(is_job_posting=False)
    outcome, calls = run(repo, job_id, notifier, read=read)
    assert outcome == "not_a_posting" and calls["score"] == 0 and repo.jobs == []
    assert "Stellenanzeige" in notifier.sent[-1][0]


def test_already_imported_job_is_sent_again_without_new_calls():
    repo, job_id, notifier = setup()
    run(repo, job_id, notifier)
    outcome, calls = run(repo, job_id, notifier)
    assert outcome == "resent" and calls == {"fetch": 0, "read": 0, "score": 0}
    assert notifier.sent[-1][0].startswith("🔁") and notifier.sent[-1][1] is None


def test_budget_stops_the_import():
    repo, job_id, notifier = setup()
    repo.spent = 100.0
    outcome, calls = run(repo, job_id, notifier)
    assert outcome == "budget" and calls == {"fetch": 0, "read": 0, "score": 0}


def test_unknown_job_id():
    repo, _, notifier = setup()
    outcome, _ = run(repo, "does-not-exist", notifier)
    assert outcome == "unknown"


def test_page_text_prefers_structured_job_data():
    ld = {"@context": "https://schema.org", "@type": "JobPosting", "title": "AI Engineer",
          "hiringOrganization": {"name": "Beispiel AG"},
          "jobLocation": {"address": {"addressLocality": "Frankfurt"}},
          "description": "<p>" + LONG + "</p>"}
    script = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    page = f"<html><body><nav>Menü</nav>{script}</body></html>"
    text = extract_page_text(page)
    assert "Titel: AI Engineer" in text and "Firma: Beispiel AG" in text
    assert "Ort: Frankfurt" in text and "Menü" not in text


def test_page_text_drops_scripts_menus_and_tags():
    page = ("<html><head><style>p{}</style></head><body><nav>Home</nav><script>var a=1;</script>"
            "<h1>Stelle</h1><p>Wir suchen <b>dich</b>.</p><footer>Impressum</footer></body></html>")
    text = extract_page_text(page)
    assert "Wir suchen dich." in text
    assert all(x not in text for x in ("var a", "Home", "Impressum", "<"))


def test_fetch_page_rejects_non_http_links_and_non_html():
    with httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"x")
    )) as client:
        with pytest.raises(ValueError):
            fetch_page(client, "file:///etc/passwd")
        with pytest.raises(ValueError):
            fetch_page(client, "https://firma.de/job.pdf")


def test_job_added_by_hand_counts_even_below_the_thresholds():
    repo, job_id, notifier = setup()
    run(repo, job_id, notifier, score=result(fit=4, reach=4))
    assert "erscheint im nächsten Digest" in notifier.sent[-1][0]
    assert repo.scores[job_id]["notified_at"] is None
