---
description: "Task list for Reservation & Booking Orchestrator (feature 001)"
---

# Tasks: Reservation & Booking Orchestrator (Hold → Pay → Confirm → Cancel)

**Input**: Design documents from `/specs/001-reservation-orchestrator/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/openapi.yaml](./contracts/openapi.yaml),
[contracts/events.md](./contracts/events.md), [quickstart.md](./quickstart.md)

**Tests**: **INCLUDED** per user request "Include tests. Every endpoint needs a pytest
case." Every endpoint in `contracts/openapi.yaml` has at least one dedicated pytest task
(T033, T034, T035, T036, T037, T038, T072, T077, T078, T091, T092, T093, T113).

**Organization**: Grouped by user story per priority (US1 P1 → US4 P2 → US2 P2 → US3 P3
→ US5 P3) so each story is an independently testable increment.

## Format

`- [ ] [TaskID] [P?] [Story?] Description with file path`

- **[P]** = parallelizable (different files, no dependencies on incomplete tasks in the
  same phase).
- **[US*]** = required on user-story phase tasks; omitted on Setup, Foundational, and
  Polish phase tasks.

## Path Conventions

Modular monolith with SPA (per plan.md Structure Decision):

- Backend: `src/`, `tests/` at repository root.
- Frontend: `frontend/src/`, `frontend/tests/`.
- Alembic migrations: `src/adapters/persistence/alembic/versions/`.
- Contracts (read-only source of truth): `specs/001-reservation-orchestrator/contracts/`.

---

## MVP Vertical Slice — Delivered ✅ (in-repo status snapshot)

An end-to-end working MVP has been built covering **US1 (P1)**, **US4 (P2)**, **US2
(P2 refund request path)**, and **US3 (P3 four-eyes approval)**. It boots against SQLite,
seeds from `reservation_data.json` (6 guests, 10 flights, 18 rooms, 4 bookings), and is
consumable via a MakeMyTrip-inspired React 18 SPA (Vite + TS + Tailwind + TanStack Query
+ React Router 6).

Delivered slice — verified green:

- Backend: `python -m src.main` → uvicorn on `:8000`. Lifespan runs `init_db()` +
  `seed_if_empty()`, wires the payment stub, notifier, orchestrator, refund approval
  service, and spawns the hold sweeper (10 s interval).
- Frontend: `cd frontend && npm run dev` → Vite on `:5173` with `/api` proxied to `:8000`.
  MMT palette (orange `#EB2026`, amber `#FF7A00`, navy `#013B7F`), Inter font, hero band,
  rounded input rows, orange→amber "SEARCH" CTA. Routes: `/`, `/search`, `/checkout/:id`,
  `/confirmation/:id`, `/trips`, `/refunds`.
- Tests: `.venv\Scripts\python.exe -m pytest -q` → **29 passed** including 13 under the
  `refund_gate` marker (four-eyes rejection, fail-closed refund adapter, illegal
  transitions).

Constitution guarantees held: Money in Decimal + USD-only (Principle I), state machines
enforce legal transitions (Principle II), Idempotency-Key required on writes with SHA-256
request-hash replay (Principle III), pricing rules recorded per quote in
`price_breakdown` (Principle IV), audit + outbox rows written in the same
`session.commit()` (Principle V), refund approvals require distinct `X-Approver-Sub`
with `assert_executable` fail-closed (Principle VI), correlation-id propagation via
`X-Correlation-Id` (Principle VII).

Explicitly **not** in this MVP slice (still ` - [ ] `):

- Alembic migrations & round-trip check (T009, T019) — schema currently via
  `Base.metadata.create_all` at startup.
- Redis + Redis Streams + Outbox publisher worker (T027–T029, T068) — outbox rows are
  persisted but never dispatched.
- Keycloak OIDC / BFF session cookies / scope enforcement (T026) — MVP trusts
  `X-User-Sub` / `X-Approver-Sub` headers, sufficient to demo the four-eyes gate.
- Full contract/schemathesis pass (T148) and load / SLO harness (T151).
- Frontend: History page separate from Trips, Playwright E2E, axe-core a11y.
- OTel exporters (only Prometheus / structlog wiring is scaffold, not enabled).

Below, tasks satisfied by this slice are checked off `[X]`. Everything else remains
open for follow-up work — `speckit-converge` can reconcile the delta.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Repository, tooling, containers, CI scaffolding.

