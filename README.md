Reservea — Reservation & Booking Orchestration (MVP)
=================================================

Overview
--------
- Minimal Reservation & Booking orchestration MVP (search → hold → pay → confirm, cancel/refund, hold sweeper) with a MakeMyTrip-inspired React SPA and a FastAPI backend.

Prerequisites
-------------
- Python 3.12
- Node.js (16+) and npm
- Optional: git

Quick setup
-----------
1. Create and activate a Python virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

2. Install frontend dependencies:

```powershell
cd frontend
npm install
cd ..
```

Running the app
---------------

Start the backend (seeds DB automatically on first run):

```powershell
# from repository root
.venv\Scripts\python.exe -m src.main
```

Start the frontend dev server:

```powershell
cd frontend
npm run dev
```

Payment MCP server (optional)
----------------------------
An in-process MCP server exposing `authorize`, `capture`, and `refund` tools is available.

```powershell
python -m src.mcp_payment_server
# SSE mode (binds on :8001):
python -m src.mcp_payment_server --sse
```

Stopping servers
----------------
- Press Ctrl+C in the terminal where the server is running.
- Or stop by port from PowerShell (replace ports if different):

```powershell
# stop backend (port 8000)
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess -Force

# stop frontend (Vite, port 5173)
Stop-Process -Id (Get-NetTCPConnection -LocalPort 5173).OwningProcess -Force

# verify ports are free
Get-NetTCPConnection -LocalPort 8000,5173 -ErrorAction SilentlyContinue
```

Testing
-------

Run the test suite:

```powershell
pytest
```

Useful endpoints
----------------
- Backend API root: http://localhost:8000/
- Frontend dev server: http://localhost:5173/
- Examples:
  - `GET /api/guests`
  - `POST /api/search`
  - `POST /api/reservations` (place hold)
  - `POST /api/reservations/{id}/pay`, `/confirm`, `/refunds`

Notes
-----
- The DB is created/seeded at `data/reservations.db` from `reservation_data.json` on backend startup.
- Refund approvals enforce a four-eyes rule: approver must be != requester.
- Idempotency and an outbox/audit pattern are implemented in the backend for this MVP.

If you want me to add deployment, Docker, or CI steps, tell me which target you prefer.
# Reservation & Booking Orchestrator

Spec-driven MVP implementation of the reservation platform (feature `001-reservation-orchestrator`).

## Quickstart

```powershell
# Backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m src.main            # http://localhost:8000 — OpenAPI at /docs

# Seed DB from reservation_data.json runs automatically on startup.

# Frontend
cd frontend
pnpm install                  # or: npm install
pnpm dev                      # http://localhost:5173
```

## Test

```powershell
pytest -q
pytest -m refund_gate         # Constitution Principle VI gate (100% coverage target)
```

## Layout

```text
src/
├── api/                # FastAPI routers (thin)
├── application/        # Use cases / orchestrator saga
├── domain/             # Pure Python — no framework imports
├── ports/              # Protocols (hexagonal boundaries)
├── adapters/           # persistence, providers, cache, broker, identity
├── observability/      # logging, tracing, metrics
├── middleware/         # correlation-id, idempotency, errors
├── workers/            # hold expiry sweeper, outbox publisher
└── main.py             # ASGI entrypoint
frontend/               # React 18 + Vite + TS strict + Tailwind (MakeMyTrip-styled)
tests/                  # unit / integration / contract / refund_gate
```

See [specs/001-reservation-orchestrator/](specs/001-reservation-orchestrator/) for the full spec, plan, and tasks.
