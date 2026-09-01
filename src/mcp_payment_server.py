"""Payment MCP Server — exposes authorize, capture, and refund as MCP tools.

The three tools delegate to the same PaymentStub that the reservation
orchestrator uses, and can also call orchestrator.pay() / orchestrator.confirm()
/ RefundApprovalService.approve() so every operation is audit-logged and
idempotency-deduped via the SQLite idempotency_records table.

Run (stdio — for local MCP clients / VS Code extension):
    python -m src.mcp_payment_server

Or as a long-running SSE server on :8001:
    python -m src.mcp_payment_server --sse
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from contextlib import asynccontextmanager
from typing import Annotated, Any, AsyncIterator

from mcp.server.mcpserver import MCPServer

from src.adapters.persistence.database import SessionLocal, init_db
from src.adapters.persistence.seeder import seed_if_empty
from src.adapters.providers.stubs import PaymentStub, PaymentTimeoutError
from src.application.orchestrator import (
    NotFound,
    Orchestrator,
    ReservationConflict,
    RefundApprovalService,
)
from src.config import get_settings
from src.domain.state_machines.refund_sm import SelfApprovalError
from src.domain.value_objects.money import Money

# ---------------------------------------------------------------------------
# Lifespan: initialise DB + seeder once, share stubs
# ---------------------------------------------------------------------------

_settings = get_settings()
_payment_stub = PaymentStub(fail_rate=_settings.payment_fail_rate)


@asynccontextmanager
async def lifespan(server: MCPServer[Any]) -> AsyncIterator[None]:  # type: ignore[type-arg]
    await init_db()
    await seed_if_empty()
    yield


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

mcp = MCPServer(
    name="payment-mcp",
    title="Reservation Payment MCP",
    description=(
        "MCP server wrapping the reservation orchestrator's payment lifecycle. "
        "Tools: authorize (places hold + runs payment auth), capture (confirms the "
        "reservation and captures funds), refund (requests and approves a refund)."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _corr() -> str:
    return f"mcp-{uuid.uuid4().hex[:12]}"


def _idem() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Tool 1: authorize
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Place a 15-minute hold on a flight or hotel offer AND authorize the payment "
        "in one step. Equivalent to POST /api/reservations followed by POST "
        "/api/reservations/{id}/pay.\n\n"
        "Parameters:\n"
        "- offer_id: offer to hold (e.g. 'FL-001', 'RM-003')\n"
        "- guest_id: guest making the booking (e.g. 'G-001')\n"
        "- payment_token: card token (use 'tok_test_visa' in dev)\n"
        "- check_in / check_out: ISO-8601 datetime strings, required for ROOM offers\n"
        "\n"
        "Returns reservation_id, state (PAID or CANCELLED_PAYMENT_FAILED), total, "
        "hold_expires_at, and the provider_ref from the payment authorisation."
    )
)
async def authorize(
    offer_id: str,
    guest_id: str,
    payment_token: str,
    check_in: str | None = None,
    check_out: str | None = None,
) -> dict:
    """Hold inventory and authorize payment; returns PAID reservation."""
    from datetime import datetime

    settings = get_settings()
    stub = PaymentStub(fail_rate=settings.payment_fail_rate)
    from src.adapters.providers.stubs import NotificationStub

    notifier = NotificationStub()
    orch = Orchestrator(payment=stub, notifier=notifier)

    ci = datetime.fromisoformat(check_in.replace("Z", "+00:00")) if check_in else None
    co = datetime.fromisoformat(check_out.replace("Z", "+00:00")) if check_out else None
    item_type = "FLIGHT" if offer_id.startswith("FL") else "ROOM"
    corr = _corr()

    async with SessionLocal() as session:
        try:
            rsvn = await orch.place_hold(
                session,
                guest_id=guest_id,
                item_type=item_type,
                item_id=offer_id,
                check_in=ci,
                check_out=co,
                idempotency_key=_idem(),
                correlation_id=corr,
                actor_sub=guest_id,
            )
        except (NotFound, ReservationConflict) as exc:
            return {"error": str(exc), "step": "hold"}

        reservation_id = rsvn.id
        try:
            rsvn = await orch.pay(
                session,
                reservation_id=reservation_id,
                payment_token=payment_token,
                idempotency_key=_idem(),
                correlation_id=corr,
                actor_sub=guest_id,
            )
        except PaymentTimeoutError as exc:
            return {
                "error": str(exc),
                "step": "authorize",
                "reservation_id": reservation_id,
                "state": rsvn.state,
            }
        except (NotFound, ReservationConflict) as exc:
            return {"error": str(exc), "step": "authorize", "reservation_id": reservation_id}

    # look up payment row for provider_ref
    async with SessionLocal() as session:
        from sqlalchemy import select
        from src.adapters.persistence.models import Payment

        pmt = (
            await session.execute(
                select(Payment).where(Payment.reservation_id == reservation_id)
            )
        ).scalar_one_or_none()
        provider_ref = pmt.provider_ref if pmt else None

    return {
        "reservation_id": reservation_id,
        "state": rsvn.state,
        "total_amount": float(rsvn.total_amount),
        "currency": rsvn.currency,
        "hold_expires_at": rsvn.hold_expires_at.isoformat() if rsvn.hold_expires_at else None,
        "provider_ref": provider_ref,
        "correlation_id": corr,
    }


# ---------------------------------------------------------------------------
# Tool 2: capture
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Capture funds for an already-authorized (PAID) reservation and confirm the "
        "booking. Equivalent to POST /api/reservations/{id}/confirm.\n\n"
        "Parameters:\n"
        "- reservation_id: the ID returned by authorize\n"
        "- guest_id: must match the reservation owner\n"
        "\n"
        "Returns state CONFIRMED, confirmation_code, and total_amount."
    )
)
async def capture(
    reservation_id: str,
    guest_id: str,
) -> dict:
    """Capture payment and confirm reservation; returns CONFIRMED state + code."""
    from src.adapters.providers.stubs import NotificationStub

    settings = get_settings()
    stub = PaymentStub(fail_rate=settings.payment_fail_rate)
    notifier = NotificationStub()
    orch = Orchestrator(payment=stub, notifier=notifier)
    corr = _corr()

    async with SessionLocal() as session:
        try:
            rsvn = await orch.confirm(
                session,
                reservation_id=reservation_id,
                idempotency_key=_idem(),
                correlation_id=corr,
                actor_sub=guest_id,
            )
        except (NotFound, ReservationConflict) as exc:
            return {"error": str(exc), "reservation_id": reservation_id}

    return {
        "reservation_id": rsvn.id,
        "state": rsvn.state,
        "confirmation_code": rsvn.confirmation_code,
        "total_amount": float(rsvn.total_amount),
        "currency": rsvn.currency,
        "correlation_id": corr,
    }


# ---------------------------------------------------------------------------
# Tool 3: refund
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Cancel a reservation and execute a refund. Orchestrates:\n"
        "  1. orchestrator.cancel() — releases inventory and creates a REQUESTED refund\n"
        "     using the FR-018 policy (full room refund if ≥ 48h before check-in, etc.)\n"
        "  2. RefundApprovalService.approve() — four-eyes gate; approver_sub must differ\n"
        "     from the guest. Use 'operator-1' as approver_sub in dev.\n\n"
        "Parameters:\n"
        "- reservation_id: the confirmed reservation to refund\n"
        "- guest_id: the reservation owner (requester)\n"
        "- reason: human-readable reason for the refund\n"
        "- approver_sub: operator who approves (must != guest_id; default 'operator-1')\n"
        "\n"
        "Returns refund_id, state (EXECUTED on success), amount, policy_code, "
        "and approver_sub."
    )
)
async def refund(
    reservation_id: str,
    guest_id: str,
    reason: str,
    approver_sub: str = "operator-1",
) -> dict:
    """Cancel + approve refund in one call; returns EXECUTED refund."""
    from src.adapters.providers.stubs import NotificationStub

    settings = get_settings()
    stub = PaymentStub(fail_rate=settings.payment_fail_rate)
    notifier = NotificationStub()
    orch = Orchestrator(payment=stub, notifier=notifier)
    svc = RefundApprovalService(payment=stub)
    corr = _corr()

    # Step 1 — cancel and create refund request
    async with SessionLocal() as session:
        try:
            _rsvn, refund_row = await orch.cancel(
                session,
                reservation_id=reservation_id,
                reason=reason,
                idempotency_key=_idem(),
                correlation_id=corr,
                actor_sub=guest_id,
            )
        except (NotFound, ReservationConflict) as exc:
            return {"error": str(exc), "step": "cancel", "reservation_id": reservation_id}

    if refund_row is None:
        return {
            "message": "reservation cancelled with no refund (was unpaid or already cancelled)",
            "reservation_id": reservation_id,
            "state": "CANCELLED",
        }

    refund_id = refund_row.id

    # Step 2 — approve (four-eyes gate)
    async with SessionLocal() as session:
        try:
            approved = await svc.approve(
                session,
                refund_id=refund_id,
                approver_sub=approver_sub,
                correlation_id=corr,
            )
        except SelfApprovalError as exc:
            return {
                "error": str(exc),
                "step": "approve",
                "refund_id": refund_id,
                "hint": "approver_sub must differ from guest_id (requester)",
            }
        except (NotFound, ReservationConflict) as exc:
            return {"error": str(exc), "step": "approve", "refund_id": refund_id}

    return {
        "refund_id": approved.id,
        "reservation_id": approved.reservation_id,
        "state": approved.state,
        "amount": float(approved.amount),
        "currency": approved.currency,
        "policy_code": approved.policy_code,
        "reason": approved.reason,
        "requester_sub": approved.requester_sub,
        "approver_sub": approved.approver_sub,
        "correlation_id": corr,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "--sse":
        # SSE transport: clients connect via http://localhost:8001/sse
        asyncio.run(mcp.run_sse_async(host="0.0.0.0", port=8001))
    else:
        # stdio transport (default) — for MCP host runtimes and VS Code Copilot
        asyncio.run(mcp.run_stdio_async())
