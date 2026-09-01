"""In-process port implementations used by the v1 MVP.

These are stub adapters that satisfy the ports contract; production would swap in
real provider SDKs and message brokers.
"""
from __future__ import annotations

import random
import uuid
from dataclasses import dataclass

from src.domain.value_objects.money import Money


class PaymentTimeoutError(Exception):
    """Raised when the payment provider fails within the retry budget (FR-015a)."""


@dataclass(slots=True)
class PaymentResult:
    provider_ref: str
    status: str  # AUTHORIZED | CAPTURED | FAILED


class PaymentStub:
    """Deterministic-ish payment stub with a configurable failure rate."""

    def __init__(self, fail_rate: float = 0.0) -> None:
        self._fail_rate = max(0.0, min(1.0, fail_rate))
        self._rng = random.Random(42)

    async def authorize(self, amount: Money, token: str) -> PaymentResult:
        if self._rng.random() < self._fail_rate:
            raise PaymentTimeoutError("provider timeout")
        return PaymentResult(provider_ref=f"PMT-{uuid.uuid4().hex[:8].upper()}", status="AUTHORIZED")

    async def capture(self, provider_ref: str) -> PaymentResult:
        return PaymentResult(provider_ref=provider_ref, status="CAPTURED")

    async def refund(self, provider_ref: str, amount: Money) -> PaymentResult:
        return PaymentResult(provider_ref=provider_ref, status="REFUNDED")


class NotificationStub:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_confirmation(self, *, to: str, reservation_id: str, confirmation_code: str) -> None:
        self.sent.append(
            {"to": to, "reservation_id": reservation_id, "confirmation_code": confirmation_code}
        )
