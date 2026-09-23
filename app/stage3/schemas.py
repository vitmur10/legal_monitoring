from datetime import datetime
from enum import StrEnum
from typing import Any
from typing import Literal

from pydantic import BaseModel, Field
from app.ai.schemas import KnowledgeBaseRecommendationResult


class PublicationStatus(StrEnum):
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class ReviewItemRead(BaseModel):
    document_id: int
    version_id: int
    title: str
    source_url: str | None = None
    source_origin: str | None = None
    status: PublicationStatus
    importance: str | None = None
    categories: list[str] = Field(default_factory=list)
    summary: str | None = None
    document_status: str | None = None
    document_date: str | None = None
    source_published_at: datetime | None = None
    effective_date: str | None = None
    affected_entities: list[str] = Field(default_factory=list)
    practical_impact: str | None = None
    knowledge_base_recommendation: KnowledgeBaseRecommendationResult = Field(default_factory=KnowledgeBaseRecommendationResult)
    telegram_post: str
    knowledge_base_article: str
    review_metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewDecisionRequest(BaseModel):
    reviewer: str | None = None
    reviewer_id: int | None = None
    note: str | None = None


class RevisionRequest(BaseModel):
    reviewer: str | None = None
    reviewer_id: int | None = None
    comment: str = Field(min_length=1, max_length=4000)


class ModerationDispatchResult(BaseModel):
    version_id: int
    status: PublicationStatus
    chat_id: str
    message_id: str
    sent_at: datetime


class PublishRequest(BaseModel):
    target: str = "telegram"
    dry_run: bool = True
    include_knowledge_base: bool = False


class PublicationRecoveryRequest(BaseModel):
    target: Literal["telegram", "knowledge_base"]
    content_version: int = Field(ge=1)
    attempt_id: str = Field(min_length=1, max_length=100)
    outcome: Literal["PUBLISHED", "NOT_PUBLISHED"]
    reference_id: str | None = Field(default=None, min_length=1, max_length=200)
    page_url: str | None = Field(default=None, max_length=2000)
    note: str = Field(min_length=10, max_length=1000)
    previous_worker_stopped: Literal[True]


class ReviewDecisionResult(BaseModel):
    version_id: int
    status: PublicationStatus
    decided_at: datetime
    reviewer: str | None = None
    note: str | None = None


class PublishActionResult(BaseModel):
    version_id: int
    status: PublicationStatus
    target: str
    message_id: str | None = None
    published_at: datetime | None = None
    error: str | None = None
    knowledge_base_status: str | None = None


class TelegramUpdateResult(BaseModel):
    handled: bool
    action: str | None = None
    version_id: int | None = None
    status: PublicationStatus | None = None
    detail: str | None = None
