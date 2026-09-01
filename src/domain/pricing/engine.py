"""Deterministic pricing engine — FR-004.

Rule pipeline order: base -> season -> occupancy_surge -> length_of_stay -> loyalty_tier.
Every rule contribution is recorded so quotes are auditable (FR-005).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from src.domain.value_objects.money import Money


@dataclass(frozen=True, slots=True)
class PricingRules:
    peak_months: tuple[int, ...] = (12, 7)
    seasonality_multiplier: Decimal = Decimal("1.25")
    occupancy_thresholds: tuple[tuple[Decimal, Decimal], ...] = (
        (Decimal("0.80"), Decimal("1.15")),
        (Decimal("0.95"), Decimal("1.30")),
    )
    length_of_stay: tuple[tuple[int, Decimal], ...] = (
        (4, Decimal("0.10")),
        (7, Decimal("0.15")),
    )
    loyalty_discount: dict[str, Decimal] = field(
        default_factory=lambda: {
            "SILVER": Decimal("0.03"),
            "GOLD": Decimal("0.05"),
            "PLATINUM": Decimal("0.08"),
        }
    )


@dataclass(frozen=True, slots=True)
class PriceBreakdownLine:
    rule: str
    delta: Money
    description: str


@dataclass(frozen=True, slots=True)
class QuoteResult:
    total: Money
    breakdown: list[PriceBreakdownLine]


def _occupancy_ratio(seats_available: int, capacity: int) -> Decimal:
    if capacity <= 0:
        return Decimal("0")
    used = capacity - max(0, seats_available)
    return Decimal(used) / Decimal(capacity)


def quote(
    *,
    base_rate: Money,
    nights: int,
    stay_start: date,
    seats_available: int,
    capacity: int,
    loyalty_tier: str | None,
    rules: PricingRules | None = None,
) -> QuoteResult:
    rules = rules or PricingRules()
    breakdown: list[PriceBreakdownLine] = []

    running = base_rate * Decimal(max(1, nights))
    breakdown.append(
        PriceBreakdownLine(
            rule="base",
            delta=running,
            description=f"{nights} × {base_rate}",
        )
    )

    # Seasonality
    if stay_start.month in rules.peak_months:
        surcharge = running * (rules.seasonality_multiplier - Decimal("1"))
        running = running + surcharge
        breakdown.append(
            PriceBreakdownLine(
                rule="season",
                delta=surcharge,
                description=f"peak month × {rules.seasonality_multiplier}",
            )
        )

    # Occupancy surge — take the highest matching threshold
    ratio = _occupancy_ratio(seats_available, capacity)
    surge_mult = Decimal("1")
    for threshold, mult in rules.occupancy_thresholds:
        if ratio >= threshold and mult > surge_mult:
            surge_mult = mult
    if surge_mult > Decimal("1"):
        surcharge = running * (surge_mult - Decimal("1"))
        running = running + surcharge
        breakdown.append(
            PriceBreakdownLine(
                rule="occupancy_surge",
                delta=surcharge,
                description=f"occupancy {ratio:.0%} × {surge_mult}",
            )
        )

    # Length of stay — take the largest applicable discount
    los_discount = Decimal("0")
    for min_nights, discount in rules.length_of_stay:
        if nights >= min_nights and discount > los_discount:
            los_discount = discount
    if los_discount > 0:
        cut = running * los_discount
        running = running - cut
        breakdown.append(
            PriceBreakdownLine(
                rule="length_of_stay",
                delta=Money(-cut.amount, cut.currency),
                description=f"{nights}-night discount −{los_discount:.0%}",
            )
        )

    # Loyalty tier
    if loyalty_tier and loyalty_tier in rules.loyalty_discount:
        pct = rules.loyalty_discount[loyalty_tier]
        cut = running * pct
        running = running - cut
        breakdown.append(
            PriceBreakdownLine(
                rule="loyalty_tier",
                delta=Money(-cut.amount, cut.currency),
                description=f"{loyalty_tier} −{pct:.0%}",
            )
        )

    return QuoteResult(total=running, breakdown=breakdown)
