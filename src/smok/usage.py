"""Clearly labeled estimates, provider usage, and per-invocation request budgets."""

import math
from dataclasses import asdict, dataclass, field


class BudgetExceeded(Exception):
    pass


def estimate(text: str, chars_per_token: float = 3.0) -> int:
    # UTF-8 bytes avoid the severe undercount a character-only heuristic gives CJK/code.
    return math.ceil(len(text.encode("utf-8")) / chars_per_token)


def cost(config, usage, *, reserve=False):
    if config.local:
        return 0.0
    prices = config.prices
    needed = ("input", "output")
    if any(prices.get(k) is None for k in needed):
        return None
    read = usage.get("cache_read_input_tokens", 0)
    created = usage.get("cache_creation_input_tokens", 0)
    uncached = usage["input_tokens"] - read - created
    if reserve and config.prompt_cache and config.adapter == "anthropic":
        if "cache_write" not in prices:
            return None
        input_cost = usage["input_tokens"] * max(prices["input"], prices["cache_write"])
    else:
        if read and "cache_read" not in prices or created and "cache_write" not in prices:
            return None
        input_cost = (
            max(0, uncached) * prices["input"]
            + read * prices.get("cache_read", 0)
            + created * prices.get("cache_write", 0)
        )
    return (input_cost + usage["output_tokens"] * prices["output"]) / 1_000_000


@dataclass
class Ledger:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_requests: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    known_cost_usd: float = 0.0
    unpriced_requests: int = 0
    models: dict = field(default_factory=dict)

    def record(self, config, usage):
        self.requests += 1
        self.input_tokens += usage["input_tokens"]
        self.output_tokens += usage["output_tokens"]
        self.estimated_requests += usage.get("source") != "provider"
        for key in ("cache_read_input_tokens", "cache_creation_input_tokens"):
            setattr(self, key, getattr(self, key) + usage.get(key, 0))
        amount = cost(config, usage, reserve=usage.get("source") != "provider")
        if amount is None:
            self.unpriced_requests += 1
        else:
            self.known_cost_usd += amount
        row = self.models.setdefault(
            config.name, {"requests": 0, "input_tokens": 0, "output_tokens": 0}
        )
        row["requests"] += 1
        row["input_tokens"] += usage["input_tokens"]
        row["output_tokens"] += usage["output_tokens"]

    def export(self):
        return asdict(self)

    def merge(self, other):
        for key, value in other.export().items():
            if key == "models":
                for name, row in value.items():
                    target = self.models.setdefault(name, dict.fromkeys(row, 0))
                    for field_name, count in row.items():
                        target[field_name] += count
            else:
                setattr(self, key, getattr(self, key) + value)

    @classmethod
    def restore(cls, value):
        if not isinstance(value, dict) or set(value) - cls.__dataclass_fields__.keys():
            raise ValueError("Invalid saved token ledger.")
        ledger = cls(**value)
        for key, number in ledger.export().items():
            if key == "models":
                if not isinstance(number, dict) or any(
                    not isinstance(name, str)
                    or not isinstance(row, dict)
                    or set(row) != {"requests", "input_tokens", "output_tokens"}
                    or any(
                        not isinstance(n, int) or isinstance(n, bool) or n < 0 for n in row.values()
                    )
                    for name, row in number.items()
                ):
                    raise ValueError("Invalid saved model ledger.")
            elif (
                not isinstance(number, (float, int))
                or isinstance(number, bool)
                or number < 0
                or not math.isfinite(number)
            ):
                raise ValueError("Invalid saved usage totals.")
            elif key != "known_cost_usd" and not isinstance(number, int):
                raise ValueError("Saved token and request totals must be integers.")
        if (
            ledger.estimated_requests > ledger.requests
            or ledger.unpriced_requests > ledger.requests
            or ledger.cache_read_input_tokens + ledger.cache_creation_input_tokens
            > ledger.input_tokens
        ):
            raise ValueError("Inconsistent saved usage totals.")
        return ledger


@dataclass
class RunBudget:
    max_turns: int | None = None
    tokens: int | None = None
    dollars: float | None = None
    turns: int = 0
    usage: Ledger = field(default_factory=Ledger)
    max_requests: int | None = None
    requests: int = 0
    reservations: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        if any(
            n is not None and (not isinstance(n, int) or isinstance(n, bool))
            for n in (self.max_turns, self.tokens, self.max_requests)
        ):
            raise ValueError("Turn and token limits must be integers.")
        for number in (self.max_turns, self.tokens, self.dollars, self.max_requests):
            if number is not None and (
                not isinstance(number, (int, float))
                or isinstance(number, bool)
                or number <= 0
                or not math.isfinite(number)
            ):
                raise ValueError("Run limits must be finite positive numbers.")

    def start_turn(self):
        if self.max_turns is not None and self.turns >= self.max_turns:
            raise BudgetExceeded("User-turn limit reached for this run.")
        self.turns += 1

    def check(self, config, input_tokens):
        if self.max_requests is not None and self.requests >= self.max_requests:
            raise BudgetExceeded("Shared model-request limit reached for this run.")
        reserve = {"input_tokens": input_tokens, "output_tokens": config.max_output_tokens}
        total = (
            self.usage.input_tokens
            + self.usage.output_tokens
            + sum(reserve.values())
            + sum(row[0] for row in self.reservations.values())
        )
        if self.tokens is not None and total > self.tokens:
            raise BudgetExceeded("Token budget cannot cover the next input and output allowance.")
        if self.dollars is not None:
            amount = cost(config, reserve, reserve=True)
            if (
                amount is None
                or self.usage.unpriced_requests
                or any(row[1] is None for row in self.reservations.values())
            ):
                raise BudgetExceeded(
                    "A dollar budget requires explicit prices for this model and cache writes."
                )
            pending = sum(row[1] for row in self.reservations.values())
            if self.usage.known_cost_usd + pending + amount > self.dollars:
                raise BudgetExceeded("Dollar budget cannot cover the next request allowance.")

    def reserve(self, config, input_tokens):
        """No await between checking and booking: atomic within the asyncio event loop."""
        self.check(config, input_tokens)
        self.requests += 1
        usage = {"input_tokens": input_tokens, "output_tokens": config.max_output_tokens}
        self.reservations[self.requests] = (sum(usage.values()), cost(config, usage, reserve=True))
        return self.requests

    def settle(self, reservation, config, usage):
        self.reservations.pop(reservation)
        self.usage.record(config, usage)
