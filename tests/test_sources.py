import httpx
import respx

from job_scout.sources import fetch_for, supported_ats
from job_scout.sources.greenhouse import _strip_html


@respx.mock
def test_greenhouse_fetch_parses_one_job():
    respx.get("https://boards-api.greenhouse.io/v1/boards/exampleai/jobs").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 123,
                        "title": "Forward Deployed Engineer",
                        "absolute_url": "https://job-boards.greenhouse.io/exampleai/jobs/123",
                        "location": {"name": "Munich, Germany"},
                        "updated_at": "2026-10-01T12:00:00+00:00",
                        "content": "<p>Ship <b>production</b> AI.</p>",
                    }
                ]
            },
        )
    )
    with httpx.Client() as client:
        jobs = fetch_for("greenhouse", client, "Example AI", "exampleai")

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "greenhouse"
    assert job.external_id == "123"
    assert job.title == "Forward Deployed Engineer"
    assert job.location == "Munich, Germany"
    assert job.remote is False
    assert "Ship production AI." in job.description


@respx.mock
def test_greenhouse_eu_uses_eu_host():
    route = respx.get("https://boards-api.eu.greenhouse.io/v1/boards/parloa/jobs").mock(
        return_value=httpx.Response(200, json={"jobs": []})
    )
    with httpx.Client() as client:
        jobs = fetch_for("greenhouse_eu", client, "Parloa", "parloa")

    assert route.called
    assert jobs == []


@respx.mock
def test_lever_fetch_parses_one_job():
    respx.get("https://api.lever.co/v0/postings/examplestartup").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "abc",
                    "text": "Forward Deployed Engineer",
                    "hostedUrl": "https://jobs.lever.co/examplestartup/abc",
                    "categories": {"location": "Berlin", "workplaceType": "onsite"},
                    "createdAt": 1759312800000,
                    "descriptionPlain": "Embed with customers.",
                }
            ],
        )
    )
    with httpx.Client() as client:
        jobs = fetch_for("lever", client, "Example Startup", "examplestartup")

    assert len(jobs) == 1
    assert jobs[0].source == "lever"
    assert jobs[0].location == "Berlin"
    assert jobs[0].remote is False


@respx.mock
def test_lever_empty_board_returns_no_error():
    respx.get("https://api.lever.co/v0/postings/noboard").mock(
        return_value=httpx.Response(200, json=[])
    )
    with httpx.Client() as client:
        assert fetch_for("lever", client, "No Board Inc", "noboard") == []


@respx.mock
def test_ashby_fetch_skips_unlisted_jobs():
    respx.get("https://api.ashbyhq.com/posting-api/job-board/examplestartup").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": "job-1",
                        "title": "Forward Deployed Engineer",
                        "jobUrl": "https://jobs.ashbyhq.com/examplestartup/job-1",
                        "location": "Remote (Germany)",
                        "isRemote": True,
                        "isListed": True,
                        "publishedAt": "2026-10-01T00:00:00.000Z",
                        "descriptionPlain": "Build with customers.",
                    },
                    {
                        "id": "job-2",
                        "title": "Draft role",
                        "isListed": False,
                    },
                ]
            },
        )
    )
    with httpx.Client() as client:
        jobs = fetch_for("ashby", client, "Example Startup", "examplestartup")

    assert len(jobs) == 1
    assert jobs[0].external_id == "job-1"
    assert jobs[0].remote is True


def test_unknown_ats_raises():
    import pytest

    with pytest.raises(ValueError, match="no fetcher registered"):
        fetch_for("personio", httpx.Client(), "X", "y")


def test_supported_ats_lists_all_registered_sources():
    assert supported_ats() == ["ashby", "greenhouse", "greenhouse_eu", "lever"]


def test_strip_html_collapses_tags():
    assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"
