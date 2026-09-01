"""Room cancellation policy (FR-018a) + flight (FR-018b)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.domain.policies.cancellation_policy import (
    compute_flight_refund,
    compute_room_refund,
)
from src.domain.value_objects.money import Money


def _utc(y, m, d, h=0):
    return datetime(y, m, d, h, tzinfo=timezone.utc)


def test_room_full_refund_when_more_than_48h_out():
    check_in = _utc(2026, 9, 20)
    cancel_at = check_in - timedelta(hours=72)
    result = compute_room_refund(
        paid_amount=Money.of("500"),
        base_nightly_rate=Money.of("100"),
        cancellation_time_utc=cancel_at,
        check_in_local=check_in,
    )
    assert result.amount == Decimal("500.00")


def test_room_retains_one_night_when_inside_48h():
    check_in = _utc(2026, 9, 20)
    cancel_at = check_in - timedelta(hours=24)
    result = compute_room_refund(
        paid_amount=Money.of("500"),
        base_nightly_rate=Money.of("100"),
        cancellation_time_utc=cancel_at,
        check_in_local=check_in,
    )
    assert result.amount == Decimal("400.00")


def test_room_refund_clamped_to_zero():
    check_in = _utc(2026, 9, 20)
    cancel_at = check_in - timedelta(hours=1)
    result = compute_room_refund(
        paid_amount=Money.of("80"),
        base_nightly_rate=Money.of("100"),
        cancellation_time_utc=cancel_at,
        check_in_local=check_in,
    )
    assert result.amount == Decimal("0.00")


def test_flight_refund_returns_provider_amount():
    result = compute_flight_refund(Money.of("125.50"))
    assert result.amount == Decimal("125.50")


def test_flight_refund_clamps_negative():
    result = compute_flight_refund(Money(Decimal("-10.00")))
    assert result.amount == Decimal("0.00")