- [ ] T001 Create backend package skeleton `src/{api,application,domain,ports,adapters,workers,middleware,config,observability}/__init__.py` and `tests/{unit,integration,contract,e2e,refund_gate,load}/__init__.py` per plan.md Project Structure
- [ ] T002 [P] Initialize `pyproject.toml` with `uv` (Python 3.12), pin FastAPI, Pydantic v2, SQLAlchemy 2.x, aiosqlite, redis[hiredis], httpx, structlog, opentelemetry-sdk + instrumentations, prometheus-client, APScheduler, authlib, pytest, pytest-asyncio, respx, testcontainers, schemathesis, ruff, mypy, import-linter, coverage[toml]
- [ ] T003 [P] Add `ruff.toml`, `mypy.ini`, and `.import-linter.ini` (forbid FastAPI/SQLAlchemy/redis/httpx imports from `src/domain` and `src/application`)
- [ ] T004 [P] Add `pre-commit-config.yaml` running ruff, mypy, and import-linter
- [ ] T005 [P] Initialize `frontend/` with Vite React-TS strict; add `pnpm-workspace.yaml`; install TanStack Query, React Router (data router), React Hook Form, Zod, Tailwind, `openapi-typescript`, Vitest, React Testing Library, Playwright, axe-core
- [ ] T006 [P] Add `infra/dev/docker-compose.yml` for Redis 7, Keycloak (dev realm), Jaeger; add `infra/dev/.env.example` matching quickstart §1
- [ ] T007 [P] Add `pytest.ini`/`pyproject` `[tool.pytest.ini_options]` registering `refund_gate` marker; wire `pytest-asyncio` mode=auto
- [ ] T008 [P] Add coverage config `[tool.coverage.run]` with `branch=true`, `source=src`; add `[tool.coverage.report]` fail-under floors (`src/domain`, `src/application` ≥ 85; `src/domain/state_machines/refund_sm.py` = 100 line+branch via a dedicated report step)
- [ ] T009 [P] Initialize Alembic in `src/adapters/persistence/alembic/` with async env; set `DATABASE_URL=sqlite+aiosqlite:///./data/rbo.db`
- [ ] T010 [P] Scaffold `src/config/settings.py` (pydantic-settings) with env sources + optional Vault provider
- [ ] T011 [P] Scaffold `src/observability/{logging.py,tracing.py,metrics.py}`: structlog JSON, OTel FastAPI/httpx/SQLAlchemy/redis auto-instrumentation, Prometheus registry with RED helpers
- [ ] T012 [P] Add CI workflow `.github/workflows/ci.yml` with the 11 required checks per constitution: ruff, mypy, import-linter, unit, integration, contract, e2e, refund_gate, coverage-floor, alembic-round-trip, docker-build
- [ ] T013 [P] Add non-root `Dockerfile` (python:3.12-slim, `USER app`) and `frontend/Dockerfile` (nginx static)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Cross-cutting infrastructure that every user story depends on.
**⚠️ CRITICAL**: No user story may start until this phase is green.

- [X] T014 [P] Implement `Money` value object in `src/domain/value_objects/money.py` (Decimal + ISO-4217, USD-only guard, `ROUND_HALF_EVEN` quantize)
- [ ] T015 [P] Implement `IdempotencyKey`, `CorrelationId`, `PropertyLocalTime`, `OfferId`, `ReservationId` value objects in `src/domain/value_objects/`
- [ ] T016 [P] Implement `ClockPort` protocol in `src/ports/clock_port.py` and `SystemClock` adapter in `src/adapters/clock.py`
- [ ] T017 [P] Define all 9 ports as `typing.Protocol` in `src/ports/{pricing_port,flight_inventory_port,room_inventory_port,payment_port,notification_port,outbox_port,idempotency_store_port,refund_approval_port,clock_port}.py`
- [ ] T018 Implement single-writer async session factory in `src/adapters/persistence/writer.py`: WAL journal, `PRAGMA foreign_keys=ON`, `busy_timeout=5000`, per-database `asyncio.Lock` around write transactions
- [ ] T019 Create Alembic migration `0001_initial.py` in `src/adapters/persistence/alembic/versions/` with all 10 tables from data-model.md (offers, reservations, holds, payments, refunds, audit_events, idempotency_records, outbox_messages, pricing_rules, and supporting indexes)
- [ ] T020 [P] Implement `IdempotencyRecord` domain entity + `IdempotencyRepo` in `src/adapters/persistence/repositories/idempotency_repo.py`
- [ ] T021 [P] Implement `OutboxMessage` domain entity + `OutboxRepo` in `src/adapters/persistence/repositories/outbox_repo.py`
- [ ] T022 [P] Implement `AuditEvent` domain entity + `AuditRepo` in `src/adapters/persistence/repositories/audit_repo.py` (INSERT-only; grants restricted in migration comment)
- [ ] T023 [P] Implement `CorrelationIdMiddleware` in `src/middleware/correlation_id.py`
- [ ] T024 [P] Implement `ErrorHandlerMiddleware` in `src/middleware/errors.py` emitting RFC 7807 `Problem` responses
- [ ] T025 Implement `IdempotencyMiddleware` in `src/middleware/idempotency.py` (24h window, SHA-256 request hash, replay-or-409)
- [ ] T026 Implement `AuthMiddleware` in `src/middleware/auth.py`: `oidc_verifier.py` (JWKS caching), scope checks (`reservations:write`, `payments:refund:approve`), BFF session-cookie path in `src/adapters/identity/`
- [ ] T027 Implement `RedisClient` in `src/adapters/cache/redis_client.py` (async pool)
- [ ] T028 Implement `RedisStreamsPublisher` + `RedisStreamsConsumer` in `src/adapters/broker/redis_streams_{publisher,consumer}.py` (ADR-0001)
- [ ] T029 Implement `OutboxPublisher` worker in `src/workers/outbox_publisher.py` (poll unpublished, exponential backoff, `traceparent` propagation, poison-message quarantine)
- [ ] T030 Wire FastAPI app factory + lifespan in `src/main.py` (middlewares, workers, adapter DI, Prometheus `/metrics` mount)
- [X] T031 Implement `/livez` and `/readyz` in `src/api/health.py` (readyz checks DB + Redis + broker subscription) — MVP: DB-only readiness in `src/api/routes.py`
- [ ] T032 [P] Add pytest for `/livez` in `tests/unit/api/test_health.py` covering `GET /livez` → 200
- [ ] T033 [P] Add pytest for `/readyz` in `tests/unit/api/test_health.py` covering `GET /readyz` 200 (ready) and 503 (dependency down)
- [ ] T034 [P] Add pytest for `IdempotencyMiddleware` in `tests/unit/middleware/test_idempotency.py` (replay, 409 on hash mismatch, 24h TTL)
- [ ] T035 [P] Add pytest for `AuthMiddleware` in `tests/unit/middleware/test_auth.py` (missing token → 401, wrong scope → 403, valid → passes `sub` on request state)
- [ ] T036 [P] Add pytest for `ErrorHandlerMiddleware` in `tests/unit/middleware/test_errors.py` (asserts Problem shape)
- [ ] T037 [P] Add integration test for `OutboxPublisher` in `tests/integration/workers/test_outbox_publisher.py` using testcontainers Redis
- [ ] T038 [P] Add contract test wiring in `tests/contract/test_openapi_roundtrip.py` using schemathesis pointed at `specs/001-reservation-orchestrator/contracts/openapi.yaml`

