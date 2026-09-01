"""Pure-domain value objects — no framework imports allowed."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

USD = "USD"


@dataclass(frozen=True, slots=True)
class Money:
    """Money = (Decimal amount, ISO-4217 currency). Float arithmetic is forbidden.

    Enforces FR-033 (Decimal + explicit currency) and FR-034 (USD only in v1).
    """

    amount: Decimal
    currency: str = USD

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError("Money.amount must be Decimal")
        if self.currency != USD:
            raise ValueError(f"currency not supported: {self.currency}")

    @classmethod
    def of(cls, value: str | int | float | Decimal, currency: str = USD) -> "Money":
        return cls(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN), currency)

    def __add__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: Decimal | int | str) -> "Money":
        return Money.of(self.amount * Decimal(str(factor)), self.currency)

    def clamp_zero(self) -> "Money":
        return Money(Decimal("0.00"), self.currency) if self.amount < 0 else self

    def _check(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise ValueError("currency mismatch")

    def __str__(self) -> str:
        return f"{self.amount:.2f} {self.currency}"

    def to_float(self) -> float:
        # For JSON serialization boundary only — never for arithmetic.
        return float(self.amount)
