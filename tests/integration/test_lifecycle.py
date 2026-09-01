"""End-to-end HTTP integration test covering search → hold → pay → confirm → cancel → refund approve."""
from __future__ import annotations

import pytest


@pytest.mark.integration
async def test_health_endpoints(client):
    r = await client.get("/api/livez")
    assert r.status_code == 200
    r = await client.get("/api/readyz")
    assert r.status_code == 200


@pytest.mark.integration
async def test_search_returns_flights_and_rooms(client):
    r = await client.post(
        "/api/search",
        json={
            "kinds": ["FLIGHT", "ROOM"],
            "origin": "JFK",
            "destination": "LAX",
            "depart_date": "2026-09-15",
            "check_in": "2026-09-15",
            "check_out": "2026-09-18",
            "location": "Los Angeles",
            "guests": 2,
        },
    )
    assert r.status_code == 200
    offers = r.json()["offers"]
    kinds = {o["kind"] for o in offers}
    assert "FLIGHT" in kinds
    assert "ROOM" in kinds


@pytest.mark.integration
async def test_full_lifecycle_flight(client):
    # Hold
    r = await client.post(
        "/api/reservations",
        json={"offer_id": "FL-001", "guest_id": "G-001"},
        headers={"Idempotency-Key": "test-hold-1", "X-User-Sub": "guest-1"},
    )
    assert r.status_code == 201, r.text
    rsvn = r.json()
    assert rsvn["state"] == "HELD"
    rid = rsvn["reservation_id"]

    # Idempotent replay returns the same
    r2 = await client.post(
        "/api/reservations",
        json={"offer_id": "FL-001", "guest_id": "G-001"},
        headers={"Idempotency-Key": "test-hold-1", "X-User-Sub": "guest-1"},
    )
    assert r2.status_code == 201
    assert r2.json()["reservation_id"] == rid

    # Pay
    r = await client.post(
        f"/api/reservations/{rid}/pay",
        json={"payment_token": "tok_test"},
        headers={"Idempotency-Key": "test-pay-1", "X-User-Sub": "guest-1"},
    )
    assert r.status_code == 200
    assert r.json()["state"] == "PAID"

    # Confirm
    r = await client.post(
        f"/api/reservations/{rid}/confirm",
        headers={"Idempotency-Key": "test-conf-1", "X-User-Sub": "guest-1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "CONFIRMED"
    assert body["confirmation_code"] is not None


@pytest.mark.integration
async def test_four_eyes_self_approval_rejected(client):
    # Hold → pay → confirm a flight
    r = await client.post(
        "/api/reservations",
        json={"offer_id": "FL-003", "guest_id": "G-002"},
        headers={"X-User-Sub": "guest-2"},
    )
    rid = r.json()["reservation_id"]
    await client.post(
        f"/api/reservations/{rid}/pay",
        json={"payment_token": "tok"},
        headers={"X-User-Sub": "guest-2"},
    )
    await client.post(
        f"/api/reservations/{rid}/confirm",
        headers={"X-User-Sub": "guest-2"},
    )

    # Request refund as guest-2
    r = await client.post(
        f"/api/reservations/{rid}/refunds",
        json={"reason": "changed plans"},
        headers={"X-User-Sub": "guest-2"},
    )
    assert r.status_code == 201, r.text
    refund_id = r.json()["refund_id"]

    # guest-2 attempts self-approval → 403
    r = await client.post(
        f"/api/refunds/{refund_id}/approve",
        headers={"X-Approver-Sub": "guest-2"},
    )
    assert r.status_code == 403

    # operator-1 approves → 200 + EXECUTED
    r = await client.post(
        f"/api/refunds/{refund_id}/approve",
        headers={"X-Approver-Sub": "operator-1"},
    )
    assert r.status_code == 200
    assert r.json()["state"] == "EXECUTED"


@pytest.mark.integration
async def test_hold_expiry_sweeper_cancels_stale_holds(client, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from src.adapters.persistence.database import SessionLocal
    from src.adapters.persistence.models import Reservation
    from src.workers.hold_sweeper import sweep_once

    r = await client.post(
        "/api/reservations",
        json={"offer_id": "FL-005", "guest_id": "G-003"},
        headers={"X-User-Sub": "guest-3"},
    )
    rid = r.json()["reservation_id"]

    # Force-expire the hold
    async with SessionLocal() as s:
        rsvn = await s.get(Reservation, rid)
        rsvn.hold_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await s.commit()

    n = await sweep_once()
    assert n >= 1

    r = await client.get(f"/api/reservations/{rid}")
    assert r.json()["state"] == "CANCELLED_EXPIRED"
