"""Unified search across flights and rooms (FR-001..FR-006)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.persistence.models import Flight, Guest, Room
from src.domain.pricing.engine import quote as price_quote
from src.domain.value_objects.money import Money


@dataclass(slots=True)
class OfferDTO:
    offer_id: str
    kind: str  # FLIGHT | ROOM
    title: str
    subtitle: str
    total_price: float
    currency: str
    breakdown: list[dict]
    meta: dict


async def search(
    session: AsyncSession,
    *,
    origin: str | None,
    destination: str | None,
    depart_date: date | None,
    return_date: date | None,
    check_in: date | None,
    check_out: date | None,
    location: str | None,
    guests: int,
    guest_id: str | None,
    kinds: list[str],
) -> list[OfferDTO]:
    tier = None
    if guest_id:
        g = await session.get(Guest, guest_id)
        if g is not None:
            tier = g.loyalty_tier

    offers: list[OfferDTO] = []

    if "FLIGHT" in kinds:
        stmt = select(Flight).where(Flight.seats_available > 0)
        if origin:
            stmt = stmt.where(Flight.origin == origin.upper())
        if destination:
            stmt = stmt.where(Flight.destination == destination.upper())
        if depart_date:
            stmt = stmt.where(
                Flight.departure_at >= datetime.combine(depart_date, datetime.min.time()),
                Flight.departure_at < datetime.combine(depart_date, datetime.max.time()),
            )
        for f in (await session.execute(stmt)).scalars():
            result = price_quote(
                base_rate=Money.of(f.base_fare),
                nights=1,
                stay_start=f.departure_at.date(),
                seats_available=f.seats_available,
                capacity=f.seat_capacity,
                loyalty_tier=tier,
            )
            offers.append(
                OfferDTO(
                    offer_id=f.id,
                    kind="FLIGHT",
                    title=f"{f.carrier} {f.flight_number}",
                    subtitle=f"{f.origin} → {f.destination} · {f.cabin.title()} · {f.stops} stops",
                    total_price=float(result.total.amount),
                    currency=result.total.currency,
                    breakdown=[
                        {"rule": l.rule, "delta": float(l.delta.amount), "description": l.description}
                        for l in result.breakdown
                    ],
                    meta={
                        "departure_at": f.departure_at.isoformat(),
                        "arrival_at": f.arrival_at.isoformat(),
                        "seats_available": f.seats_available,
                    },
                )
            )

    if "ROOM" in kinds and check_in and check_out:
        nights = max(1, (check_out - check_in).days)
        stmt = select(Room)
        if location:
            stmt = stmt.where(Room.location.ilike(f"%{location}%"))
        # Capacity filter
        stmt = stmt.where(Room.capacity >= max(1, guests))
        for r in (await session.execute(stmt)).scalars():
            # FR-002: full-range availability
            cal = set(r.availability_calendar or [])
            wanted = {(check_in + timedelta(days=i)).isoformat() for i in range(nights)}
            if not wanted.issubset(cal):
                continue
            result = price_quote(
                base_rate=Money.of(r.base_rate),
                nights=nights,
                stay_start=check_in,
                seats_available=1,
                capacity=1,
                loyalty_tier=tier,
            )
            offers.append(
                OfferDTO(
                    offer_id=r.id,
                    kind="ROOM",
                    title=f"{r.property} — {r.room_type}",
                    subtitle=f"{r.location} · {nights} nights · fits {r.capacity}",
                    total_price=float(result.total.amount),
                    currency=result.total.currency,
                    breakdown=[
                        {"rule": l.rule, "delta": float(l.delta.amount), "description": l.description}
                        for l in result.breakdown
                    ],
                    meta={
                        "location": r.location,
                        "property": r.property,
                        "capacity": r.capacity,
                        "base_rate": float(r.base_rate),
                        "nights": nights,
                    },
                )
            )

    # Sort by price ascending (FR-001 says "relevance and price"; price only here).
    offers.sort(key=lambda o: o.total_price)
    return offers
