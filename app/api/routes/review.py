import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_session
from app.stage3.factory import create_review_service
from app.stage3.review_service import ReviewService
from app.stage3.schemas import (
    PublicationStatus,
    PublicationRecoveryRequest,
    PublishActionResult,
    PublishRequest,
    ModerationDispatchResult,
    ReviewDecisionRequest,
    ReviewDecisionResult,
    ReviewItemRead,
    RevisionRequest,
    TelegramUpdateResult,
)
from app.stage3.telegram_service import TelegramWorkflowService
from app.knowledge_base.service import KnowledgeBasePublicationResult

router = APIRouter(prefix="/review", tags=["review"])


@router.post("/items/{version_id}/recover-publication", response_model=ReviewItemRead)
async def recover_publication(
    version_id: int, payload: PublicationRecoveryRequest,
    recovery_secret: str | None = Header(default=None, alias="X-Publication-Recovery-Secret"),
    session: AsyncSession = Depends(get_session),
):
    expected = get_settings().publication_recovery_secret
    if not expected:
        raise HTTPException(status_code=503, detail="Звірку публікацій не налаштовано")
    if not recovery_secret or not secrets.compare_digest(recovery_secret, expected):
        raise HTTPException(status_code=403, detail="Немає доступу до звірки публікацій")
    try:
        result = await service(session).recover_publication(version_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Матеріал не знайдено")
    return result


@router.post("/items/{version_id}/knowledge-base", response_model=KnowledgeBasePublicationResult)
async def add_to_knowledge_base(version_id: int, session: AsyncSession = Depends(get_session)):
    try:
        result = await service(session).publish_to_knowledge_base(version_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Document version not found")
    await session.commit()
    return result


def service(session: AsyncSession) -> ReviewService:
    return create_review_service(session)


@router.get("/items", response_model=list[ReviewItemRead])
async def list_review_items(
    status: PublicationStatus | None = Query(default=PublicationStatus.READY_FOR_REVIEW),
    session: AsyncSession = Depends(get_session),
):
    return await service(session).list_items(status)


@router.post("/items/{version_id}/approve", response_model=ReviewDecisionResult)
async def approve_review_item(
    version_id: int,
    payload: ReviewDecisionRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await service(session).approve(version_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Document version not found")
    await session.commit()
    return result


@router.post("/items/{version_id}/reject", response_model=ReviewDecisionResult)
async def reject_review_item(
    version_id: int,
    payload: ReviewDecisionRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await service(session).reject(version_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Document version not found")
    await session.commit()
    return result


@router.post("/items/{version_id}/publish", response_model=PublishActionResult)
async def publish_review_item(
    version_id: int,
    payload: PublishRequest,
    session: AsyncSession = Depends(get_session),
):
    if payload.target != "telegram":
        raise HTTPException(status_code=400, detail="Only Telegram publishing is supported")
    try:
        result = await service(session).publish(version_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Document version not found")
    await session.commit()
    return result


@router.post("/items/{version_id}/dispatch", response_model=ModerationDispatchResult)
async def dispatch_review_item(
    version_id: int,
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await service(session).dispatch_to_moderation(version_id)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Document version not found")
    await session.commit()
    return result


@router.post("/items/{version_id}/revise", response_model=ModerationDispatchResult)
async def revise_review_item(
    version_id: int,
    payload: RevisionRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await service(session).revise(version_id, payload)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Document version not found")
    await session.commit()
    return result


@router.post("/telegram/webhook", response_model=TelegramUpdateResult)
async def telegram_webhook(
    update: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    telegram_secret: str | None = Header(default=None, alias="X-Telegram-Bot-Api-Secret-Token"),
):
    settings = get_settings()
    if not settings.telegram_enabled:
        raise HTTPException(status_code=503, detail="Telegram integration is disabled")
    if settings.telegram_webhook_secret and not (
        telegram_secret
        and secrets.compare_digest(telegram_secret, settings.telegram_webhook_secret)
    ):
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret")
    result = await TelegramWorkflowService(service(session)).handle_update(update)
    await session.commit()
    return result