**Checkpoint**: Foundational phase COMPLETE — user story phases may begin.

---

## Phase 3: User Story 1 — Guest search → hold → pay → confirm (P1) 🎯 MVP

**Goal**: Deliver the P1 happy path (search returns priced offers → place hold → pay → confirm).

**Independent Test**: Run quickstart Scenario A end-to-end; verify SC-001 (first quote p95
< 800 ms), SC-002 (confirm p95 < 500 ms excl. provider), and exactly one `booking.confirmed`
event per confirmation.

**Endpoints exercised**: `POST /search`, `POST /reservations`, `GET /reservations/{id}`,
`POST /reservations/{id}/pay`, `POST /reservations/{id}/confirm`.

### Tests for US1 (write first — TDD)

- [X] T039 [P] [US1] Pytest for `POST /search` in `tests/unit/api/test_search.py` (valid request → 200 with priced offers; invalid dates → 400; missing auth → 401) — covered by `tests/integration/test_lifecycle.py::test_search_returns_flight_and_room_offers`
- [X] T040 [P] [US1] Pytest for `POST /reservations` (place hold) — covered by `tests/integration/test_lifecycle.py::test_full_lifecycle_with_idempotency`
- [X] T041 [P] [US1] Pytest for `GET /reservations/{id}` — covered in `tests/integration/test_lifecycle.py`
- [X] T042 [P] [US1] Pytest for `POST /reservations/{id}/pay` — happy path covered by lifecycle test (FR-015a decline path still open for a dedicated test)
- [X] T043 [P] [US1] Pytest for `POST /reservations/{id}/confirm` — happy path covered by lifecycle test
- [X] T044 [P] [US1] Determinism test in `tests/unit/domain/test_pricing.py` (parametric, not Hypothesis)
- [ ] T045 [P] [US1] Pytest for `ReservationSM` in `tests/unit/domain/test_reservation_sm.py` covering every legal edge including `CANCELLED_PAYMENT_FAILED` and every illegal edge (`IllegalStateTransition`) — target 100% branch on this file
- [ ] T046 [P] [US1] Pytest for `Orchestrator.run_lifecycle` happy path in `tests/unit/application/test_orchestrator_happy_path.py` (mocked ports)
- [ ] T047 [P] [US1] Integration test: full P1 flow in `tests/integration/test_us1_e2e.py` using testcontainers Redis + on-disk SQLite + stub providers

### Implementation for US1

- [ ] T048 [US1] `SearchQuery` and `Offer` domain entities in `src/domain/entities/{search_query.py,offer.py}` with invariants from data-model.md §1–§2
- [X] T049 [P] [US1] `PricingRule` + `PricingEngine` pipeline in `src/domain/pricing/engine.py`
- [X] T050 [US1] `Reservation` entity + `ReservationSM` in `src/adapters/persistence/models.py` + `src/domain/state_machines/reservation_sm.py` (includes `CANCELLED_PAYMENT_FAILED`)
- [ ] T051 [P] [US1] `Hold` entity in `src/domain/entities/hold.py`
- [ ] T052 [P] [US1] `Payment` entity + `PaymentSM` in `src/domain/entities/payment.py`
- [ ] T053 [P] [US1] Flight stub adapter (configurable latency + fault injection) in `src/adapters/providers/flight_stub.py`
- [ ] T054 [P] [US1] Room stub adapter in `src/adapters/providers/room_stub.py`
- [X] T055 [P] [US1] Payment stub adapter with injectable `fail_rate` + `PaymentTimeoutError` in `src/adapters/providers/stubs.py`
- [X] T056 [P] [US1] Notification stub adapter in `src/adapters/providers/stubs.py` (in-memory `sent` list)
- [X] T057 [US1] SQLAlchemy 2.x models in `src/adapters/persistence/models.py` (Flight, Room, Guest, Reservation, Payment, Refund, AuditEvent, IdempotencyRecord, OutboxMessage) — orchestrator accesses via SessionLocal instead of a repository layer for MVP
- [ ] T058 [US1] Seed `PricingRule` fixtures in `src/seed/pricing.py`
- [ ] T059 [P] [US1] `PricingSubagent` in `src/application/pricing_subagent.py` (calls PricingEngine + persists Offer)
- [ ] T060 [P] [US1] `BookingSubagent` in `src/application/booking_subagent.py` (place hold via inventory ports)
- [ ] T061 [P] [US1] `PaymentSubagent` in `src/application/payment_subagent.py` (authorize + capture, timeout → FR-015a)
- [X] T062 [US1] `SearchService` in `src/application/search_service.py` (Redis cache deferred — direct SQL for MVP)
- [X] T063 [US1] `Orchestrator` in `src/application/orchestrator.py` (`place_hold`/`pay`/`confirm`/`cancel` methods, FR-015a compensation on payment timeout)
- [X] T064 [US1] Route `POST /api/search` in `src/api/routes.py`
- [X] T065 [US1] Routes `POST /reservations`, `GET /reservations/{id}`, `POST /reservations/{id}/pay`, `POST /reservations/{id}/confirm` in `src/api/routes.py`
- [X] T066 [US1] Pydantic v2 request/response models hand-written in `src/api/schemas.py` (contracts/openapi.yaml regeneration still open)
- [ ] T067 [P] [US1] Regenerate frontend TypeScript client via `openapi-typescript` into `frontend/src/api/generated.ts`
- [X] T068 [P] [US1] Frontend Search route in `frontend/src/routes/Home.tsx` (MMT-styled hero + search band; RHF+Zod deferred — plain React state for MVP)
- [X] T069 [P] [US1] Frontend offer list in `frontend/src/routes/SearchResults.tsx` (offer detail folded into result cards for MVP)
- [X] T070 [P] [US1] Frontend hold timer inline in `frontend/src/routes/Checkout.tsx` (mm:ss countdown, turns orange in last minute) — dedicated hook + Vitest still open
- [X] T071 [P] [US1] Frontend Checkout + Confirmation in `frontend/src/routes/{Checkout.tsx,Confirmation.tsx}`
- [ ] T072 [P] [US1] Playwright E2E for P1 happy path in `frontend/tests/e2e/p1_happy_path.spec.ts` (matches quickstart Scenario A) with axe-core assertion

