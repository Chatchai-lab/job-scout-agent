from types import SimpleNamespace

import pytest

from job_scout.toolcall import call_tool

TOOL = {"name": "submit_x", "description": "d", "input_schema": {"type": "object"}}


def _resp(content, stop="tool_use", inp=10, out=5):
    usage = SimpleNamespace(input_tokens=inp, output_tokens=out, cache_read_input_tokens=0,
                            cache_creation_input_tokens=0)
    return SimpleNamespace(content=content, usage=usage, stop_reason=stop)


def _tool_block(payload):
    return SimpleNamespace(type="tool_use", name="submit_x", input=payload)


class Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


def _call(client, **kw):
    return call_tool(client, model="m", system_text="sys", tool=TOOL, user_text="hi",
                     max_tokens=100, **kw)


def test_request_uses_auto_strict_and_effort_never_forced():
    client = Client([_resp([_tool_block({"a": 1})])])
    payload, _ = _call(client)
    request = client.requests[0]
    assert payload == {"a": 1}
    assert request["tool_choice"] == {"type": "auto"}
    assert request["tools"][0]["strict"] is True and "strict" not in TOOL
    assert request["extra_body"] == {"output_config": {"effort": "medium"}}
    assert "submit_x" in request["messages"][0]["content"]


def test_missing_tool_call_is_retried_and_usage_is_summed():
    text_only = _resp([SimpleNamespace(type="text", text="Hallo")], stop="end_turn")
    client = Client([text_only, _resp([_tool_block({"ok": True})])])
    payload, usage = _call(client)
    assert payload == {"ok": True} and len(client.requests) == 2
    assert usage.input_tokens == 20 and usage.output_tokens == 10


def test_gives_up_after_the_attempts_with_a_clear_error():
    text_only = _resp([SimpleNamespace(type="text", text="x")], stop="end_turn")
    with pytest.raises(ValueError, match="did not call submit_x"):
        _call(Client([text_only, text_only]))


def test_truncated_output_is_never_accepted():
    with pytest.raises(ValueError, match="cut off"):
        _call(Client([_resp([_tool_block({"a": 1})], stop="max_tokens")]))


def test_refusal_raises():
    with pytest.raises(ValueError, match="refused"):
        _call(Client([_resp([], stop="refusal")]))
