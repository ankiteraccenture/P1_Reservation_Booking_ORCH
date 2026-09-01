"""SQLAlchemy 2.x async models — system-of-record schema for reservations."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---- Seed / catalog ---------------------------------------------------------


class Flight(Base):
    __tablename__ = "flights"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    carrier: Mapped[str] = mapped_column(String)
    flight_number: Mapped[str] = mapped_column(String, index=True)
    origin: Mapped[str] = mapped_column(String, index=True)
    destination: Mapped[str] = mapped_column(String, index=True)
    departure_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    arrival_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cabin: Mapped[str] = mapped_column(String)
    base_fare: Mapped[float] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    seat_capacity: Mapped[int] = mapped_column(Integer)
    seats_available: Mapped[int] = mapped_column(Integer)
    stops: Mapped[int] = mapped_column(Integer, default=0)


class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    property: Mapped[str] = mapped_column(String, index=True)
    location: Mapped[str] = mapped_column(String, index=True)
    room_type: Mapped[str] = mapped_column(String)
    capacity: Mapped[int] = mapped_column(Integer)
    base_rate: Mapped[float] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    peak_multiplier: Mapped[float] = mapped_column(Numeric(4, 2), default=1.0)
    peak_dates: Mapped[list] = mapped_column(JSON, default=list)
    availability_calendar: Mapped[list] = mapped_column(JSON, default=list)


class Guest(Base):
    __tablename__ = "guests"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    loyalty_id: Mapped[str | None] = mapped_column(String, nullable=True)
    loyalty_tier: Mapped[str | None] = mapped_column(String, nullable=True)


# ---- Domain of record -------------------------------------------------------


class Reservation(Base):
    __tablename__ = "reservations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    guest_id: Mapped[str] = mapped_column(String, ForeignKey("guests.id"), index=True)
    item_type: Mapped[str] = mapped_column(String)  # FLIGHT | ROOM
    item_id: Mapped[str] = mapped_column(String, index=True)
    state: Mapped[str] = mapped_column(String, index=True)
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    confirmation_code: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    check_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nights: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_breakdown: Mapped[list] = mapped_column(JSON, default=list)
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1)

    payments: Mapped[list["Payment"]] = relationship(back_populates="reservation", cascade="all,delete-orphan")
    refunds: Mapped[list["Refund"]] = relationship(back_populates="reservation", cascade="all,delete-orphan")


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    reservation_id: Mapped[str] = mapped_column(String, ForeignKey("reservations.id"), index=True)
    amount: Mapped[float] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    provider_ref: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)  # AUTHORIZED | CAPTURED | FAILED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    reservation: Mapped["Reservation"] = relationship(back_populates="payments")


class Refund(Base):
    __tablename__ = "refunds"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    reservation_id: Mapped[str] = mapped_column(String, ForeignKey("reservations.id"), index=True)
    payment_id: Mapped[str] = mapped_column(String, ForeignKey("payments.id"))
    amount: Mapped[float] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    policy_code: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, index=True)  # REQUESTED | APPROVED | EXECUTED | REVOKED | REJECTED
    requester_sub: Mapped[str] = mapped_column(String)
    approver_sub: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    reservation: Mapped["Reservation"] = relationship(back_populates="refunds")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    correlation_id: Mapped[str] = mapped_column(String, index=True)
    actor_sub: Mapped[str] = mapped_column(String)
    actor_role: Mapped[str] = mapped_column(String)
    entity_type: Mapped[str] = mapped_column(String)
    entity_id: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class IdempotencyRecord(Base):
    """Durable dedup — co-located with domain writes (constitution v1.3.0)."""

    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("key", "route", name="uq_idem_key_route"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String, index=True)
    route: Mapped[str] = mapped_column(String)
    request_hash: Mapped[str] = mapped_column(String)
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class OutboxMessage(Base):
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    aggregate_id: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    correlation_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
