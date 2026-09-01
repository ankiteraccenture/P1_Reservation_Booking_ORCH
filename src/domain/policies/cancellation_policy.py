"""Room cancellation policy — FR-018a.

Full refund if the cancellation is at least 48 hours before check-in;
otherwise the paid amount minus one night's base rate (clamped to zero).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from src.domain.value_objects.money import Money


def compute_room_refund(
    paid_amount: Money,
    base_nightly_rate: Money,
    cancellation_time_utc: datetime,
    check_in_local: datetime,
) -> Money:
    """Return the refundable amount for a paid room reservation.

    ``check_in_local`` is treated as the property's local midnight of the check-in date.
    ``cancellation_time_utc`` and ``check_in_local`` may be tz-aware or naive; caller
    is responsible for the correct property-local conversion (FR-018a).
    """
    cutoff = check_in_local - timedelta(hours=48)
    # Normalize tzinfo for comparison
    if cancellation_time_utc.tzinfo is not None and cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=cancellation_time_utc.tzinfo)
    if cancellation_time_utc <= cutoff:
        return paid_amount
    return (paid_amount - base_nightly_rate).clamp_zero()


def compute_flight_refund(provider_refundable: Money) -> Money:
    """FR-018b — trust the provider adapter's cancellation-quote result."""
    return provider_refundable.clamp_zero()