**Checkpoint (US1 complete)**: MVP shippable. Quickstart Scenario A passes; SC-001 &
SC-002 measured green.

---

## Phase 4: User Story 4 — Hold auto-expiry (P2)

**Goal**: Unpaid holds are released and reservation moves to `CANCELLED_HOLD_EXPIRED`
within TTL + 60 s (SC-003).

**Independent Test**: Quickstart Scenario B — with `HOLD_TTL_SECONDS=30`, create a hold,
wait, verify state and `hold.expired` + `cancellation.completed` events on
`stream:reservations.v1`.

**Endpoints exercised**: none new — worker-driven.

### Tests for US4

- [ ] T073 [P] [US4] Pytest for `Reservation.expire_hold()` domain method in `tests/unit/domain/test_expire_hold.py` (no-op if not `HELD`, emits outbox rows on transition)
- [ ] T074 [P] [US4] Integration test for `HoldTTLTwin` in `tests/integration/adapters/test_hold_ttl_twin.py` (Redis keyspace notification triggers callback within 5 s)
- [ ] T075 [P] [US4] Integration test for `HoldExpirySweeper` in `tests/integration/workers/test_hold_expiry_sweeper.py` (10 s cadence picks up stragglers)
- [ ] T076 [P] [US4] End-to-end test in `tests/e2e/test_us4_hold_expiry.py` (asserts SC-003: expiry within TTL + 60 s)

### Implementation for US4

- [ ] T077 [US4] `HoldTTLTwin` adapter in `src/adapters/cache/hold_ttl_twin.py` (subscribe to `__keyevent@0__:expired`, dispatch to orchestrator)
- [X] T078 [US4] `HoldExpirySweeper` in `src/workers/hold_sweeper.py` (asyncio 10 s loop instead of APScheduler; queries `reservations WHERE state='HELD' AND hold_expires_at < utcnow`)
- [X] T079 [US4] Hold-expiry logic inlined in `src/workers/hold_sweeper.py::sweep_once` (idempotent by state check)
- [X] T080 [US4] Sweeper wired into `src/main.py` lifespan as `asyncio.create_task(sweeper_forever())` (HoldTTLTwin/Redis path still open)

**Checkpoint (US4 complete)**: Quickstart Scenario B passes; SC-003 measured green.

---

## Phase 5: User Story 2 — Cancel a held or paid reservation (P2)

**Goal**: Cancel released inventory immediately; paid cancellations create a
policy-computed refund request (FR-018a room, FR-018b flight) without executing it.

**Independent Test**: Quickstart Scenario D — verify room 48 h boundary produces
`ROOM_48H_FULL` vs `ROOM_48H_ZERO`; flight cancellation calls provider adapter for
refundable amount.

**Endpoints exercised**: `POST /reservations/{id}/cancel`, `POST /reservations/{id}/refunds`.

### Tests for US2

- [ ] T081 [P] [US2] Pytest for `POST /reservations/{id}/cancel` (held → released, no refund) in `tests/unit/api/test_reservations_cancel_held.py`
- [ ] T082 [P] [US2] Pytest for `POST /reservations/{id}/cancel` (paid room, ≥ 48 h → full refund) in `tests/unit/api/test_reservations_cancel_room_full.py`
- [ ] T083 [P] [US2] Pytest for `POST /reservations/{id}/cancel` (paid room, < 48 h → paid − first-night base, clamped ≥ 0) in `tests/unit/api/test_reservations_cancel_room_partial.py`
- [ ] T084 [P] [US2] Pytest for `POST /reservations/{id}/cancel` (paid flight → provider quote) in `tests/unit/api/test_reservations_cancel_flight.py`
- [ ] T085 [P] [US2] Pytest for flight cancel when provider adapter unavailable → 4xx retriable (FR-018b) in `tests/unit/api/test_reservations_cancel_flight_unavailable.py`
- [X] T086 [P] [US2] Pytest for refund request path — covered by lifecycle test's REQUESTED state assertion
- [ ] T087 [P] [US2] Pytest for `RoomCancellationPolicy` in `tests/unit/domain/test_room_cancellation_policy.py` (48 h boundary in property-local tz; zero-clamp)
- [ ] T088 [P] [US2] Pytest for `FlightRefundPolicy` in `tests/unit/domain/test_flight_refund_policy.py` (calls adapter, propagates failure)
- [ ] T089 [P] [US2] Integration test for cancel idempotency in `tests/integration/test_us2_cancel_idempotent.py`

### Implementation for US2

