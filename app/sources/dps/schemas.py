from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import RelationType


class DpsDocumentType(StrEnum):
    NEWS = "NEWS"
    ORDER = "ORDER"
    LETTER = "LETTER"
    REPORTING_FORM = "REPORTING_FORM"
    OTHER = "OTHER"


class DpsAttachment(BaseModel):
    url: str
    label: str
    extension: str
    size_text: str | None = None


class DpsDocumentReference(BaseModel):
    document_kind: str
    issuer: str | None = None
    number: str
    date: Date | None = None
    title: str | None = None
    url: str | None = None
    external_id: str | None = None
    evidence: str


class DpsRelationCandidate(BaseModel):
    from_external_id: str
    to_external_id: str
    relation_type: RelationType
    source: str = "dps"
    metadata: dict[str, Any] = Field(default_factory=dict)


class DpsDocumentStub(BaseModel):
    page_id: str
    external_id: str
    title: str
    canonical_url: str
    print_url: str
    source_url: str
    section: str | None = None
    document_type: DpsDocumentType = DpsDocumentType.OTHER
    published_at: datetime | None = None


class DpsPageMetadata(BaseModel):
    page_id: str
    external_id: str
    title: str
    canonical_url: str
    print_url: str
    source_url: str
    section: str | None = None
    author: str | None = None
    document_type: DpsDocumentType = DpsDocumentType.OTHER
    published_at: datetime | None = None
    effective_at: datetime | None = None
    body: str
    attachments: list[DpsAttachment] = Field(default_factory=list)
    references: list[DpsDocumentReference] = Field(default_factory=list)
    relation_candidates: list[DpsRelationCandidate] = Field(default_factory=list)
