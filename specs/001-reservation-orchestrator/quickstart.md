# Quickstart — Reservation & Booking Orchestrator

**Feature**: `001-reservation-orchestrator`
**Purpose**: Prove the feature works end-to-end in a fresh dev environment. Implementation
details are in `plan.md`, `data-model.md`, and `contracts/`.

## Prerequisites

- Python 3.12+
- `uv` (fast Python package manager) — install via <https://astral.sh/uv>
- Node.js 20+ and `pnpm`
- Docker + docker-compose
- `just` or `make` (either works with the recipes below)

## 1. Bootstrap

```powershell
# From repo root
uv sync                                     # installs backend deps
pnpm --dir frontend install                 # installs SPA deps
docker compose -f infra/dev/docker-compose.yml up -d redis keycloak   # broker/cache + IdP
uv run alembic upgrade head                 # SQLite migration
uv run python -m src.seed.stubs             # seeds flight/room/payment stubs
```

Environment variables (dev defaults live in `infra/dev/.env`):

- `DATABASE_URL=sqlite+aiosqlite:///./data/rbo.db`
- `REDIS_URL=redis://localhost:6379/0`
- `OIDC_ISSUER=http://localhost:8081/realms/rbo`
- `OIDC_AUDIENCE=rbo-api`

## 2. Run the stack

```powershell
# Terminal A: API + workers
uv run uvicorn src.main:app --reload --port 8080

# Terminal B: SPA
pnpm --dir frontend dev
```

Open <http://localhost:5173>. Log in via Keycloak with the seeded users:

- `guest@example.com / test` (`reservations:write`)
- `agent1@example.com / test` (`reservations:write`, `payments:refund:approve`)
- `agent2@example.com / test` (`reservations:write`, `payments:refund:approve`)

## 3. End-to-end validation scenarios

### Scenario A — P1 happy path (search → hold → pay → confirm)

1. Search a room: origin `SFO`, dates 30 days out, `pax=2`.
2. Pick an offer; place hold. Response = `201 Reservation{state=HELD}`.
3. `POST /reservations/{id}/pay` with a stub token. Response = `state=PAY_AUTHORIZED`.
4. `POST /reservations/{id}/confirm`. Response = `state=CONFIRMED`.
5. Verify `booking.confirmed` on `stream:reservations.v1`.

**Success criteria**: SC-001 (first quote < 800 ms), SC-002 (confirm < 500 ms excl.
provider), single `booking.confirmed` per confirmation.

### Scenario B — Hold expiry (P2)

1. Place a hold; do not pay for > 15 min.
2. Observe reservation → `CANCELLED_HOLD_EXPIRED` within 60 s of TTL (SC-003).
3. Verify `hold.expired` + `cancellation.completed` events.

For a fast dev loop, set `HOLD_TTL_SECONDS=30` in `infra/dev/.env`.

### Scenario C — Payment timeout (chaos, FR-015a)

1. Enable stub fault injection: `POST /admin/stubs/payment` `{ "mode": "TIMEOUT", "delay_ms": 6000 }`.
2. Place a hold; call `/pay`.
3. Observe reservation → `CANCELLED_PAYMENT_FAILED` (terminal); hold released.
4. Verify `payment.failed` + `cancellation.completed` events.

**Success criteria**: SC-012 (payment-failure chaos scenario passes).

### Scenario D — Room 48 h refund policy (FR-018a)

1. Confirm a room reservation whose `start_at` is > 48 h away.
2. `POST /reservations/{id}/cancel` — expect full refund path with policy `ROOM_48H_FULL`.
3. Now confirm a second reservation with `start_at` < 48 h away.
4. Cancel — expect `ROOM_48H_ZERO`; no refund is auto-issued.

**Success criteria**: SC-011.

### Scenario E — Refund four-eyes (Principle VI)

1. As `guest`, `POST /reservations/{id}/refunds`. Response = `Refund{state=REQUESTED}`.
2. As **guest** (same `sub`), attempt `POST /refunds/{id}/approve` → `403`.
3. As `agent1` (requester was guest, so approver differs), approve → `state=APPROVED`.
4. Payment adapter executes → `state=EXECUTED`; `refund.executed` emitted.

Now the negative path:

1. As `agent1`, request a refund on a different reservation.
2. As `agent1`, try to approve → `403` (four-eyes).
3. As `agent2`, approve → `EXECUTED`.

### Scenario F — Idempotency

1. Send `POST /reservations` twice with the **same** `Idempotency-Key` and body.
2. Both requests return the same `201 Reservation` body.
3. Send a third with the same key but a different body → `409 Conflict`.

## 4. Test suites (Principle III)

```powershell
# Backend
uv run pytest tests/unit -q
uv run pytest tests/integration -q          # uses testcontainers Redis + on-disk SQLite
uv run pytest tests/contract -q             # schemathesis vs contracts/openapi.yaml
uv run pytest -m refund_gate -q             # Principle VI — 100% line + branch required
uv run pytest tests/e2e -q                  # chaos scenarios C + D
uv run pytest tests/load/smoke.py -q        # k6 smoke via subprocess

# Frontend
pnpm --dir frontend test                    # Vitest
pnpm --dir frontend test:e2e                # Playwright + axe-core
```

Expected coverage thresholds (CI fails otherwise):

- `src/domain/**`, `src/application/**` ≥ **85%** (target 90%).
- `src/domain/state_machines/refund_sm.py` = **100%** line + branch.

## 5. Observability sanity check

- `GET /livez` → 200; `GET /readyz` → 200 after workers subscribe to Redis.
- `GET /metrics` exposes RED metrics (`http_requests_total`, `http_request_duration_seconds`)
  and business counters (`reservations_confirmed_total`, `refunds_executed_total`).
- structlog output on stdout is JSON with `correlation_id`, `tenant_id`, `user_id`,
  `idempotency_key`, and `reservation_id` when applicable.
- Traces visible in the local Jaeger UI (`http://localhost:16686`) if
  `docker compose -f infra/dev/docker-compose.yml up -d jaeger` was run.

## 6. Reset the world

```powershell
docker compose -f infra/dev/docker-compose.yml down -v
Remove-Item -Recurse -Force .\data
uv run alembic upgrade head
uv run python -m src.seed.stubs
```
