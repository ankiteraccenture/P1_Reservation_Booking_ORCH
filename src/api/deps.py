"""Shared FastAPI dependencies."""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.persistence.database import SessionLocal


async def db_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def correlation_id(x_correlation_id: str | None = Header(default=None, alias="X-Correlation-Id")) -> str:
    return x_correlation_id or uuid.uuid4().hex


def idempotency_key(idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> str | None:
    return idempotency_key


def actor_sub(
    x_user_sub: str | None = Header(default=None, alias="X-User-Sub"),
    x_approver: str | None = Header(default=None, alias="X-Approver-Sub"),
) -> str:
    return x_approver or x_user_sub or "guest-anonymous"


DBSession = Annotated[AsyncSession, Depends(db_session)]
CorrelationId = Annotated[str, Depends(correlation_id)]
IdempotencyKey = Annotated[str | None, Depends(idempotency_key)]
ActorSub = Annotated[str, Depends(actor_sub)]
