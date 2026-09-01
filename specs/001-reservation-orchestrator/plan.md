# Implementation Plan: Reservation & Booking Orchestrator (Hold → Pay → Confirm → Cancel)

**Branch**: `001-reservation-orchestrator` | **Date**: 2026-09-01 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-reservation-orchestrator/spec.md`

> **Constitution alignment note**: This plan was originally written against
> constitution v1.2.0, which listed only RabbitMQ/Kafka as brokers. After the
> `/speckit-analyze` cross-artifact review, the constitution was amended to
> **v1.3.0** to (a) admit Redis Streams as a broker for v1-scale deployments
> (≤ 100 rps sustained writes) and (b) require the idempotency dedup store to
> be co-located transactionally with the domain write. Both prior deviations
> in this plan are therefore no longer deviations — they are the sanctioned
> defaults. Deviation D1 below is retained as historical context and a
> re-evaluation trigger.

## Summary

Deliver a modular-monolith FastAPI service that lets guests search flights and rooms, receive
deterministically priced offers, place a 15-minute hold, pay, confirm, and cancel — with a
human-gated refund path. A single in-process **Orchestrator** drives the `hold → pay → confirm
→ cancel` saga and delegates work to three subagents (**Pricing**, **Booking**, **Payment**)
behind Protocol ports. SQLite (WAL) is the system of record; Redis serves as the search-result
cache and the hold-TTL twin; a transactional outbox in SQLite feeds a Redis Streams publisher.
Human-gated refunds enforce four-eyes at the domain layer with a fail-closed payment adapter.
The first-party UI is a React 18 SPA (TypeScript strict, TanStack Query, React Hook Form + Zod,
Tailwind). All decisions align with constitution v1.2.0; the single justified deviation is the
broker choice (Redis Streams instead of RabbitMQ/Kafka for v1) — see Complexity Tracking below
and ADR-0001 in [research.md](./research.md).

## Technical Context

**Language/Version**: Python 3.12+ (asyncio end-to-end); TypeScript 5+ (strict) for the SPA.

**Primary Dependencies**: FastAPI, Pydantic v2, SQLAlchemy 2.x async, Alembic, aiosqlite,
redis-py (async), httpx, structlog, OpenTelemetry SDK, prometheus-client, APScheduler,
authlib (OIDC), pytest + pytest-asyncio, respx, testcontainers, schemathesis. Frontend:
React 18, Vite, TanStack Query, React Router (data router), React Hook Form + Zod, Tailwind,
`openapi-typescript`, Vitest, React Testing Library, Playwright, axe-core.

**Storage**: SQLite (aiosqlite) as system of record with WAL journal mode, `PRAGMA
foreign_keys=ON`, and application-level single-writer discipline. Redis 7+ for search
result cache (short TTL) and hold-TTL twin (keyspace-notification-driven expiry). Alembic
manages migrations; all migrations reversible.

**Testing**: pytest + pytest-asyncio (unit, integration, contract, refund_gate, e2e), respx
for HTTP stubs, testcontainers for ephemeral Redis; Vitest + React Testing Library
(frontend unit/component); Playwright + axe-core (frontend E2E + a11y); k6 (load smoke).

**Target Platform**: Linux server (x86_64), containerized on `python:3.12-slim` as a
non-root user; v1 deployment via `docker-compose` (Kubernetes deferred). Frontend served
as a static build via a lightweight nginx sidecar.

**Project Type**: Web service + SPA (two deployable artifacts in one repo).

**Performance Goals**:
- Search API p95 < 300 ms (aligns with SC-001 "first quote in ≤ 800 ms" including client render).
- Hold → Pay → Confirm orchestration p95 < 500 ms, excluding provider latency.
- Sustain 200 rps peak, 50 rps sustained on search; 10 rps sustained on write paths.
- Frontend LCP < 2.5 s on 4G mid-tier; reservation-flow JS bundle < 250 KB gzipped.

**Constraints**:
- SQLite single-writer: all mutations serialize through one async writer path (per-database
  `asyncio.Lock`); long transactions prohibited.
- All money in `decimal.Decimal` with explicit ISO-4217 currency; USD only in v1.
- All timestamps timezone-aware UTC internally; property-local time used only for the
  FR-018a 48-hour room cancellation cutoff.
- No blocking I/O on the event loop; CPU-bound work offloaded via `asyncio.to_thread`.
- Availability target 99.9% (single-region v1); RPO ≤ 5 min via SQLite WAL backups.

**Scale/Scope**: v1 target ~10k active reservations, single tenant, USD only, ~200 rps
peak. Refund approval queue expected to remain in the low hundreds per day; UI optimized
for reviewability, not throughput.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Requirement | Plan alignment | Status |
|---|---|---|---|
| I. API-First & Contract-Driven Design | OpenAPI 3.1 contract merged before implementation; Pydantic v2 as single source of truth. | Phase 1 emits `contracts/openapi.yaml` first; FastAPI routes bind Pydantic v2 models; frontend client generated via `openapi-typescript`. | **PASS** |
| II. Modular Domain Boundaries (Hexagonal) | Bounded contexts; adapters isolate I/O; domain/application framework-agnostic. | `src/domain/` and `src/application/` forbidden from importing FastAPI/SQLAlchemy/redis/httpx (enforced by `import-linter` in CI). `src/ports/` holds Protocols; `src/adapters/{persistence,providers,broker,cache,identity}` isolate all I/O. | **PASS** |
| III. Test-First Development (NON-NEGOTIABLE) | TDD; unit ≥ 90% target / 85% hard floor in domain & application; contract, integration, E2E, and refund-gate tiers required. | tasks.md (next phase) orders tests before implementation; refund state machine required at 100% line + branch; CI enforces all floors. | **PASS** |
| IV. Async-by-Default & Idempotent Orchestration | Async I/O; sagas; `Idempotency-Key`; transactional outbox; retries + circuit breaker. | Full asyncio stack; `Orchestrator.run_lifecycle()` implements sagas with compensations; `IdempotencyStorePort` persisted transactionally in SQLite (per constitution v1.3.0 dedup-atomicity rule); outbox table + Redis Streams publisher (broker admitted by v1.3.0). | **PASS** |
| V. Observability, Security & Operational Readiness | structlog JSON, OTel tracing, Prometheus RED + business metrics, `/livez`+`/readyz`, OAuth 2.1/OIDC, secrets manager, TLS 1.3. | `observability/` (logging, tracing, metrics) plus `middleware/` (correlation-id, auth, idempotency, errors); `pydantic-settings` with optional Vault; TLS terminated at ingress. | **PASS** |
| VI. Human-in-the-Loop Refund Gate (NON-NEGOTIABLE) | Four-eyes, fail-closed adapter, immutable audit, auto-refund allowlist empty at launch, 100% coverage on state machine, `pytest -m refund_gate` in CI. | `RefundApprovalService` enforces four-eyes in the domain layer; payment adapter re-verifies approval inside the same DB transaction that reserves the outbox event; allowlist ships empty; `refund_gate` marker registered in `pyproject.toml`. | **PASS** |

### Justified Deviations

**D1 — Broker choice (historical, now sanctioned by constitution v1.3.0)**.
The original plan (against constitution v1.2.0) treated Redis Streams as a
deviation from the RabbitMQ/Kafka-only rule. Constitution v1.3.0 explicitly
admits Redis Streams for v1-scale deployments (≤ 100 rps sustained writes),
so this is no longer a deviation. Retained here as a **re-evaluation trigger**:
write throughput ≥ 100 rps sustained MUST open an ADR proposing a successor
broker at the next quarterly architecture review.

## Project Structure

### Documentation (this feature)

```text
specs/001-reservation-orchestrator/
├── plan.md                  # This file (/speckit-plan output)
├── research.md              # Phase 0 output
├── data-model.md            # Phase 1 output
├── quickstart.md            # Phase 1 output
├── contracts/
│   ├── openapi.yaml         # HTTP contract (OpenAPI 3.1)
│   └── events.md            # Domain event schemas
├── checklists/
│   └── requirements.md      # From /speckit-specify
└── tasks.md                 # /speckit-tasks output (not created by /speckit-plan)
```

### Source Code (repository root)

```text
src/
├── api/                     # FastAPI routers (thin; delegate to application services)
│   ├── deps.py              # Auth, correlation-id, idempotency-key dependencies
│   ├── search.py            # POST /search
│   ├── reservations.py      # POST /reservations, /pay, /confirm, /cancel, GET /reservations/{id}
│   └── refunds.py           # POST /reservations/{id}/refunds, /refunds/{id}/approve, /revoke, GET /refunds
├── application/             # Use cases; framework-agnostic
│   ├── search_service.py
│   ├── pricing_subagent.py
│   ├── booking_subagent.py
│   ├── payment_subagent.py
│   ├── orchestrator.py      # Saga runner with compensations
│   └── refund_approval_service.py
├── domain/                  # Pure Python — no framework imports
│   ├── entities/            # Reservation, Hold, Payment, Refund, Offer, AuditEvent, IdempotencyRecord, OutboxMessage, PricingRule
│   ├── value_objects/       # Money, IdempotencyKey, CorrelationId, PropertyLocalTime, OfferId, ReservationId
│   ├── policies/            # RoomCancellationPolicy (FR-018a), AutoRefundAllowlist (empty), FlightRefundPolicy (FR-018b)
│   ├── state_machines/      # ReservationSM, RefundSM (100% branch coverage)
│   └── pricing/             # PricingEngine rule pipeline (base → season → surge → LOS → tier)
├── ports/                   # Protocols (Ports for hexagonal boundary)
│   ├── pricing_port.py
│   ├── flight_inventory_port.py
│   ├── room_inventory_port.py
│   ├── payment_port.py
│   ├── notification_port.py
│   ├── clock_port.py
│   ├── outbox_port.py
│   ├── idempotency_store_port.py
│   └── refund_approval_port.py
├── adapters/
│   ├── persistence/         # SQLAlchemy 2.x async
│   │   ├── models/          # ORM models mapped from domain entities
│   │   ├── repositories/    # ReservationRepo, HoldRepo, PaymentRepo, RefundRepo, OutboxRepo, IdempotencyRepo, AuditRepo
│   │   ├── writer.py        # Single-writer lock (asyncio.Lock) + WAL settings
│   │   └── alembic/         # Reversible migrations
│   ├── providers/
│   │   ├── flight_stub.py   # Configurable latency & fault injection
│   │   ├── room_stub.py
│   │   ├── payment_stub.py  # Injectable timeout for FR-015a
│   │   └── notify_stub.py
│   ├── broker/
│   │   ├── redis_streams_publisher.py
│   │   └── redis_streams_consumer.py
│   ├── cache/
│   │   ├── redis_client.py
│   │   └── hold_ttl_twin.py # Keyspace-notification-driven expiry signaller
│   └── identity/
│       ├── oidc_verifier.py
│       └── scopes.py        # reservations:write, payments:refund:approve
├── workers/
│   ├── outbox_publisher.py  # Reads outbox → publishes to Redis Streams
│   └── hold_expiry_sweeper.py # APScheduler 10-second backup for Redis TTL twin
├── middleware/
│   ├── correlation_id.py
│   ├── auth.py
│   ├── idempotency.py
│   └── errors.py
├── config/
│   └── settings.py          # pydantic-settings (env + optional Vault)
├── observability/
│   ├── logging.py           # structlog JSON config
│   ├── tracing.py           # OpenTelemetry setup + traceparent propagation
│   └── metrics.py           # Prometheus registry + RED helpers + business counters
└── main.py                  # FastAPI app factory + lifespan (start workers, wire adapters)

