"""Hold expiry sweeper — enforces SC-003 (expiry + 60s) and FR-010/FR-011."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from src.adapters.persistence.database import SessionLocal
from src.adapters.persistence.models import AuditEvent, Flight, OutboxMessage, Reservation
from src.config import get_settings
from src.domain.state_machines.reservation_sm import ReservationState, assert_transition

log = logging.getLogger(__name__)


async def sweep_once() -> int:
    """Cancel any HELD reservations whose expiry is past. Returns number of cancellations."""
    now = datetime.now(timezone.utc)
    count = 0
    async with SessionLocal() as session:
        stmt = select(Reservation).where(
            Reservation.state == ReservationState.HELD.value,
            Reservation.hold_expires_at.is_not(None),
        )
        rows = (await session.execute(stmt)).scalars().all()
        for rsvn in rows:
            expires = rsvn.hold_expires_at
            if expires is None:
                continue
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires >= now:
                continue
            try:
                assert_transition(ReservationState(rsvn.state), ReservationState.CANCELLED_EXPIRED)
            except ValueError:
                continue
            rsvn.state = ReservationState.CANCELLED_EXPIRED.value
            rsvn.version += 1
            if rsvn.item_type == "FLIGHT":
                flight = await session.get(Flight, rsvn.item_id)
                if flight is not None:
                    flight.seats_available += 1
            session.add(
                OutboxMessage(
                    event_type="hold.expired",
                    aggregate_id=rsvn.id,
                    payload={"reason": "expired"},
                    correlation_id=f"sweeper-{now.isoformat()}",
                )
            )
            session.add(
                AuditEvent(
                    correlation_id=f"sweeper-{now.isoformat()}",
                    actor_sub="system",
                    actor_role="system",
                    entity_type="reservation",
                    entity_id=rsvn.id,
                    action="hold_expired",
                    payload={},
                )
            )
            count += 1
        if count:
            await session.commit()
    return count


async def run_forever() -> None:
    interval = get_settings().hold_sweeper_interval_seconds
    while True:
        try:
            n = await sweep_once()
            if n:
                log.info("hold_sweeper cancelled %d expired holds", n)
        except Exception:  # pragma: no cover - safety net
            log.exception("hold_sweeper iteration failed")
        await asyncio.sleep(interval)