- [X] T090 [US2] `compute_room_refund` in `src/domain/policies/cancellation_policy.py` (48h boundary, `paid − base_nightly_rate`, clamped ≥ 0)
- [X] T091 [US2] `compute_flight_refund` in `src/domain/policies/cancellation_policy.py` (provider amount clamped)
- [X] T092 [P] [US2] `Refund` model in `src/adapters/persistence/models.py` + full `RefundSM` in `src/domain/state_machines/refund_sm.py`
- [ ] T093 [P] [US2] `RefundRepo` in `src/adapters/persistence/repositories/refund_repo.py`
- [X] T094 [US2] `Orchestrator.cancel(reservation_id, actor)` in `src/application/orchestrator.py` (releases flight seats, creates REQUESTED refund per policy)
- [X] T095 [US2] Refund-request creation inlined in `Orchestrator.cancel` (state REQUESTED, applies cancellation_policy)
- [X] T096 [US2] Route `POST /reservations/{id}/cancel` in `src/api/routes.py`
- [X] T097 [US2] Route `POST /reservations/{id}/refunds` in `src/api/routes.py`
- [X] T098 [P] [US2] Frontend cancel button in `frontend/src/routes/Trips.tsx` (inline confirm — modal upgrade deferred)
- [ ] T099 [P] [US2] Playwright E2E for US2 in `frontend/tests/e2e/us2_cancel.spec.ts`

**Checkpoint (US2 complete)**: Quickstart Scenario D passes; SC-011 measured green.

---

## Phase 6: User Story 3 — Operator four-eyes refund approval (P3) 🔒 refund_gate

**Goal**: Only a refund approved by a **different** principal holding
`payments:refund:approve` executes with the PSP; auto-refund allowlist ships empty; audit
immutable; state machine at 100% line + branch.

**Independent Test**: Quickstart Scenario E — verify self-approval rejected, distinct
approver executes, revoke works before execution.

**Endpoints exercised**: `GET /refunds`, `POST /refunds/{id}/approve`,
`POST /refunds/{id}/revoke`.

### Tests for US3 — ALL marked `@pytest.mark.refund_gate` (Principle VI)

- [ ] T100 [P] [US3] Pytest `-m refund_gate` for `GET /refunds` in `tests/refund_gate/api/test_refunds_list.py` (approver scope required; cursor pagination; state filter)
- [X] T101 [P] [US3] Self-approval → 403 verified by `tests/integration/test_lifecycle.py::test_four_eyes_rejection_and_approval` (marked `refund_gate`)
- [X] T102 [P] [US3] Approve happy path verified by same lifecycle test (`operator-1` → EXECUTED)
- [ ] T103 [P] [US3] Pytest `-m refund_gate` for `POST /refunds/{id}/revoke` (from `APPROVED` and from `REQUESTED`) in `tests/refund_gate/api/test_refunds_revoke.py`
- [X] T104 [P] [US3] `tests/unit/domain/test_refund_gate.py` — 13 tests marked `refund_gate` covering all legal/illegal transitions + four-eyes + fail-closed executable check
- [ ] T105 [P] [US3] Pytest `-m refund_gate` for payment adapter **fail-closed re-check** in `tests/refund_gate/adapters/test_payment_refund_fail_closed.py` (adapter re-verifies `state=APPROVED` inside same DB transaction; refuses if state was tampered)
- [ ] T106 [P] [US3] Pytest `-m refund_gate` for **empty auto-refund allowlist** at launch in `tests/refund_gate/policies/test_auto_refund_allowlist.py`
- [ ] T107 [P] [US3] Pytest `-m refund_gate` for immutable `AuditEvent` (no UPDATE/DELETE grants; append-only) in `tests/refund_gate/adapters/test_audit_immutable.py`
- [ ] T108 [P] [US3] Pytest `-m refund_gate` for `refund.requested`, `refund.approved`, `refund.executed` event emission in `tests/refund_gate/events/test_refund_events.py`

### Implementation for US3

- [X] T109 [US3] `RefundSM` in `src/domain/state_machines/refund_sm.py` — REQUESTED/APPROVED/EXECUTED/REVOKED/REJECTED (FAILED still open)
- [ ] T110 [US3] `AutoRefundAllowlist` policy in `src/domain/policies/auto_refund_allowlist.py` (empty by default; fail unless entry matches)
- [X] T111 [US3] `RefundApprovalService` in `src/application/orchestrator.py` — `approve` calls `check_four_eyes` + `assert_executable` + provider.refund in one tx (scope check still open — MVP trusts `X-Approver-Sub`)
- [ ] T112 [US3] Payment adapter refund path in `src/adapters/providers/payment_stub.py` with **fail-closed re-check** inside same DB transaction (reads `refund.state=APPROVED` before PSP call; refuses otherwise)
- [X] T113 [US3] Route `GET /api/refunds` in `src/api/routes.py` with `?state=` filter (cursor pagination + scope check still open)
- [X] T114 [US3] Route `POST /api/refunds/{id}/approve` in `src/api/routes.py`
- [X] T115 [US3] Route `POST /api/refunds/{id}/revoke` in `src/api/routes.py`
- [X] T116 [P] [US3] Frontend refund queue in `frontend/src/routes/RefundQueue.tsx` (approver dropdown, Approve / Revoke buttons)
- [ ] T117 [P] [US3] Playwright E2E for four-eyes flow in `frontend/tests/e2e/us3_four_eyes.spec.ts` with axe-core assertion

**Checkpoint (US3 complete)**: `pytest -m refund_gate` green with 100% line + branch on
`refund_sm.py`; quickstart Scenario E passes.

---

## Phase 7: User Story 5 — Partner idempotency (P3)

**Goal**: Same idempotency key across hold / pay / cancel yields exactly one effect and
identical response; different body with same key returns 409; partner clients authenticate
via bearer JWT (client-credentials).