frontend/
├── src/
│   ├── routes/              # Search, OfferDetail, Payment, Confirmation, History, RefundApproval
│   ├── components/
│   ├── api/                 # Generated types (openapi-typescript) + typed fetch wrapper
│   ├── hooks/               # useHoldTimer, useIdempotencyKey, useAuth
│   ├── forms/               # RHF + Zod schemas mirroring OpenAPI
│   └── styles/              # Tailwind config
├── tests/
│   ├── unit/                # Vitest + React Testing Library
│   └── e2e/                 # Playwright + axe-core
└── vite.config.ts

tests/
├── unit/                    # domain + application (mock only at ports)
├── integration/             # adapters via testcontainers Redis + on-disk SQLite
├── contract/                # OpenAPI round-trip (schemathesis) + JSON Schema for events
├── e2e/                     # Chaos: provider outage, payment timeout → CANCELLED_PAYMENT_FAILED
├── refund_gate/             # pytest -m refund_gate (Principle VI)
└── load/                    # k6 scripts: search, hold→pay→confirm
```

**Structure Decision**: **Modular monolith** with one Python package under `src/` and a
sibling `frontend/` package. Bounded contexts are enforced by an `import-linter` contract
that forbids `domain/*` and `application/*` from importing FastAPI, SQLAlchemy, redis,
httpx, or any adapter module. The two deployables (backend image and frontend static
bundle) are built from this single repo and orchestrated via `docker-compose` in dev/CI;
production topology (Kubernetes) is deferred beyond v1.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| Redis Streams as v1 broker (constitution names RabbitMQ/Kafka) | Redis already required for cache + hold-TTL twin; adding a second broker doubles ops surface without benefit at v1 scale (10 rps writes). Outbox pattern preserved; broker is a swappable adapter. | RabbitMQ/Kafka at v1: higher operational cost, no measurable improvement in durability for our scale. Revisit at ≥ 100 rps writes. |
| Hybrid hold expiry (Redis TTL twin + 10 s SQLite sweeper) | SC-003 requires release within TTL + 60 s. Redis alone risks loss on restart; SQLite alone would need ~1 s polling to hit SLA. Two paths give defense-in-depth at minimal cost. | Redis-only: expiry lost on restart. SQLite-only 1 s polling: excessive DB pressure. |

## Post-Design Constitution Re-Check

Re-evaluated after Phase 1 artifacts written:

- **I. API-First**: PASS — `contracts/openapi.yaml` covers every state-changing endpoint;
  Pydantic v2 models will be generated from it; frontend client generated too.
- **II. Hexagonal**: PASS — `data-model.md` describes domain entities free of ORM concerns;
  adapters listed in `Project Structure` isolate all I/O; `import-linter` will enforce
  boundaries in CI.
- **III. Test-First**: PASS (planned) — Phase 2 (`/speckit-tasks`) will emit tests-before-code
  ordering with the coverage tiers from the constitution.
- **IV. Async + Idempotent + Outbox**: PASS — outbox pattern preserved end-to-end;
  broker choice (Redis Streams) and dedup-store locality (SQLite) both align with
  constitution v1.3.0.
- **V. Observability & Security**: PASS — logging/tracing/metrics + OIDC scopes documented
  in structure; `/livez` and `/readyz` endpoints listed in `openapi.yaml`.
- **VI. Refund Gate**: PASS — refund state machine, four-eyes rule, immutable audit, and
  empty auto-refund allowlist reflected in `data-model.md` and `openapi.yaml`.

**Gate result**: **GREEN** — ready for `/speckit-tasks`.
