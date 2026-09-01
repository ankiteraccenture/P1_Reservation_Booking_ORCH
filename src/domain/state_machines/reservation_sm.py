"""Reservation lifecycle state machine."""
from __future__ import annotations

from enum import Enum


class ReservationState(str, Enum):
    NEW = "NEW"
    HELD = "HELD"
    PAID = "PAID"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    CANCELLED_EXPIRED = "CANCELLED_EXPIRED"
    CANCELLED_PAYMENT_FAILED = "CANCELLED_PAYMENT_FAILED"


_TRANSITIONS: dict[ReservationState, set[ReservationState]] = {
    ReservationState.NEW: {ReservationState.HELD},
    ReservationState.HELD: {
        ReservationState.PAID,
        ReservationState.CANCELLED,
        ReservationState.CANCELLED_EXPIRED,
        ReservationState.CANCELLED_PAYMENT_FAILED,
    },
    ReservationState.PAID: {ReservationState.CONFIRMED, ReservationState.CANCELLED},
    ReservationState.CONFIRMED: {ReservationState.CANCELLED},
    ReservationState.CANCELLED: set(),
    ReservationState.CANCELLED_EXPIRED: set(),
    ReservationState.CANCELLED_PAYMENT_FAILED: set(),
}


def can_transition(current: ReservationState, target: ReservationState) -> bool:
    return target in _TRANSITIONS.get(current, set())


def assert_transition(current: ReservationState, target: ReservationState) -> None:
    if not can_transition(current, target):
        raise ValueError(f"illegal reservation transition: {current.value} -> {target.value}")


TERMINAL_STATES = {
    ReservationState.CANCELLED,
    ReservationState.CANCELLED_EXPIRED,
    ReservationState.CANCELLED_PAYMENT_FAILED,
}
