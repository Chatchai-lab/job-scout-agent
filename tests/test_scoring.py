import pytest
from fakes import llm_response, posting

from job_scout.pricing import Usage, cost_usd
from job_scout.scoring import build_system, build_user, parse_response, score_job, usage_from

GOOD = {"fit": 8, "reach": 7, "ring": "kern", "reason": "Passt."}


def test_parse_response_reads_tool_call():
    result = parse_response(llm_response(GOOD))
    assert (result.fit, result.reach, result.ring) == (8, 7, "kern")


def test_parse_response_without_tool_call_raises():
    with pytest.raises(ValueError):
        parse_response(llm_response(None))


def test_out_of_range_score_is_rejected():
    with pytest.raises(ValueError):
        parse_response(llm_response({**GOOD, "fit": 11}))


def test_usage_handles_missing_cache_fields():
    usage = usage_from(llm_response(GOOD))
    assert usage == Usage(input_tokens=10, cache_read_tokens=0, cache_write_tokens=3,
                          output_tokens=5)


def test_system_prompt_marks_cache_and_forces_tool():
    calls = {}

    class Client:
        class messages:
            @staticmethod
            def create(**kwargs):
                calls.update(kwargs)
                return llm_response(GOOD)

    result, _ = score_job(Client, "claude-haiku-5-5", build_system("p: 1", []), posting())
    assert calls["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert calls["tool_choice"] == {"type": "tool", "name": "submit_score"}
    assert result.fit == 8


def test_long_descriptions_are_truncated():
    text = build_user(posting(description="x" * 50_000))
    assert len(text) < 7000


def test_cost_haiku_and_unknown_model_fallback():
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost_usd("claude-haiku-5-5", usage) == pytest.approx(0.60)
    assert cost_usd("some-new-model", usage) > cost_usd("claude-haiku-5-5", usage)


def test_cache_reads_are_cheaper_than_fresh_input():
    fresh = cost_usd("claude-haiku-5-5", Usage(input_tokens=100_000))
    cached = cost_usd("claude-haiku-5-5", Usage(cache_read_tokens=100_000))
    assert cached == pytest.approx(fresh * 0.1)