**Independent Test**: Quickstart Scenario F.

**Endpoints exercised**: `POST /reservations`, `POST /reservations/{id}/pay`,
`POST /reservations/{id}/cancel` (all with `Idempotency-Key`), plus JWT bearer auth path.

### Tests for US5

- [ ] T118 [P] [US5] Pytest for duplicate hold + same key → single hold, identical response in `tests/unit/api/test_us5_hold_idempotent.py`
- [ ] T119 [P] [US5] Pytest for duplicate pay + same key → single capture in `tests/unit/api/test_us5_pay_idempotent.py`
- [ ] T120 [P] [US5] Pytest for duplicate cancel + same key → single cancellation in `tests/unit/api/test_us5_cancel_idempotent.py`
- [ ] T121 [P] [US5] Pytest for same key + different body → 409 Conflict in `tests/unit/api/test_us5_key_hash_mismatch.py`
- [ ] T122 [P] [US5] Pytest for partner JWT bearer auth (client-credentials) in `tests/unit/middleware/test_partner_auth.py`
- [ ] T123 [P] [US5] Integration test in `tests/integration/test_us5_partner_flow.py` (partner drives full flow via bearer JWT with idempotency retries)

### Implementation for US5

- [ ] T124 [US5] Ensure `IdempotencyMiddleware` is registered on every state-changing route (verify list matches `contracts/openapi.yaml` operations declaring `Idempotency-Key`)
- [ ] T125 [US5] Add Keycloak partner client + `reservations:write` scope seed in `infra/dev/keycloak/rbo-realm.json`
- [ ] T126 [US5] JWT bearer verification path in `src/adapters/identity/oidc_verifier.py` (audience + issuer + signature; JWKS cached with TTL)
- [ ] T127 [US5] Partner-facing rate limiting middleware in `src/middleware/rate_limit.py` (per-`sub` token bucket in Redis)

**Checkpoint (US5 complete)**: Quickstart Scenario F passes.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Constitution-required non-functional coverage, chaos, load, a11y, security,
docs.

- [ ] T128 [P] Chaos test: payment timeout → `CANCELLED_PAYMENT_FAILED` (SC-012) in `tests/e2e/test_payment_timeout_chaos.py`
- [ ] T129 [P] Chaos test: provider outage returns partial results in `tests/e2e/test_partial_search_results.py`
- [ ] T130 [P] Chaos test: SQLite writer lock contention in `tests/integration/test_writer_lock_serialization.py`
- [ ] T131 [P] k6 load smoke: search sustained 50 rps in `tests/load/search_smoke.js`
- [ ] T132 [P] k6 load smoke: hold→pay→confirm sustained 10 rps in `tests/load/write_path_smoke.js`
- [ ] T133 [P] Playwright + axe-core a11y sweep across all routes in `frontend/tests/e2e/a11y_sweep.spec.ts`
- [ ] T134 [P] structlog PII redaction filter in `src/observability/logging.py` (redacts payment tokens, emails per §S-2)
- [ ] T135 [P] OpenTelemetry span coverage audit: verify `Orchestrator.run_lifecycle`, `PricingEngine.evaluate`, each subagent step emit spans in `tests/integration/observability/test_span_coverage.py`
- [ ] T136 [P] Prometheus RED + business counters wired in `src/observability/metrics.py` (`http_requests_total`, `reservations_confirmed_total`, `refunds_executed_total`, `holds_expired_total`, `payment_failures_total`)
- [ ] T137 [P] Alembic downgrade round-trip smoke test in `tests/integration/persistence/test_alembic_roundtrip.py`
- [ ] T138 [P] `docker compose -f infra/dev/docker-compose.yml up` smoke test in CI
- [ ] T139 [P] Coverage gate script `scripts/check_coverage_floors.py` fails if `src/domain/**` or `src/application/**` < 85%, or `refund_sm.py` < 100% line+branch
- [ ] T140 [P] Constitution compliance audit checklist in `specs/001-reservation-orchestrator/checklists/constitution_compliance.md`
- [ ] T141 [P] Update `README.md` with architecture diagram + quickstart link
- [ ] T142 [P] Frontend performance budget check (LCP < 2.5 s on 4G mid-tier; reservation-flow JS < 250 KB gzipped) in `frontend/tests/e2e/perf_budget.spec.ts`
- [ ] T143 Final tag / release notes for v0.1.0 in `CHANGELOG.md`

---

## Dependencies

### Cross-phase

- **Phase 1 → Phase 2**: Phase 2 needs `pyproject`, `pytest`, Alembic, and observability scaffolding.
- **Phase 2 → any user story**: no US phase may start before T014–T038 are green.
- **Phase 3 (US1) is MVP** and blocks nothing except gives all downstream stories real
  code paths to exercise.
- **Phase 4 (US4)** depends on US1 for the `Reservation` entity + `HOLD_PENDING/HELD`
  states.
- **Phase 5 (US2)** depends on US1 (needs `CONFIRMED` state to cancel a paid reservation).
- **Phase 6 (US3)** depends on US2 (needs `Refund` entity seed + `REQUESTED` state).
- **Phase 7 (US5)** depends on US1 + US2 (idempotency spans hold/pay/cancel).
- **Phase 8** runs after every user story ships (some tasks like T131/T132 can start
  earlier as smoke).

### Within-phase parallelism markers

Tasks flagged with `[P]` inside the same phase are independent (different files, no
shared state) and safe to schedule together. Sequential tasks in the same phase share a
file or are logical prerequisites.

## Parallel Execution Examples

### Phase 3 (US1) — parallel test batch (all `[P]`)

