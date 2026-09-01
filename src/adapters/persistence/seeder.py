"""Seed the SQLite database from reservation_data.json on startup."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from src.adapters.persistence.database import SessionLocal
from src.adapters.persistence.models import (
    Flight,
    Guest,
    Payment,
    Reservation,
    Room,
)
from src.config import get_settings, repo_root
from src.domain.state_machines.reservation_sm import ReservationState

_TIER_BY_PREFIX = {
    "MR-6": "PLATINUM",
    "MR-7": "GOLD",
    "MR-5": "SILVER",
    "MR-4": "SILVER",
}


def _derive_tier(loyalty_id: str | None) -> str | None:
    if not loyalty_id:
        return None
    for prefix, tier in _TIER_BY_PREFIX.items():
        if loyalty_id.startswith(prefix):
            return tier
    return "SILVER"


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def seed_if_empty() -> None:
    """Load `reservation_data.json` into SQLite if the flights table is empty."""
    settings = get_settings()
    seed_path = Path(settings.seed_file)
    if not seed_path.is_absolute():
        seed_path = repo_root() / settings.seed_file
    if not seed_path.exists():
        return

    async with SessionLocal() as session:
        existing = (await session.execute(select(Flight.id).limit(1))).first()
        if existing is not None:
            return

        raw = json.loads(seed_path.read_text(encoding="utf-8"))

        for f in raw.get("flights", []):
            session.add(
                Flight(
                    id=f["id"],
                    carrier=f["carrier"],
                    flight_number=f["flight_number"],
                    origin=f["origin"],
                    destination=f["destination"],
                    departure_at=_parse_dt(f["departure_at"]),
                    arrival_at=_parse_dt(f["arrival_at"]),
                    cabin=f["cabin"],
                    base_fare=f["base_fare"],
                    currency=f["currency"],
                    seat_capacity=f["seat_capacity"],
                    seats_available=f["seats_available"],
                    stops=f.get("stops", 0),
                )
            )

        for r in raw.get("rooms", []):
            session.add(
                Room(
                    id=r["id"],
                    property=r["property"],
                    location=r["location"],
                    room_type=r["room_type"],
                    capacity=r["capacity"],
                    base_rate=r["base_rate"],
                    currency=r["currency"],
                    peak_multiplier=r.get("peak_multiplier", 1.0),
                    peak_dates=r.get("peak_dates", []),
                    availability_calendar=r.get("availability_calendar", []),
                )
            )

        for g in raw.get("guests", []):
            session.add(
                Guest(
                    id=g["id"],
                    name=g["name"],
                    email=g["email"],
                    loyalty_id=g.get("loyalty_id"),
                    loyalty_tier=_derive_tier(g.get("loyalty_id")),
                )
            )

        for b in raw.get("bookings", []):
            state = {
                "CONFIRMED": ReservationState.CONFIRMED,
                "PENDING": ReservationState.HELD,
                "CANCELLED": ReservationState.CANCELLED,
            }.get(b["status"], ReservationState.NEW).value

            check_in = _parse_dt(b["check_in"] + "T00:00:00Z") if b.get("check_in") else None
            check_out = _parse_dt(b["check_out"] + "T00:00:00Z") if b.get("check_out") else None
            nights = (
                (check_out - check_in).days if check_in and check_out else None
            )

            session.add(
                Reservation(
                    id=b["id"],
                    guest_id=b["guest_id"],
                    item_type=b["item_type"],
                    item_id=b["item_id"],
                    state=state,
                    total_amount=b["amount"],
                    currency=b["currency"],
                    confirmation_code=b.get("payment_ref"),
                    check_in=check_in,
                    check_out=check_out,
                    nights=nights,
                    hold_expires_at=_parse_dt(b["expires_at"]) if b.get("expires_at") else None,
                    created_at=_parse_dt(b["created_at"]),
                )
            )
            if b.get("payment_ref"):
                session.add(
                    Payment(
                        id=b["payment_ref"],
                        reservation_id=b["id"],
                        amount=b["amount"],
                        currency=b["currency"],
                        provider_ref=b["payment_ref"],
                        status="CAPTURED",
                    )
                )

        await session.commit()
