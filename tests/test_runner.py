import anthropic
import httpx

from job_scout.runner import error_detail


def test_api_errors_show_status_and_message_only():
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.example.com"))
    exc = anthropic.BadRequestError("tools.0.input_schema: invalid", response=response, body=None)
    assert error_detail(exc) == "BadRequestError 400: tools.0.input_schema: invalid"


def test_other_errors_show_the_type_only():
    assert error_detail(RuntimeError("Wohnt in Musterstr. 1")) == "RuntimeError"
