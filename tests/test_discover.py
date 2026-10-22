import httpx
import respx

from job_scout.discover import Match, find_board, run_discover, slug_variants


def test_slug_variants_drop_legal_forms():
    assert slug_variants("Aleph Alpha GmbH") == ["alephalpha", "aleph-alpha"]
    assert slug_variants("Celonis SE") == ["celonis"]


@respx.mock
def test_find_board_returns_first_vendor_with_open_jobs():
    respx.get("https://boards-api.greenhouse.io/v1/boards/exampleco/jobs").mock(
        return_value=httpx.Response(404)
    )
    respx.get("https://boards-api.eu.greenhouse.io/v1/boards/exampleco/jobs").mock(
        return_value=httpx.Response(404)
    )
    respx.get("https://api.ashbyhq.com/posting-api/job-board/exampleco").mock(
        return_value=httpx.Response(
            200,
            json={"jobs": [{"id": "1", "title": "Solutions Engineer",
                            "jobUrl": "https://jobs.ashbyhq.com/exampleco/1",
                            "location": "Berlin", "descriptionPlain": "x"}]},
        )
    )
    with httpx.Client() as client:
        match = find_board(client, "Exampleco GmbH")
    assert match is not None
    assert (match.ats, match.slug, match.open_jobs) == ("ashby", "exampleco", 1)
    assert match.sample_titles == ["Solutions Engineer"]


@respx.mock
def test_find_board_none_when_every_vendor_misses():
    respx.route().mock(return_value=httpx.Response(404))
    with httpx.Client() as client:
        assert find_board(client, "Nobody GmbH") is None


class _Store:
    def __init__(self, names):
        self.names = names
        self.found: dict[str, Match] = {}
        self.missing: list[str] = []

    def pending(self):
        return self.names

    def save_found(self, name, match):
        self.found[name] = match

    def save_not_found(self, name):
        self.missing.append(name)


@respx.mock
def test_run_discover_saves_hits_and_misses():
    respx.get("https://boards-api.greenhouse.io/v1/boards/hit/jobs").mock(
        return_value=httpx.Response(
            200,
            json={"jobs": [{"id": 1, "title": "FDE", "absolute_url": "https://x/1",
                            "location": {"name": "Berlin"}, "content": ""}]},
        )
    )
    respx.route().mock(return_value=httpx.Response(404))
    store = _Store(["Hit", "Miss"])
    with httpx.Client() as client:
        assert run_discover(client, store) == (1, 1)
    assert store.found["Hit"].ats == "greenhouse"
    assert store.missing == ["Miss"]
