# Phase 0 — Research

**Feature**: Reservation & Booking Orchestrator
**Branch**: `001-reservation-orchestrator`
**Date**: 2026-09-01

This document consolidates the design research needed to unblock Phase 1. There are **zero
remaining `NEEDS CLARIFICATION` markers** — every Technical Context entry in `plan.md` is
resolved.

Each entry follows the format: **Decision → Rationale → Alternatives considered**.

---

## R1. SQLite as system of record under an async FastAPI stack

- **Decision**: Use aiosqlite + SQLAlchemy 2.x async with `journal_mode=WAL`,
  `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`, and an **application-level
  single-writer lock** (`asyncio.Lock`) around all write transactions.
- **Rationale**: WAL allows concurrent readers with a single writer; the app-level lock
  guarantees deterministic serialization inside a single process, avoiding `SQLITE_BUSY`
  under our v1 target of ~10 rps writes. Transactions are kept ≤ 50 ms.
- **Alternatives considered**:
  - *One writer OS process, N readers*: adds IPC complexity and process supervision
    without measurable gain at v1 scale.
  - *PostgreSQL*: excluded by constitution NFR §T-1 for v1.
  - *`journal_mode=DELETE`*: kills concurrency for readers; rejected.

## R2. Transactional outbox in SQLite

- **Decision**: `outbox_messages` table populated in the **same transaction** as the
  domain change. A background publisher (`workers/outbox_publisher.py`) polls unpublished
  rows in ID order, publishes to Redis Streams, then marks them `published_at`. Exponential
  backoff on publisher failure; poison-message quarantine after N attempts.
- **Rationale**: Guarantees at-least-once delivery with zero external dependency at write
  time; consumers are responsible for idempotency (via `event_id`).
- **Alternatives considered**:
  - *SQLite triggers to enqueue*: opaque behavior, harder to reason about; rejected.
  - *Change-data-capture from WAL*: no supported CDC tooling for aiosqlite; rejected.
  - *Direct publish from request handler*: violates atomicity — publish could happen after
    a rolled-back transaction. Rejected.

## R3. Broker choice — **ADR-0001**

- **Decision**: **Redis Streams** as the v1 broker consumed by the outbox publisher.
- **Rationale**: Redis is already required (search cache + hold-TTL twin); Streams offer
  consumer groups, at-least-once delivery, and durable append semantics that cover v1
  needs at 10 rps writes. Adding a second broker (RabbitMQ/Kafka) doubles ops surface
  with no measurable payoff at this scale.
- **Alternatives considered**:
  - *RabbitMQ*: mature, but adds an additional operational domain (Erlang cluster) for
    minimal gain at this scale.
  - *Kafka*: strong ordering and retention semantics we do not yet need; higher operational
    cost; rejected for v1.
- **Constitutional deviation**: Yes — constitution v1.2.0 names RabbitMQ or Kafka. This
  deviation is captured under Complexity Tracking in `plan.md` and revisited at the first
  quarterly review or when write throughput ≥ 100 rps sustained.

## R4. Hold expiry mechanism — **ADR-0002**

- **Decision**: **Hybrid** — a Redis key `hold:{id}` with TTL = 15 min plus a
  keyspace-notification listener (`__keyevent@0__:expired`) triggers the domain
  `Reservation.expire_hold()`; **AND** an APScheduler job runs every 10 s that scans
  `SELECT id FROM holds WHERE status='active' AND expires_at < now()` and expires any
  stragglers.
- **Rationale**: SC-003 requires release within TTL + 60 s. Redis alone can miss expiries
  after a restart; SQLite alone would need ~1 s polling to hit the SLA under high load.
  The two-path design gives defense-in-depth at trivial cost.
- **Alternatives considered**:
  - *Redis sorted-set poll*: simpler than notifications but needs a dedicated polling
    loop; superseded by the SQLite sweeper anyway.
  - *SQLite-only 1 s polling*: adds ~50k redundant queries per day for no benefit.

## R5. Idempotency store schema and dedup window

- **Decision**: `idempotency_records(key, request_hash, response_status, response_body,
  created_at, expires_at)` with `PRIMARY KEY (key)` and a 24-hour dedup window. Middleware
  checks the key; if present with a matching `request_hash`, replay the stored response;
  if present with a different hash, return `409 Conflict`.
- **Rationale**: Matches the constitution's contract; 24 h covers partner retry policies
  and human retry patterns without unbounded growth (nightly cleanup deletes expired rows).
- **Alternatives considered**:
  - *Response hash keyed by URL + body only (no client key)*: violates the
    `Idempotency-Key` contract; rejected.

## R6. Payment saga & compensation

