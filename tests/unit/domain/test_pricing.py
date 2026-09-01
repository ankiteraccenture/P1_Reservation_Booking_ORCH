"""Pricing engine unit tests (FR-004, FR-005)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.domain.pricing.engine import PricingRules, quote
from src.domain.value_objects.money import Money


def test_base_only_no_extras():
    r = quote(
        base_rate=Money.of("200"),
        nights=1,
        stay_start=date(2026, 9, 15),
        seats_available=100,
        capacity=100,
        loyalty_tier=None,
    )
    assert r.total.amount == Decimal("200.00")
    assert len(r.breakdown) == 1


def test_peak_month_applies_seasonality():
    r = quote(
        base_rate=Money.of("200"),
        nights=1,
        stay_start=date(2026, 12, 24),
        seats_available=100,
        capacity=100,
        loyalty_tier=None,
    )
    # 200 * 1.25 = 250
    assert r.total.amount == Decimal("250.00")


def test_occupancy_surge_at_95_pct():
    r = quote(
        base_rate=Money.of("100"),
        nights=1,
        stay_start=date(2026, 9, 15),
        seats_available=5,
        capacity=100,
        loyalty_tier=None,
    )
    # 5% seats available => 95% used => 1.30 surge => 100 * 1.30 = 130
    assert r.total.amount == Decimal("130.00")


def test_length_of_stay_discount_7_nights():
    r = quote(
        base_rate=Money.of("100"),
        nights=7,
        stay_start=date(2026, 9, 15),
        seats_available=100,
        capacity=100,
        loyalty_tier=None,
    )
    # 100 * 7 = 700; -15% = 595
    assert r.total.amount == Decimal("595.00")


def test_loyalty_platinum_stacks_after_los():
    r = quote(
        base_rate=Money.of("100"),
        nights=4,
        stay_start=date(2026, 9, 15),
        seats_available=100,
        capacity=100,
        loyalty_tier="PLATINUM",
    )
    # 400 - 10% = 360 - 8% = 331.20
    assert r.total.amount == Decimal("331.20")


def test_deterministic_repeat_produces_identical_price():
    kwargs = dict(
        base_rate=Money.of("189"),
        nights=5,
        stay_start=date(2026, 9, 15),
        seats_available=20,
        capacity=100,
        loyalty_tier="GOLD",
    )
    r1 = quote(**kwargs)
    r2 = quote(**kwargs)
    assert r1.total.amount == r2.total.amount