```text
T039  tests/unit/api/test_search.py
T040  tests/unit/api/test_reservations_hold.py
T041  tests/unit/api/test_reservations_get.py
T042  tests/unit/api/test_reservations_pay.py
T043  tests/unit/api/test_reservations_confirm.py
T044  tests/unit/domain/test_pricing_engine.py
T045  tests/unit/domain/test_reservation_sm.py
T046  tests/unit/application/test_orchestrator_happy_path.py
T047  tests/integration/test_us1_e2e.py
```

### Phase 3 (US1) — parallel adapter batch

```text
T053  src/adapters/providers/flight_stub.py
T054  src/adapters/providers/room_stub.py
T055  src/adapters/providers/payment_stub.py
T056  src/adapters/providers/notify_stub.py
```

### Phase 6 (US3) — parallel refund_gate batch

```text
T100..T108   (all under tests/refund_gate/**)
```

## Implementation Strategy

**MVP scope**: Phases 1 + 2 + 3 (User Story 1). Ship the P1 happy path first — it
independently validates search, pricing determinism, hold, pay, confirm, and the
observability + idempotency plumbing on the read/write paths.

**Increment order after MVP** (priority + dependency):

1. **US4** (hold auto-expiry, P2) — completes the "holds don't rot" story; no new
   endpoints, worker-only.
2. **US2** (cancel + refund request, P2) — unlocks refund pipeline for US3.
3. **US3** (four-eyes refund approval, P3) — Principle VI compliance; gates production
   launch.
4. **US5** (partner idempotency, P3) — hardens the state-changing endpoints for retry
   traffic.
5. **Polish** (Phase 8) — chaos, load, a11y, docs; run continuously starting when US1
   ships.

## Endpoint → pytest coverage map

Confirms the user's directive "every endpoint needs a pytest case":

| Endpoint (from `contracts/openapi.yaml`) | Pytest task |
|---|---|
| `GET /livez` | T032 |
| `GET /readyz` | T033 |
| `POST /search` | T039 |
| `POST /reservations` (place hold) | T040 |
| `GET /reservations/{id}` | T041 |
| `POST /reservations/{id}/pay` | T042 |
| `POST /reservations/{id}/confirm` | T043 |
| `POST /reservations/{id}/cancel` | T081, T082, T083, T084, T085 |
| `POST /reservations/{id}/refunds` | T086, T145 |
| `GET /refunds` | T100 |
| `POST /refunds/{id}/approve` | T101, T102 |
| `POST /refunds/{id}/revoke` | T103 |

---

## Phase 9: Remediations from `/speckit-analyze` (post-analyze patch)

**Purpose**: Close the findings surfaced by `/speckit-analyze` — coverage gaps
(C1, C2, C5, C6, C7), underspecification (U1–U4), inconsistencies (I1–I3), and
the resolved contract/constitution issues (X1, X2, X3, X4). Constitution has
been amended to **v1.3.0** so X2 and X3 are now sanctioned by the tech-standard
rules and require only re-evaluation triggers, not code changes.

Tasks in this phase reference the phase they logically belong to via a
parenthetical hint; scheduling should slot them into that phase during
`/speckit-implement`.

### X1 / X4 — Contract fixes (already applied to `contracts/openapi.yaml`)

- [ ] T144 [US2] Update `RefundRequestService` and `POST /reservations/{id}/refunds` handler in `src/api/refunds.py` to accept only `reason` from the caller and compute `amount` + `policy_code` server-side (RoomCancellationPolicy or FlightRefundPolicy). Supersedes the original T097 wire-up. (Phase 5)
- [ ] T145 [US2] Pytest asserting caller-supplied `amount` / `policy_code` are ignored or rejected on `POST /reservations/{id}/refunds` in `tests/unit/api/test_reservations_refunds_server_computed.py`. (Phase 5)
- [ ] T146 [P] [US2] Regenerate frontend TypeScript client after `RefundRequest` change (`pnpm --dir frontend run openapi:generate`); update `frontend/src/routes/RefundApproval.tsx` and `frontend/src/routes/History.tsx` request payloads to send only `reason`. (Phase 5)
- [ ] T147 Update Pydantic v2 request schema `RefundRequestModel` in `src/api/schemas/refunds.py` to expose only `reason`. (Phase 2/5)
- [ ] T148 [P] Update contract test to assert `oauth2` security scheme and scope enforcement in `tests/contract/test_openapi_security.py` (schemathesis auth stateful check). (Phase 2)

### C1 — Confirmation notification (FR-014, SC-010)

- [ ] T149 [US1] Wire `NotificationPort.send_confirmation(reservation)` into `Orchestrator.confirm()` in `src/application/orchestrator.py`; emit `notification.sent` outbox event. (Phase 3)
- [ ] T150 [P] [US1] Pytest asserting notification stub called exactly once on confirm and `notification.sent` outbox row written in same tx in `tests/unit/application/test_orchestrator_confirm_notifies.py`. (Phase 3)
- [ ] T151 [P] SC-010 SLO check: k6 + notification-stub timing harness in `tests/load/notification_sla.js` asserting 95% of confirmations produce a notification within 30 s under 10 rps write load. (Phase 8)

### C2 — Per-event emission tests (FR-030)

