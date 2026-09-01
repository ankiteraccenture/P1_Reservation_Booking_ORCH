"""Shared pytest fixtures — in-memory SQLite + wired-up orchestrator."""
from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def _tmp_db(monkeypatch, tmp_path):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("RSVN_SQLITE_PATH", str(db_file))
    monkeypatch.setenv("RSVN_SEED_FILE", str(Path(__file__).resolve().parents[1] / "reservation_data.json"))
    from src.config import get_settings

    get_settings.cache_clear()
    yield


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from src.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Trigger lifespan
        async with app.router.lifespan_context(app):
            yield c
