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


def test_research_and_support_titles_are_dropped():
    assert prefilter(_job(title="AI Research Engineer")) == "title_excluded"
    assert prefilter(_job(title="AI Support Engineer")) == "title_excluded"


def test_non_dev_titles_are_dropped():
    assert prefilter(_job(title="Account Associate - EMEA")) == "title_excluded"
    assert prefilter(_job(title="Brand Designer, Growth")) == "title_excluded"
    assert prefilter(_job(title="Business Recruiter, GTM")) == "title_excluded"
    assert prefilter(_job(title="Office Coordinator")) == "title_not_dev"


def test_dev_titles_pass():
    for title in ("AI Engineer", "Software Developer (m/w/d)", "Applied AI Engineer",
                  "Backend Engineer", "Implementation Engineer", "Technical Consultant"):
        assert prefilter(_job(title=title)) is None, title


def test_foreign_place_in_title_is_dropped_even_without_location():
    assert prefilter(_job(title="AI Engineer - Singapore", location=None)) == "outside_germany"
    assert prefilter(_job(title="AI Engineer (UK)", location=None)) == "outside_germany"


def test_remote_with_foreign_location_is_dropped():
    job = _job(location="Remote - San Francisco, CA", remote=True)
    assert prefilter(job) == "outside_germany"


def test_german_and_foreign_place_together_is_kept():
    assert prefilter(_job(location="Berlin or London")) is None


def test_foreign_place_kept_when_abroad_enabled():
    job = _job(title="AI Engineer - Singapore", location=None)
    assert prefilter(job, include_abroad=True) is None


def test_emea_is_not_treated_as_foreign():
    assert prefilter(_job(title="Forward Deployed Engineer – EMEA", location=None)) is None


def test_us_state_and_other_foreign_remote_locations_are_dropped():
    for loc in ("Remote - Texas", "Remote - California", "Colombia", "Belgrade", "China"):
        assert prefilter(_job(location=loc, remote=True)) == "outside_germany", loc


def test_hardware_titles_are_dropped():
    assert prefilter(_job(title="Mechanical Engineer, Kinematic Systems")) == "title_excluded"
    assert prefilter(_job(title="Camera Engineer")) == "title_excluded"
