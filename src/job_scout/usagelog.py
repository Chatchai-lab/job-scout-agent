"""Record every billed model call of a run, so a failure half-way never hides what it cost."""

from types import SimpleNamespace
from typing import Any

from job_scout.pricing import Usage, cost_usd
from job_scout.scoring import usage_from


class UsageRecorder:
    """Stands in for the Anthropic client: forwards `messages.create` and notes each response."""

    def __init__(self, client: Any):
        self._client = client
        self.calls: list[tuple[str, Usage]] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> Any:
        response = self._client.messages.create(**kwargs)
        self.calls.append((str(kwargs.get("model", "")), usage_from(response)))
        return response


def log_calls(repo: Any, purpose: str, calls: list[tuple[str, Usage]]) -> None:
    for model, u in calls:
        repo.log_usage(
            {
                "purpose": purpose,
                "model": model,
                "input_tokens": u.input_tokens,
                "cache_read_tokens": u.cache_read_tokens,
                "output_tokens": u.output_tokens,
                "cost_usd": round(cost_usd(model, u), 6),
            }
        )
