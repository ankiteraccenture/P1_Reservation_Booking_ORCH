"""Reservation orchestrator — implements the hold → pay → confirm → cancel saga.

All state-changing methods:
- accept an idempotency key + correlation id
- persist domain writes + outbox events + idempotency dedup in one transaction
- emit AuditEvent rows for every transition (FR-029, FR-030)
"""
from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.persistence.models import (
    AuditEvent,
    Flight,
    Guest,
    IdempotencyRecord,
    OutboxMessage,
    Payment,
    Refund,
    Reservation,
    Room,
)
from src.adapters.providers.stubs import (
    NotificationStub,
    PaymentStub,
    PaymentTimeoutError,
)
from src.config import get_settings
from src.domain.policies.cancellation_policy import (
    compute_flight_refund,
    compute_room_refund,
)
from src.domain.pricing.engine import quote as price_quote
from src.domain.state_machines.refund_sm import (
    RefundState,
    assert_executable,
    check_four_eyes,
)
from src.domain.state_machines.reservation_sm import (
    ReservationState,
    assert_transition,
)
from src.domain.value_objects.money import Money


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime | None) -> datetime | None:
    """SQLite returns tz-naive datetimes; coerce to UTC for safe comparison."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _confirmation_code() -> str:
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32
    return "".join(secrets.choice(alphabet) for _ in range(8))


class ReservationConflict(Exception):
    pass


class NotFound(Exception):
    pass


class IdempotencyReplay(Exception):
    """Sentinel — carries the original response."""

    def __init__(self, status: int, body: dict) -> None:
        super().__init__("replay")
        self.status = status
        self.body = body


def _hash_request(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


async def _check_idempotency(
    session: AsyncSession, key: str | None, route: str, payload: dict
) -> None:
    if not key:
        return
    row = (
        await session.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.key == key,
                IdempotencyRecord.route == route,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return
    if row.request_hash != _hash_request(payload):
        raise ReservationConflict("idempotency key reused with different payload")
    raise IdempotencyReplay(row.response_status, row.response_body)


async def _record_idempotency(
    session: AsyncSession,
    key: str | None,
    route: str,
    payload: dict,
    status: int,
    body: dict,
) -> None:
    if not key:
        return
    session.add(
        IdempotencyRecord(
            key=key,
            route=route,
            request_hash=_hash_request(payload),
            response_status=status,
            response_body=body,
        )
    )


async def _emit(
    session: AsyncSession,
    *,
    event_type: str,
    aggregate_id: str,
    payload: dict,
    correlation_id: str,
    actor_sub: str,
    actor_role: str,
    entity_type: str,
    action: str,
) -> None:
    session.add(
        OutboxMessage(
            event_type=event_type,
            aggregate_id=aggregate_id,
            payload=payload,
            correlation_id=correlation_id,
        )
    )
    session.add(
        AuditEvent(
            correlation_id=correlation_id,
            actor_sub=actor_sub,
            actor_role=actor_role,
            entity_type=entity_type,
            entity_id=aggregate_id,
            action=action,
            payload=payload,
        )
    )


def _reservation_to_dict(r: Reservation) -> dict:
    return {
        "reservation_id": r.id,
        "guest_id": r.guest_id,
        "item_type": r.item_type,
        "item_id": r.item_id,
        "state": r.state,
        "total_amount": float(r.total_amount) if r.total_amount is not None else None,
        "currency": r.currency,
        "confirmation_code": r.confirmation_code,
        "check_in": r.check_in.isoformat() if r.check_in else None,
        "check_out": r.check_out.isoformat() if r.check_out else None,
        "nights": r.nights,
        "hold_expires_at": r.hold_expires_at.isoformat() if r.hold_expires_at else None,
        "price_breakdown": r.price_breakdown,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
        "version": r.version,
    }


# ---- Orchestrator ----------------------------------------------------------


class Orchestrator:
    def __init__(
        self,
        payment: PaymentStub,
        notifier: NotificationStub,
    ) -> None:
        self._payment = payment
        self._notifier = notifier

    # -- Hold ---------------------------------------------------------------

    async def place_hold(
        self,
        session: AsyncSession,
        *,
        guest_id: str,
        item_type: str,
        item_id: str,
        check_in: datetime | None,
        check_out: datetime | None,
        idempotency_key: str | None,
        correlation_id: str,
        actor_sub: str,
    ) -> Reservation:
        payload = {
            "guest_id": guest_id,
            "item_type": item_type,
            "item_id": item_id,
            "check_in": check_in.isoformat() if check_in else None,
            "check_out": check_out.isoformat() if check_out else None,
        }
        await _check_idempotency(session, idempotency_key, "placeHold", payload)

        guest = await session.get(Guest, guest_id)
        if guest is None:
            raise NotFound(f"guest {guest_id} not found")

        nights = 0
        total = Money.of("0")
        breakdown_json: list[dict] = []

        if item_type == "FLIGHT":
            flight = await session.get(Flight, item_id)
            if flight is None:
                raise NotFound(f"flight {item_id} not found")
            if flight.seats_available <= 0:
                raise ReservationConflict("flight sold out")
            flight.seats_available -= 1
            result = price_quote(
                base_rate=Money.of(flight.base_fare),
                nights=1,
                stay_start=flight.departure_at.date(),
                seats_available=flight.seats_available,
                capacity=flight.seat_capacity,
                loyalty_tier=guest.loyalty_tier,
            )
            total = result.total
            breakdown_json = [
                {"rule": l.rule, "delta": float(l.delta.amount), "description": l.description}
                for l in result.breakdown
            ]
        elif item_type == "ROOM":
            room = await session.get(Room, item_id)
            if room is None:
                raise NotFound(f"room {item_id} not found")
            if not (check_in and check_out):
                raise ReservationConflict("room hold requires check_in and check_out")
            nights = max(1, (check_out.date() - check_in.date()).days)
            # Verify inventory covers the range (FR-002)
            calendar = set(room.availability_calendar or [])
            span = [(check_in.date() + timedelta(days=i)).isoformat() for i in range(nights)]
            if not all(d in calendar for d in span):
                raise ReservationConflict("room not available for full range")
            result = price_quote(
                base_rate=Money.of(room.base_rate),
                nights=nights,
                stay_start=check_in.date(),
                seats_available=1,
                capacity=1,
                loyalty_tier=guest.loyalty_tier,
            )
            total = result.total
            breakdown_json = [
                {"rule": l.rule, "delta": float(l.delta.amount), "description": l.description}
                for l in result.breakdown
            ]
        else:
            raise ReservationConflict(f"unknown item_type {item_type}")

        settings = get_settings()
        rsvn = Reservation(
            id=_new_id("R"),
            guest_id=guest_id,
            item_type=item_type,
            item_id=item_id,
            state=ReservationState.HELD.value,
            total_amount=total.amount,
            currency=total.currency,
            check_in=check_in,
            check_out=check_out,
            nights=nights or None,
            hold_expires_at=_now() + timedelta(minutes=settings.hold_ttl_minutes),
            price_breakdown=breakdown_json,
        )
        session.add(rsvn)
        await session.flush()

        await _emit(
            session,
            event_type="reservation.created",
            aggregate_id=rsvn.id,
            payload={"item_type": item_type, "item_id": item_id, "total": float(total.amount)},
            correlation_id=correlation_id,
            actor_sub=actor_sub,
            actor_role="guest",
            entity_type="reservation",
            action="place_hold",
        )
        await _record_idempotency(
            session, idempotency_key, "placeHold", payload, 201, _reservation_to_dict(rsvn)
        )
        await session.commit()
        return rsvn

    # -- Pay ---------------------------------------------------------------

    async def pay(
        self,
        session: AsyncSession,
        *,
        reservation_id: str,
        payment_token: str,
        idempotency_key: str | None,
        correlation_id: str,
        actor_sub: str,
    ) -> Reservation:
        payload = {"reservation_id": reservation_id, "payment_token": payment_token}
        await _check_idempotency(session, idempotency_key, "payReservation", payload)

        rsvn = await session.get(Reservation, reservation_id)
        if rsvn is None:
            raise NotFound(f"reservation {reservation_id} not found")
        current = ReservationState(rsvn.state)
        if current is not ReservationState.HELD:
            raise ReservationConflict(f"reservation not payable in state {current.value}")
        if rsvn.hold_expires_at and _as_utc(rsvn.hold_expires_at) < _now():
            raise ReservationConflict("hold expired")

        amount = Money(Decimal(str(rsvn.total_amount)), rsvn.currency)
        try:
            auth = await self._payment.authorize(amount, payment_token)
        except PaymentTimeoutError:
            # FR-015a — terminal CANCELLED_PAYMENT_FAILED
            assert_transition(current, ReservationState.CANCELLED_PAYMENT_FAILED)
            rsvn.state = ReservationState.CANCELLED_PAYMENT_FAILED.value
            rsvn.version += 1
            await self._release_inventory(session, rsvn)
            await _emit(
                session,
                event_type="payment.failed",
                aggregate_id=rsvn.id,
                payload={"reason": "provider_timeout"},
                correlation_id=correlation_id,
                actor_sub=actor_sub,
                actor_role="guest",
                entity_type="reservation",
                action="payment_failed",
            )
            await _record_idempotency(
                session, idempotency_key, "payReservation", payload, 200, _reservation_to_dict(rsvn)
            )
            await session.commit()
            return rsvn

        assert_transition(current, ReservationState.PAID)
        payment = Payment(
            id=_new_id("PMT"),
            reservation_id=rsvn.id,
            amount=rsvn.total_amount,
            currency=rsvn.currency,
            provider_ref=auth.provider_ref,
            status="AUTHORIZED",
        )
        session.add(payment)
        rsvn.state = ReservationState.PAID.value
        rsvn.version += 1

        await _emit(
            session,
            event_type="payment.authorized",
            aggregate_id=rsvn.id,
            payload={"payment_id": payment.id, "amount": float(rsvn.total_amount)},
            correlation_id=correlation_id,
            actor_sub=actor_sub,
            actor_role="guest",
            entity_type="reservation",
            action="pay",
        )
        await _record_idempotency(
            session, idempotency_key, "payReservation", payload, 200, _reservation_to_dict(rsvn)
        )
        await session.commit()
        return rsvn

    # -- Confirm ----------------------------------------------------------

    async def confirm(
        self,
        session: AsyncSession,
        *,
        reservation_id: str,
        idempotency_key: str | None,
        correlation_id: str,
        actor_sub: str,
    ) -> Reservation:
        payload = {"reservation_id": reservation_id}
        await _check_idempotency(session, idempotency_key, "confirmReservation", payload)

        rsvn = await session.get(Reservation, reservation_id)
        if rsvn is None:
            raise NotFound(f"reservation {reservation_id} not found")
        current = ReservationState(rsvn.state)
        if current is not ReservationState.PAID:
            raise ReservationConflict(f"reservation not confirmable in state {current.value}")

        # Capture with provider
        payment = (
            await session.execute(select(Payment).where(Payment.reservation_id == rsvn.id))
        ).scalars().first()
        if payment is None:
            raise ReservationConflict("no payment attached")
        result = await self._payment.capture(payment.provider_ref)
        payment.status = result.status

        assert_transition(current, ReservationState.CONFIRMED)
        rsvn.state = ReservationState.CONFIRMED.value
        rsvn.confirmation_code = _confirmation_code()
        rsvn.version += 1

        guest = await session.get(Guest, rsvn.guest_id)
        if guest is not None:
            await self._notifier.send_confirmation(
                to=guest.email,
                reservation_id=rsvn.id,
                confirmation_code=rsvn.confirmation_code,
            )

        await _emit(
            session,
            event_type="booking.confirmed",
            aggregate_id=rsvn.id,
            payload={"confirmation_code": rsvn.confirmation_code},
            correlation_id=correlation_id,
            actor_sub=actor_sub,
            actor_role="guest",
            entity_type="reservation",
            action="confirm",
        )
        await _emit(
            session,
            event_type="notification.sent",
            aggregate_id=rsvn.id,
            payload={"channel": "email"},
            correlation_id=correlation_id,
            actor_sub="system",
            actor_role="system",
            entity_type="reservation",
            action="notify",
        )
        await _record_idempotency(
            session, idempotency_key, "confirmReservation", payload, 200, _reservation_to_dict(rsvn)
        )
        await session.commit()
        return rsvn

    # -- Cancel ------------------------------------------------------------

    async def cancel(
        self,
        session: AsyncSession,
        *,
        reservation_id: str,
        reason: str | None,
        idempotency_key: str | None,
        correlation_id: str,
        actor_sub: str,
    ) -> tuple[Reservation, Refund | None]:
        payload = {"reservation_id": reservation_id, "reason": reason}
        await _check_idempotency(session, idempotency_key, "cancelReservation", payload)

        rsvn = await session.get(Reservation, reservation_id)
        if rsvn is None:
            raise NotFound(f"reservation {reservation_id} not found")
        current = ReservationState(rsvn.state)

        was_paid = current in (ReservationState.PAID, ReservationState.CONFIRMED)
        target = ReservationState.CANCELLED
        assert_transition(current, target)

        await self._release_inventory(session, rsvn)
        rsvn.state = target.value
        rsvn.version += 1

        refund: Refund | None = None
        if was_paid:
            payment = (
                await session.execute(select(Payment).where(Payment.reservation_id == rsvn.id))
            ).scalars().first()
            if payment is None:
                raise ReservationConflict("no payment to refund")

            paid = Money(Decimal(str(payment.amount)), payment.currency)
            if rsvn.item_type == "ROOM" and rsvn.check_in and rsvn.nights:
                room = await session.get(Room, rsvn.item_id)
                base_rate = Money.of(room.base_rate) if room else Money.of("0")
                amount = compute_room_refund(
                    paid_amount=paid,
                    base_nightly_rate=base_rate,
                    cancellation_time_utc=_now(),
                    check_in_local=rsvn.check_in,
                )
                policy_code = "ROOM_48H"
            else:
                # FR-018b: provider adapter returns paid amount as v1 stub
                amount = compute_flight_refund(paid)
                policy_code = "FLIGHT_PROVIDER"

            refund = Refund(
                id=_new_id("RF"),
                reservation_id=rsvn.id,
                payment_id=payment.id,
                amount=amount.amount,
                currency=amount.currency,
                policy_code=policy_code,
                reason=reason or "customer_request",
                state=RefundState.REQUESTED.value,
                requester_sub=actor_sub,
            )
            session.add(refund)

            await _emit(
                session,
                event_type="refund.requested",
                aggregate_id=refund.id,
                payload={
                    "reservation_id": rsvn.id,
                    "amount": float(amount.amount),
                    "policy_code": policy_code,
                },
                correlation_id=correlation_id,
                actor_sub=actor_sub,
                actor_role="guest",
                entity_type="refund",
                action="request",
            )

        await _emit(
            session,
            event_type="cancellation.completed",
            aggregate_id=rsvn.id,
            payload={"reason": reason},
            correlation_id=correlation_id,
            actor_sub=actor_sub,
            actor_role="guest",
            entity_type="reservation",
            action="cancel",
        )
        await _record_idempotency(
            session, idempotency_key, "cancelReservation", payload, 200, _reservation_to_dict(rsvn)
        )
        await session.commit()
        return rsvn, refund

    async def _release_inventory(self, session: AsyncSession, rsvn: Reservation) -> None:
        if rsvn.item_type == "FLIGHT":
            flight = await session.get(Flight, rsvn.item_id)
            if flight is not None:
                flight.seats_available += 1


# ---- Refund approval service (four-eyes gate) ------------------------------


class RefundApprovalService:
    def __init__(self, payment: PaymentStub) -> None:
        self._payment = payment

    async def approve(
        self,
        session: AsyncSession,
        *,
        refund_id: str,
        approver_sub: str,
        correlation_id: str,
    ) -> Refund:
        refund = await session.get(Refund, refund_id)
        if refund is None:
            raise NotFound(f"refund {refund_id} not found")
        if refund.state != RefundState.REQUESTED.value:
            raise ReservationConflict(f"refund not approvable in state {refund.state}")

        check_four_eyes(refund.requester_sub, approver_sub)

        refund.state = RefundState.APPROVED.value
        refund.approver_sub = approver_sub

        # Fail-closed re-check inside the same tx before dispatching (Principle VI.2).
        assert_executable(RefundState(refund.state))
        payment = await session.get(Payment, refund.payment_id)
        if payment is None:
            raise ReservationConflict("payment missing for refund")
        amount = Money(Decimal(str(refund.amount)), refund.currency)
        await self._payment.refund(payment.provider_ref, amount)
        refund.state = RefundState.EXECUTED.value

        await _emit(
            session,
            event_type="refund.approved",
            aggregate_id=refund.id,
            payload={"approver_sub": approver_sub},
            correlation_id=correlation_id,
            actor_sub=approver_sub,
            actor_role="approver",
            entity_type="refund",
            action="approve",
        )
        await _emit(
            session,
            event_type="refund.executed",
            aggregate_id=refund.id,
            payload={"amount": float(refund.amount)},
            correlation_id=correlation_id,
            actor_sub=approver_sub,
            actor_role="approver",
            entity_type="refund",
            action="execute",
        )
        await session.commit()
        return refund

    async def revoke(
        self,
        session: AsyncSession,
        *,
        refund_id: str,
        actor_sub: str,
        correlation_id: str,
    ) -> Refund:
        refund = await session.get(Refund, refund_id)
        if refund is None:
            raise NotFound(f"refund {refund_id} not found")
        if refund.state != RefundState.REQUESTED.value:
            # Executed refunds are non-revocable (Principle VI.5 says pre-execution only).
            raise ReservationConflict("only pending refunds may be revoked")
        refund.state = RefundState.REVOKED.value
        await _emit(
            session,
            event_type="refund.revoked",
            aggregate_id=refund.id,
            payload={},
            correlation_id=correlation_id,
            actor_sub=actor_sub,
            actor_role="approver",
            entity_type="refund",
            action="revoke",
        )
        await session.commit()
        return refund
