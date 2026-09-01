"""Refund gate policy tests — Constitution Principle VI.

Covers: state machine legal/illegal transitions, self-approval rejection,
fail-closed executable check.
"""
from __future__ import annotations

import pytest

from src.domain.state_machines.refund_sm import (
    NotApprovedError,
    RefundState,
    SelfApprovalError,
    assert_executable,
    assert_transition,
    can_transition,
    check_four_eyes,
)


@pytest.mark.refund_gate
class TestRefundStateMachine:
    def test_requested_can_go_to_approved(self):
        assert can_transition(RefundState.REQUESTED, RefundState.APPROVED)

    def test_requested_can_go_to_rejected(self):
        assert can_transition(RefundState.REQUESTED, RefundState.REJECTED)

    def test_approved_can_go_to_executed(self):
        assert can_transition(RefundState.APPROVED, RefundState.EXECUTED)

    def test_approved_can_go_to_revoked(self):
        assert can_transition(RefundState.APPROVED, RefundState.REVOKED)

    def test_executed_is_terminal(self):
        for target in RefundState:
            assert not can_transition(RefundState.EXECUTED, target)

    def test_revoked_is_terminal(self):
        for target in RefundState:
            assert not can_transition(RefundState.REVOKED, target)

    def test_rejected_is_terminal(self):
        for target in RefundState:
            assert not can_transition(RefundState.REJECTED, target)

    def test_requested_cannot_skip_to_executed(self):
        assert not can_transition(RefundState.REQUESTED, RefundState.EXECUTED)
        with pytest.raises(ValueError):
            assert_transition(RefundState.REQUESTED, RefundState.EXECUTED)

    def test_assert_transition_ok(self):
        assert_transition(RefundState.REQUESTED, RefundState.APPROVED)


@pytest.mark.refund_gate
class TestFourEyes:
    def test_self_approval_rejected(self):
        with pytest.raises(SelfApprovalError):
            check_four_eyes("user-a", "user-a")

    def test_distinct_approver_ok(self):
        check_four_eyes("user-a", "user-b")


@pytest.mark.refund_gate
class TestFailClosedExecute:
    def test_execute_requires_approved(self):
        for state in (RefundState.REQUESTED, RefundState.EXECUTED, RefundState.REVOKED, RefundState.REJECTED):
            with pytest.raises(NotApprovedError):
                assert_executable(state)

    def test_execute_allowed_when_approved(self):
        assert_executable(RefundState.APPROVED)
