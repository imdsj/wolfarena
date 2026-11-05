"""Process-wide token/spend ledger so a nightly run cannot overspend.

Prices are the published deepseek-chat list prices rounded up; the number is
an estimate for budgeting, not an invoice. Every call records the ``usage``
block returned by the API when it is present, otherwise it falls back to a
character-count estimate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock


INPUT_CNY_PER_MILLION = 2.0
OUTPUT_CNY_PER_MILLION = 8.0
CHARS_PER_TOKEN = 1.5


@dataclass
class SpendLedger:
    limit_cny: float | None = None
    calls: int = 0
    failures: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_cny: float = 0.0
    by_source: dict[str, float] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def reset(self, *, limit_cny: float | None = None) -> None:
        with self._lock:
            self.limit_cny = limit_cny
            self.calls = 0
            self.failures = 0
            self.input_tokens = 0
            self.output_tokens = 0
            self.cost_cny = 0.0
            self.by_source = {}

    def remaining(self) -> float | None:
        if self.limit_cny is None:
            return None
        return max(0.0, self.limit_cny - self.cost_cny)

    def can_spend(self, estimate_cny: float = 0.01) -> bool:
        remaining = self.remaining()
        return remaining is None or remaining >= estimate_cny

    def record(
        self,
        *,
        source: str,
        usage: dict | None = None,
        prompt_chars: int = 0,
        completion_chars: int = 0,
    ) -> None:
        if isinstance(usage, dict) and usage.get("prompt_tokens") is not None:
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
        else:
            prompt_tokens = int(prompt_chars / CHARS_PER_TOKEN)
            completion_tokens = int(completion_chars / CHARS_PER_TOKEN)
        cost = (
            prompt_tokens * INPUT_CNY_PER_MILLION
            + completion_tokens * OUTPUT_CNY_PER_MILLION
        ) / 1_000_000
        with self._lock:
            self.calls += 1
            self.input_tokens += prompt_tokens
            self.output_tokens += completion_tokens
            self.cost_cny += cost
            self.by_source[source] = round(
                self.by_source.get(source, 0.0) + cost, 6
            )

    def record_failure(self) -> None:
        with self._lock:
            self.failures += 1

    def summary(self) -> dict[str, object]:
        return {
            "calls": self.calls,
            "failures": self.failures,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_cny": round(self.cost_cny, 4),
            "limit_cny": self.limit_cny,
            "remaining_cny": (
                None if self.remaining() is None else round(self.remaining(), 4)
            ),
            "by_source": dict(self.by_source),
        }


LEDGER = SpendLedger()
