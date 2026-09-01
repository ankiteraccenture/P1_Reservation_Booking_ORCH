"""API routers: search, reservations, refunds, catalog."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from src.adapters.persistence.models import Guest, Refund, Reservation
from src.api.deps import ActorSub, CorrelationId, DBSession, IdempotencyKey
from src.api.schemas import (
    CancelRequest,
    GuestListItem,
    Offer,
    PayRequest,
    PlaceHoldRequest,
    ProblemDetail,
    RefundRequest,
    RefundResponse,
    ReservationResponse,
    SearchRequest,
    SearchResponse,
)
from src.application.orchestrator import (
    IdempotencyReplay,
    NotFound,
    Orchestrator,
    RefundApprovalService,
    ReservationConflict,
)
from src.application.orchestrator import _reservation_to_dict  # internal helper
from src.application.search_service import search as run_search
from src.domain.state_machines.refund_sm import SelfApprovalError

router = APIRouter()


# ---- System ---------------------------------------------------------------


@router.get("/livez", tags=["system"])
async def livez() -> dict:
    return {"status": "ok"}


@router.get("/readyz", tags=["system"])
async def readyz(session: DBSession) -> dict:
    # Simple ping — SELECT 1 confirms DB reachability.
    await session.execute(select(1))
    return {"status": "ready"}


# ---- Catalog helpers (dev/demo) -------------------------------------------


@router.get("/guests", response_model=list[GuestListItem], tags=["catalog"])
async def list_guests(session: DBSession) -> list[GuestListItem]:
    rows = (await session.execute(select(Guest))).scalars().all()
    return [
        GuestListItem(
            id=g.id,
            name=g.name,
            email=g.email,
            loyalty_id=g.loyalty_id,
            loyalty_tier=g.loyalty_tier,
        )
        for g in rows
    ]


# ---- Search --------------------------------------------------------------


@router.post("/search", response_model=SearchResponse, tags=["search"])
async def search_endpoint(body: SearchRequest, session: DBSession, corr: CorrelationId) -> SearchResponse:
    offers = await run_search(
        session,
        origin=body.origin,
        destination=body.destination,
        depart_date=body.depart_date,
        return_date=body.return_date,
        check_in=body.check_in,
        check_out=body.check_out,
        location=body.location,
        guests=body.guests,
        guest_id=body.guest_id,
        kinds=body.kinds or ["FLIGHT", "ROOM"],
    )
    return SearchResponse(
        offers=[
            Offer(
                offer_id=o.offer_id,
                kind=o.kind,
                title=o.title,
                subtitle=o.subtitle,
                total_price=o.total_price,
                currency=o.currency,
                breakdown=o.breakdown,
                meta=o.meta,
            )
            for o in offers
        ]
    )


# ---- Reservations --------------------------------------------------------


def _to_response(rsvn: Reservation) -> ReservationResponse:
    return ReservationResponse.model_validate(_reservation_to_dict(rsvn))


@router.post(
    "/reservations",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["reservations"],
    responses={409: {"model": ProblemDetail}, 404: {"model": ProblemDetail}},
)
async def place_hold(
    request: Request,
    body: PlaceHoldRequest,
    session: DBSession,
    corr: CorrelationId,
    idem: IdempotencyKey,
    actor: ActorSub,
) -> ReservationResponse:
    orch: Orchestrator = request.app.state.orchestrator
    try:
        rsvn = await orch.place_hold(
            session,
            guest_id=body.guest_id,
            item_type="FLIGHT" if body.offer_id.startswith("FL") else "ROOM",
            item_id=body.offer_id,
            check_in=body.check_in,
            check_out=body.check_out,
            idempotency_key=idem,
            correlation_id=corr,
            actor_sub=actor,
        )
    except IdempotencyReplay as replay:
        return ReservationResponse.model_validate(replay.body)
    except NotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReservationConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _to_response(rsvn)


@router.get("/reservations", response_model=list[ReservationResponse], tags=["reservations"])
async def list_reservations(session: DBSession) -> list[ReservationResponse]:
    rows = (
        await session.execute(select(Reservation).order_by(Reservation.created_at.desc()))
    ).scalars().all()
    return [_to_response(r) for r in rows]


@router.get(
    "/reservations/{reservation_id}",
    response_model=ReservationResponse,
    tags=["reservations"],
    responses={404: {"model": ProblemDetail}},
)
async def get_reservation(reservation_id: str, session: DBSession) -> ReservationResponse:
    rsvn = await session.get(Reservation, reservation_id)
    if rsvn is None:
        raise HTTPException(status_code=404, detail="reservation not found")
    return _to_response(rsvn)


@router.post(
    "/reservations/{reservation_id}/pay",
    response_model=ReservationResponse,
    tags=["reservations"],
)
async def pay_reservation(
    request: Request,
    reservation_id: str,
    body: PayRequest,
    session: DBSession,
    corr: CorrelationId,
    idem: IdempotencyKey,
    actor: ActorSub,
) -> ReservationResponse:
    orch: Orchestrator = request.app.state.orchestrator
    try:
        rsvn = await orch.pay(
            session,
            reservation_id=reservation_id,
            payment_token=body.payment_token,
            idempotency_key=idem,
            correlation_id=corr,
            actor_sub=actor,
        )
    except IdempotencyReplay as replay:
        return ReservationResponse.model_validate(replay.body)
    except NotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReservationConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _to_response(rsvn)


@router.post(
    "/reservations/{reservation_id}/confirm",
    response_model=ReservationResponse,
    tags=["reservations"],
)
async def confirm_reservation(
    request: Request,
    reservation_id: str,
    session: DBSession,
    corr: CorrelationId,
    idem: IdempotencyKey,
    actor: ActorSub,
) -> ReservationResponse:
    orch: Orchestrator = request.app.state.orchestrator
    try:
        rsvn = await orch.confirm(
            session,
            reservation_id=reservation_id,
            idempotency_key=idem,
            correlation_id=corr,
            actor_sub=actor,
        )
    except IdempotencyReplay as replay:
        return ReservationResponse.model_validate(replay.body)
    except NotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReservationConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _to_response(rsvn)


@router.post(
    "/reservations/{reservation_id}/cancel",
    response_model=ReservationResponse,
    tags=["reservations"],
)
async def cancel_reservation(
    request: Request,
    reservation_id: str,
    body: CancelRequest | None,
    session: DBSession,
    corr: CorrelationId,
    idem: IdempotencyKey,
    actor: ActorSub,
) -> ReservationResponse:
    orch: Orchestrator = request.app.state.orchestrator
    reason = body.reason if body else None
    try:
        rsvn, _refund = await orch.cancel(
            session,
            reservation_id=reservation_id,
            reason=reason,
            idempotency_key=idem,
            correlation_id=corr,
            actor_sub=actor,
        )
    except IdempotencyReplay as replay:
        return ReservationResponse.model_validate(replay.body)
    except NotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReservationConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _to_response(rsvn)


# ---- Refunds -------------------------------------------------------------


def _refund_to_dict(r: Refund) -> dict:
    return {
        "refund_id": r.id,
        "reservation_id": r.reservation_id,
        "amount": float(r.amount),
        "currency": r.currency,
        "policy_code": r.policy_code,
        "reason": r.reason,
        "state": r.state,
        "requester_sub": r.requester_sub,
        "approver_sub": r.approver_sub,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }


@router.post(
    "/reservations/{reservation_id}/refunds",
    response_model=RefundResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["refunds"],
)
async def request_refund(
    request: Request,
    reservation_id: str,
    body: RefundRequest,
    session: DBSession,
    corr: CorrelationId,
    idem: IdempotencyKey,
    actor: ActorSub,
) -> RefundResponse:
    """Cancel + create refund request (delegates to orchestrator.cancel).

    The refund amount and policy_code are ALWAYS server-computed (FR-018).
    """
    orch: Orchestrator = request.app.state.orchestrator
    try:
        _rsvn, refund = await orch.cancel(
            session,
            reservation_id=reservation_id,
            reason=body.reason,
            idempotency_key=idem,
            correlation_id=corr,
            actor_sub=actor,
        )
    except IdempotencyReplay as replay:
        return RefundResponse.model_validate(replay.body)
    except NotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReservationConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    if refund is None:
        raise HTTPException(status_code=409, detail="reservation was unpaid; no refund created")
    return RefundResponse.model_validate(_refund_to_dict(refund))


@router.get("/refunds", response_model=list[RefundResponse], tags=["refunds"])
async def list_refunds(session: DBSession, state: str | None = None) -> list[RefundResponse]:
    stmt = select(Refund).order_by(Refund.created_at.desc())
    if state:
        stmt = stmt.where(Refund.state == state)
    rows = (await session.execute(stmt)).scalars().all()
    return [RefundResponse.model_validate(_refund_to_dict(r)) for r in rows]


@router.post(
    "/refunds/{refund_id}/approve",
    response_model=RefundResponse,
    tags=["refunds"],
    responses={403: {"model": ProblemDetail}, 409: {"model": ProblemDetail}},
)
async def approve_refund(
    request: Request,
    refund_id: str,
    session: DBSession,
    corr: CorrelationId,
    actor: ActorSub,
) -> RefundResponse:
    svc: RefundApprovalService = request.app.state.refund_service
    try:
        refund = await svc.approve(
            session, refund_id=refund_id, approver_sub=actor, correlation_id=corr
        )
    except SelfApprovalError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except NotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReservationConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    return RefundResponse.model_validate(_refund_to_dict(refund))


@router.post(
    "/refunds/{refund_id}/revoke",
    response_model=RefundResponse,
    tags=["refunds"],
)
async def revoke_refund(
    request: Request,
    refund_id: str,
    session: DBSession,
    corr: CorrelationId,
    actor: ActorSub,
) -> RefundResponse:
    svc: RefundApprovalService = request.app.state.refund_service
    try:
        refund = await svc.revoke(
            session, refund_id=refund_id, actor_sub=actor, correlation_id=corr
        )
    except NotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReservationConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    return RefundResponse.model_validate(_refund_to_dict(refund))