- **Decision**: Two-step **authorize → capture** flow. The Payment subagent authorizes on
  `POST /pay`; the Orchestrator captures inside the confirm step; **timeouts** at either
  step transition the reservation to `CANCELLED_PAYMENT_FAILED` (per FR-015a) and release
  the hold. Compensation on capture failure = void authorization + release hold.
- **Rationale**: Separating authorize and capture matches PSP semantics and prevents
  double-charge on retries. Terminal `CANCELLED_PAYMENT_FAILED` gives partners a clear
  final state for retry logic.
- **Alternatives considered**:
  - *Single-step "sale"*: simpler but no clean compensation window; rejected.

## R7. Refund gate (Principle VI) — **ADR-0004**

- **Decision**: Enforce four-eyes in **`RefundApprovalService`** (application) and re-check
  in the **payment adapter** immediately before calling the PSP. The refund SM is:
  `REQUESTED → APPROVED → EXECUTED` with terminal `REVOKED` and `FAILED`. Approval must be
  by a different `sub` than the requester; both roles must carry the
  `payments:refund:approve` scope. The auto-refund allowlist is loaded from
  `config.refund_allowlist` and ships **empty**.
- **Rationale**: Defense in depth — the adapter's re-check makes it impossible for a bug
  in the service to bypass the gate. Immutable audit records emitted for every state
  transition. The state machine is required at **100% line + branch coverage** via
  `pytest -m refund_gate`.
- **Alternatives considered**:
  - *Enforce only in adapter*: gives less business visibility; rejected.
  - *Enforce only in service*: single point of failure; rejected.

## R8. OpenTelemetry instrumentation

- **Decision**: Auto-instrument FastAPI, httpx, SQLAlchemy, and redis. Custom spans for
  `Orchestrator.run_lifecycle`, `PricingEngine.evaluate`, and each subagent step.
  W3C `traceparent` propagated on all outbound HTTP calls and stamped on outbox rows so
  downstream consumers continue the trace.
- **Rationale**: Meets Principle V; per-request correlation without hand-rolling spans.
- **Alternatives considered**:
  - *Logs-only observability*: fails Principle V; rejected.

## R9. React SPA data-fetching + auth pattern

- **Decision**: **BFF cookies** for the first-party SPA. FastAPI issues an httpOnly,
  Secure, SameSite=Lax session cookie after OIDC login; the SPA calls the API with
  cookies. Partner clients use bearer JWTs (client-credentials flow).
- **Rationale**: Avoids storing access tokens in the browser (XSS-safer). Bearer JWTs
  remain available for partners and preserve stateless partner auth.
- **Alternatives considered**:
  - *Access token in `localStorage`*: XSS-hostile; rejected.
  - *In-memory tokens with refresh in httpOnly cookie*: viable but adds a refresh loop;
    deferred to a future iteration if partners request it.

## R10. Pricing engine determinism

- **Decision**: Rules applied in a fixed pipeline order **base → seasonal → surge → LOS →
  loyalty tier**, each producing a `Decimal` delta. Ties broken by rule ID. All arithmetic
  in `Decimal` with `ROUND_HALF_EVEN` and `quantize` to 2 dp for USD.
- **Rationale**: Determinism is testable and reproducible in property-based tests.
- **Alternatives considered**:
  - *Percentage-only stacking*: loses precision across many rules; rejected.
  - *Float arithmetic*: banned by constitution NFR §M-1.

## R11. Frontend testing strategy

- **Decision**: Vitest for pure logic + component tests; Playwright for the P1 happy path
  and refund-approver flow; axe-core assertions in the E2E tier for a11y. Contract tests
  regenerate the OpenAPI TypeScript client on every CI run and fail if the diff is
  non-empty without a matching change in `contracts/openapi.yaml`.
- **Rationale**: Keeps the API and UI contracts in lockstep and enforces a11y.
- **Alternatives considered**:
  - *Cypress*: viable but slower CI cold-start than Playwright; rejected.

## R12. Auth choice for local dev — **ADR-0003**

- **Decision**: **Keycloak** container in dev/CI for OIDC; production expects an external
  IdP (issuer URL + JWKS via config). Scopes `reservations:write` and
  `payments:refund:approve` are declared on the Keycloak client and validated in the API
  middleware. Refund approvers must additionally hold a role/claim distinct from the
  requester's subject.
- **Rationale**: Keeps dev parity with production auth flow; avoids embedding an IdP in
  the app.
- **Alternatives considered**:
  - *Static bearer tokens in dev*: hides real OIDC edge cases; rejected.

---

## Summary of ADRs referenced by `plan.md`

- **ADR-0001** — Redis Streams as v1 broker (see R3).
- **ADR-0002** — Hybrid hold expiry (Redis TTL twin + 10 s SQLite sweeper) (see R4).
- **ADR-0003** — Keycloak in dev for OIDC (see R12).
- **ADR-0004** — Refund gate defense-in-depth (see R7).
