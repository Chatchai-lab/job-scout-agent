"""Structured output via a tool call, for models that reject a forced tool_choice.

Claude Sonnet 5.5 answers 400 to tool_choice "tool"/"any". With "auto" the model is told in the
prompt to call the tool, `strict: true` keeps the arguments schema-valid, and a missing call is
retried. Every attempt is billed, so usage is summed over all attempts.
"""

from typing import Any

from job_scout.pricing import Usage
from job_scout.scoring import usage_from


def _add(a: Usage, b: Usage) -> Usage:
    return Usage(
        input_tokens=a.input_tokens + b.input_tokens,
        cache_read_tokens=a.cache_read_tokens + b.cache_read_tokens,
        cache_write_tokens=a.cache_write_tokens + b.cache_write_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
    )


def call_tool(
    client: Any,
    *,
    model: str,
    system_text: str,
    tool: dict[str, Any],
    user_text: str,
    max_tokens: int,
    effort: str = "medium",
    attempts: int = 2,
) -> tuple[dict[str, Any], Usage]:
    """Return the tool input the model submitted. Thinking blocks in the reply are ignored."""
    strict_tool = {**tool, "strict": True}
    prompt = f"{user_text}\n\nRufe das Tool {tool['name']} auf. Antworte nicht mit Freitext."
    total = Usage()
    for _ in range(attempts):
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
            tools=[strict_tool],
            tool_choice={"type": "auto"},
            messages=[{"role": "user", "content": prompt}],
            extra_body={"output_config": {"effort": effort}},
        )
        total = _add(total, usage_from(response))
        if response.stop_reason == "refusal":
            raise ValueError("model refused the request")
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == tool["name"]:
                if response.stop_reason == "max_tokens":
                    raise ValueError("output was cut off (max_tokens); raise the limit")
                return dict(block.input), total
    raise ValueError(f"model did not call {tool['name']}")