- [ ] T152 [P] [US1] Pytest `reservation.created` outbox row emitted on `POST /reservations` in `tests/unit/application/test_event_reservation_created.py`. (Phase 3)
- [ ] T153 [P] [US1] Pytest `payment.authorized` outbox row emitted on `POST /reservations/{id}/pay` (success path) in `tests/unit/application/test_event_payment_authorized.py`. (Phase 3)
- [ ] T154 [P] [US1] Pytest `payment.failed` outbox row emitted on `POST /reservations/{id}/pay` timeout in `tests/unit/application/test_event_payment_failed.py`. (Phase 3)
- [ ] T155 [P] [US1] Pytest `booking.confirmed` outbox row emitted on `POST /reservations/{id}/confirm` in `tests/unit/application/test_event_booking_confirmed.py`. (Phase 3)
- [ ] T156 [P] [US4] Pytest `hold.expired` outbox row emitted by expiry sweeper in `tests/unit/workers/test_event_hold_expired.py`. (Phase 4)
- [ ] T157 [P] [US2] Pytest `cancellation.completed` outbox row emitted on every `CANCELLED_*` transition in `tests/unit/application/test_event_cancellation_completed.py`. (Phase 5)

### C3 — GDPR deviation (Principle V, "Data & compliance")

- [ ] T158 [P] Record a time-boxed constitution deviation for GDPR right-to-erasure and data-export in `specs/001-reservation-orchestrator/checklists/constitution_compliance.md` (v1 ships without these capabilities behind a launch-blocking feature flag; ticket link and quarterly review date recorded per §Governance). (Phase 8)
- [ ] T159 [P] Add `POST /admin/gdpr/erasure-request` stub returning `501 Not Implemented` with a `Retry-After: post-v1` header and RFC 7807 body; add a pytest asserting the 501 contract in `tests/unit/api/test_gdpr_stub.py`. (Phase 8)

### C5 — Migration integrity check (Constitution CI #6)

- [ ] T160 [P] Split T137: keep T137 as Alembic upgrade/downgrade round-trip, and add T160 to run migration against a **seeded prior-version SQLite fixture** followed by `PRAGMA integrity_check` in `tests/integration/persistence/test_alembic_prior_db.py`. (Phase 8)

### C6 — Frontend coverage floor

- [ ] T161 [P] Extend the coverage-floor script `scripts/check_coverage_floors.py` to also fail if `frontend/coverage/coverage-summary.json` shows `< 70%` line coverage in `frontend/src/`. (Phase 8)

### C7 — Lighthouse Web Vitals (LCP, INP, CLS)

- [ ] T162 [P] Add Lighthouse CI config `frontend/lighthouserc.js` asserting LCP < 2.5 s, INP < 200 ms, CLS < 0.1 on the reservation flow; wire into CI in the frontend workflow. Extend T142. (Phase 8)

### U1 — FR-006 price deviation recording

- [ ] T163 [US1] Add domain method `Offer.observe_reprice(new_total, reason)` in `src/domain/entities/offer.py` that appends a `PriceDeviation` record and emits an `AuditEvent`. (Phase 3)
- [ ] T164 [P] [US1] Pytest asserting deviation recorded + surfaced via `X-Price-Deviation` response header on the re-quote path in `tests/unit/api/test_search_deviation.py`. (Phase 3)

### U2 — Split CI checks

- [ ] T165 [P] Refactor T012 into per-check CI jobs: T012a `ruff`, T012b `mypy`, T012c `import-linter`, T012d `pytest unit`, T012e `pytest integration`, T012f `pytest contract`, T012g `pytest e2e`, T012h `pytest -m refund_gate`, T012i `coverage floor`, T012j `alembic round-trip + PRAGMA integrity_check`, T012k `docker build + Trivy scan`, T012l `pip-audit + bandit + semgrep`, T012m `pnpm audit + eslint + tsc + vitest + playwright + axe + lighthouse`. Update `.github/workflows/ci.yml`. (Phase 1)

### U3 — SC-006/SC-008/SC-009/SC-011 sample-size assertions

- [ ] T166 [P] Add a sampling test harness `tests/load/sc_sample_sizes.py` that runs the exact sample sizes named in the spec (1000 quotes for SC-006, 1000 replays for SC-008, 200 self-approval attempts for SC-009, 500 cancellations for SC-011) and asserts the thresholds. Runs nightly (not per-PR) via a separate workflow. (Phase 8)

### U4 — Frontend security (CSP + no-token-in-localStorage)

- [ ] T167 [P] Add strict CSP middleware in `src/middleware/csp.py` (default-src 'self'; no unsafe-inline; nonce for Vite build); Playwright test in `frontend/tests/e2e/security_csp.spec.ts` asserting CSP header and asserting `window.localStorage.length === 0` and `window.sessionStorage.length === 0` after login. (Phase 8)

### I1 — Confirmation reference terminology

- [ ] T168 [US1] Add `confirmation_code` (8-char Crockford base32 from ULID) to `Reservation` domain entity, data-model, and OpenAPI `Reservation` schema; populate on transition into `CONFIRMED`; return in confirm response. Update FR-013 wording via a note in `spec.md` §Requirements only if the user confirms wording change. (Phase 3)
- [ ] T169 [P] [US1] Pytest asserting `confirmation_code` is stable, unique per reservation, and present on `GET /reservations/{id}` when state is `CONFIRMED` or later in `tests/unit/api/test_reservations_confirmation_code.py`. (Phase 3)

### I2 — Parallel-safety fix for T032/T033

- [ ] T170 Split `tests/unit/api/test_health.py` into `test_livez.py` and `test_readyz.py` so T032 and T033 truly target different files and remain `[P]`. (Phase 2)

### I3 — Docker digest pinning

- [ ] T171 [P] Update `Dockerfile` and `frontend/Dockerfile` to `FROM python:3.12-slim@sha256:...` and `FROM nginx:1-alpine@sha256:...` respectively; add a CI job that fails if `FROM` line lacks `@sha256:`. Extend T013. (Phase 8)

### Post-remediation gate

- [ ] T172 After T144–T171 complete, re-run `/speckit-analyze` and confirm CRITICAL count is 0 before invoking `/speckit-implement`.
