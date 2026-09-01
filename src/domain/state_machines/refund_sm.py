"""Refund state machine — Constitution Principle VI (100% line+branch target).

Enforces four-eyes gate + fail-closed default in the domain layer.
"""
from __future__ import annotations

from enum import Enum


class RefundState(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    REVOKED = "REVOKED"
    REJECTED = "REJECTED"


_TRANSITIONS: dict[RefundState, set[RefundState]] = {
    RefundState.REQUESTED: {RefundState.APPROVED, RefundState.REJECTED},
    RefundState.APPROVED: {RefundState.EXECUTED, RefundState.REVOKED},
    RefundState.EXECUTED: set(),
    RefundState.REVOKED: set(),
    RefundState.REJECTED: set(),
}


class SelfApprovalError(Exception):
    """Raised at the domain layer when requester == approver (FR-020)."""


class NotApprovedError(Exception):
    """Raised at the payment adapter when execution is attempted without APPROVED (Principle VI.2)."""


def can_transition(current: RefundState, target: RefundState) -> bool:
    return target in _TRANSITIONS.get(current, set())


def assert_transition(current: RefundState, target: RefundState) -> None:
    if not can_transition(current, target):
        raise ValueError(f"illegal refund transition: {current.value} -> {target.value}")


def check_four_eyes(requester_sub: str, approver_sub: str) -> None:
    """Domain-level enforcement of FR-020 (self-approval not permitted)."""
    if requester_sub == approver_sub:
        raise SelfApprovalError("self-approval not permitted")


def assert_executable(state: RefundState) -> None:
    """Fail-closed default: only APPROVED refunds may be sent to the provider (Principle VI.2)."""
    if state is not RefundState.APPROVED:
        raise NotApprovedError(f"refund not approved (state={state.value})")
