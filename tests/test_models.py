from job_scout.models import JobPosting


def _job(**overrides) -> JobPosting:
    base = dict(
        source="greenhouse",
        external_id="1",
        company_name="Example AI GmbH",
        title="Forward Deployed Engineer (m/w/d)",
        url="https://example.com/jobs/1",
        location="München, Bayern, Germany",
    )
    return JobPosting(**(base | overrides))


def test_same_job_from_two_sources_shares_dedup_key():
    api = _job()
    mail = _job(
        source="linkedin_mail",
        external_id="li-99",
        company_name="Example AI",
        title="Forward Deployed Engineer",
        location="Munich",
    )
    assert api.dedup_key == mail.dedup_key == "example-ai|forward-deployed-engineer|munich"


def test_different_city_gives_different_key():
    assert _job().dedup_key != _job(location="Berlin, Germany").dedup_key


def test_missing_location_still_builds_key():
    assert _job(location=None).dedup_key.endswith("|")
