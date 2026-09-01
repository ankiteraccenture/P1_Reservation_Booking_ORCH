# Domain Event Contracts

**Feature**: Reservation & Booking Orchestrator
**Branch**: `001-reservation-orchestrator`
**Date**: 2026-09-01

All events are produced via the **transactional outbox** (`OutboxMessage`) and delivered
**at-least-once** through the Redis Streams broker (`stream:reservations.v1`). Consumers
MUST be idempotent by `event_id`.

## Common envelope

Every event carries this envelope. Event-specific fields live under `data`.

```json
{
  "event_id": "01J8Q…",              // ULID; same as OutboxMessage.message_id
  "event_type": "booking.confirmed", // dotted, versioned via schema_version
  "schema_version": 1,
  "occurred_at": "2026-09-01T18:12:03.482Z",
  "aggregate_type": "RESERVATION",   // RESERVATION | REFUND | PAYMENT | HOLD
  "aggregate_id": "01J8Q…",
  "correlation_id": "…",
  "traceparent": "00-…-…-01",         // W3C
  "data": { … }                      // See per-event schema below
}
```

Envelope rules:

- `occurred_at` is UTC, ISO-8601, millisecond precision.
- `traceparent` MUST be propagated by consumers.
- Consumers MUST dedupe by `event_id` (24 h window recommended).
- Ordering guarantee: **per `aggregate_id`** the publisher preserves insertion order.

## Event catalogue

| # | `event_type` | Aggregate | Emitted when | v |
|---|---|---|---|---|
| 1 | `reservation.created` | RESERVATION | Hold placed successfully | 1 |
| 2 | `hold.expired` | HOLD | Hold TTL elapsed and reservation moved to `CANCELLED_HOLD_EXPIRED` | 1 |
| 3 | `payment.authorized` | PAYMENT | PSP authorization succeeded | 1 |
| 4 | `payment.failed` | PAYMENT | PSP declined or timed out (FR-015a) | 1 |
| 5 | `booking.confirmed` | RESERVATION | Reservation entered `CONFIRMED` (capture ok) | 1 |
| 6 | `cancellation.completed` | RESERVATION | Reservation entered any `CANCELLED_*` terminal state | 1 |
| 7 | `refund.requested` | REFUND | Refund state = REQUESTED | 1 |
| 8 | `refund.approved` | REFUND | Four-eyes gate passed, state = APPROVED | 1 |
| 9 | `refund.executed` | REFUND | PSP refund succeeded, state = EXECUTED | 1 |

## Per-event `data` schemas

### 1. `reservation.created`

```json
{
  "reservation_id": "…",
  "user_sub": "…",
  "offer_id": "…",
  "product_kind": "FLIGHT | ROOM | BUNDLE",
  "total_price": { "amount": "199.00", "currency": "USD" },
  "hold_id": "…",
  "hold_expires_at": "2026-09-01T18:27:03Z"
}
```

### 2. `hold.expired`

```json
{
  "reservation_id": "…",
  "hold_id": "…",
  "expired_at": "2026-09-01T18:27:03Z"
}
```

### 3. `payment.authorized`

```json
{
  "reservation_id": "…",
  "payment_id": "…",
  "amount": { "amount": "199.00", "currency": "USD" },
  "psp_auth_ref": "…"
}
```

### 4. `payment.failed`

```json
{
  "reservation_id": "…",
  "payment_id": "…",
  "reason": "TIMEOUT | DECLINED | GATEWAY_ERROR",
  "terminal_state": "CANCELLED_PAYMENT_FAILED"
}
```

### 5. `booking.confirmed`

```json
{
  "reservation_id": "…",
  "payment_id": "…",
  "psp_capture_ref": "…",
  "product_kind": "FLIGHT | ROOM | BUNDLE",
  "confirmed_at": "2026-09-01T18:12:04Z"
}
```

### 6. `cancellation.completed`

```json
{
  "reservation_id": "…",
  "terminal_state": "CANCELLED_USER | CANCELLED_HOLD_EXPIRED | CANCELLED_PAYMENT_FAILED",
  "reason": "…"
}
```

### 7. `refund.requested`

```json
{
  "refund_id": "…",
  "reservation_id": "…",
  "payment_id": "…",
  "amount": { "amount": "199.00", "currency": "USD" },
  "policy_code": "ROOM_48H_FULL | ROOM_48H_ZERO | FLIGHT_PROVIDER_TERMS | DISCRETIONARY",
  "requested_by_sub": "…",
  "reason": "…"
}
```

### 8. `refund.approved`

```json
{
  "refund_id": "…",
  "reservation_id": "…",
  "approved_by_sub": "…",     // MUST differ from requested_by_sub
  "approved_at": "2026-09-01T18:20:00Z"
}
```

### 9. `refund.executed`

```json
{
  "refund_id": "…",
  "reservation_id": "…",
  "psp_refund_ref": "…",
  "executed_at": "2026-09-01T18:20:04Z"
}
```

## Non-goals for v1

- Public event schema registry (Avro/Protobuf). JSON with `schema_version` is sufficient
  for v1; consumers are internal.
- Cross-region ordering. Single-region only for v1.
- Fan-out to multiple broker technologies. Only Redis Streams for v1 (see ADR-0001).
