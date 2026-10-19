"""Token prices and cost calculation (USD per million tokens)."""

from dataclasses import dataclass

# (input, output). Unknown models fall back to the expensive tier so the
# budget guard errs on the side of stopping early, never of overspending.
_PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
}
_FALLBACK = (2.00, 10.00)
_CACHE_READ_FACTOR = 0.10
_CACHE_WRITE_FACTOR = 1.25


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0


def cost_usd(model: str, usage: Usage) -> float:
    price_in, price_out = _PRICES.get(model, _FALLBACK)
    total = (
        usage.input_tokens * price_in
        + usage.cache_read_tokens * price_in * _CACHE_READ_FACTOR
        + usage.cache_write_tokens * price_in * _CACHE_WRITE_FACTOR
        + usage.output_tokens * price_out
    )
    return total / 1_000_000
