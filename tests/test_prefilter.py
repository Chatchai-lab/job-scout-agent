from job_scout.models import JobPosting
from job_scout.prefilter import prefilter


def _job(**overrides) -> JobPosting:
    base = dict(
        source="greenhouse",
        external_id="1",
        company_name="Example AI",
        title="Forward Deployed Engineer",
        url="https://example.com/1",
        location="Munich, Germany",
    )
    return JobPosting(**(base | overrides))


def test_core_junior_role_passes():
    assert prefilter(_job()) is None


def test_senior_title_is_dropped():
    assert prefilter(_job(title="Senior Forward Deployed Engineer")) == "senior_title"


def test_quota_sales_title_is_dropped():
    assert prefilter(_job(title="Account Executive, Enterprise")) == "sales_title"


def test_sales_engineer_title_with_fde_keyword_is_kept_for_llm():
    # "Solutions Engineer" matches TITLE_KEYWORDS even though it also
    # contains no quota language — the LLM decides fit from the description.
    assert prefilter(_job(title="Solutions Engineer")) is None


def test_us_only_is_dropped():
    job = _job(location="Remote (US only)", remote=True)
    assert prefilter(job) == "us_only"


def test_outside_germany_onsite_is_dropped_by_default():
    assert prefilter(_job(location="Paris, France")) == "outside_germany"


def test_outside_germany_onsite_kept_when_abroad_enabled():
    assert prefilter(_job(location="Paris, France"), include_abroad=True) is None


def test_remote_location_is_never_dropped_for_geography():
    job = _job(location="Remote (Europe)", remote=True)
    assert prefilter(job) is None
