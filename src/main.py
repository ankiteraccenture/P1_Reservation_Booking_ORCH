"""ASGI entrypoint — wires app, seed, sweeper, and routers."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.adapters.persistence.database import init_db
from src.adapters.persistence.seeder import seed_if_empty
from src.adapters.providers.stubs import NotificationStub, PaymentStub
from src.api.routes import router
from src.application.orchestrator import Orchestrator, RefundApprovalService
from src.config import get_settings
from src.workers.hold_sweeper import run_forever as sweeper_forever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await init_db()
    await seed_if_empty()
    payment = PaymentStub(fail_rate=settings.payment_fail_rate)
    notifier = NotificationStub()
    app.state.payment = payment
    app.state.notifier = notifier
    app.state.orchestrator = Orchestrator(payment, notifier)
    app.state.refund_service = RefundApprovalService(payment)
    sweeper_task = asyncio.create_task(sweeper_forever())
    try:
        yield
    finally:
        sweeper_task.cancel()
        try:
            await sweeper_task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    app = FastAPI(
        title="Reservation & Booking Orchestrator",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=False)
