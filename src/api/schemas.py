"""Pydantic v2 request/response schemas (single source of truth per Principle I)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    correlation_id: str | None = None


class SearchRequest(BaseModel):
    kinds: list[Literal["FLIGHT", "ROOM"]] = Field(default_factory=lambda: ["FLIGHT", "ROOM"])
    origin: str | None = None
    destination: str | None = None
    depart_date: date | None = None
    return_date: date | None = None
    check_in: date | None = None
    check_out: date | None = None
    location: str | None = None
    guests: int = 1
    guest_id: str | None = None


class BreakdownLine(BaseModel):
    rule: str
    delta: float
    description: str


class Offer(BaseModel):
    offer_id: str
    kind: Literal["FLIGHT", "ROOM"]
    title: str
    subtitle: str
    total_price: float
    currency: str
    breakdown: list[BreakdownLine]
    meta: dict


class SearchResponse(BaseModel):
    offers: list[Offer]


class PlaceHoldRequest(BaseModel):
    offer_id: str
    guest_id: str
    check_in: datetime | None = None
    check_out: datetime | None = None


class PayRequest(BaseModel):
    payment_token: str


class CancelRequest(BaseModel):
    reason: str | None = None


class RefundRequest(BaseModel):
    """Server-computes amount and policy_code (FR-018/FR-018a/FR-018b)."""

    reason: str = Field(min_length=1, max_length=1024)


class ReservationResponse(BaseModel):
    reservation_id: str
    guest_id: str
    item_type: str
    item_id: str
    state: str
    total_amount: float
    currency: str
    confirmation_code: str | None
    check_in: datetime | None
    check_out: datetime | None
    nights: int | None
    hold_expires_at: datetime | None
    price_breakdown: list[BreakdownLine]
    created_at: datetime
    updated_at: datetime
    version: int


class RefundResponse(BaseModel):
    refund_id: str
    reservation_id: str
    amount: float
    currency: str
    policy_code: str
    reason: str
    state: str
    requester_sub: str
    approver_sub: str | None
    created_at: datetime
    updated_at: datetime


class GuestListItem(BaseModel):
    id: str
    name: str
    email: str
    loyalty_id: str | None = None
    loyalty_tier: str | None = None
