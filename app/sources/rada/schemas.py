from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import RelationType


class RadaRevisionState(StrEnum):
    PREVIOUS = "PREVIOUS"
    CURRENT = "CURRENT"
    FUTURE = "FUTURE"


class RadaRevision(BaseModel):
    date: date
    basis_nregs: list[str] = Field(default_factory=list)
    event_type: int | None = None
    format: int | None = None
    pages: int | None = None
    size: int | None = None
    state: RadaRevisionState


class RadaDocumentStub(BaseModel):
    nreg: str
    title: str | None = None
    dokid: int | None = None
    status_id: int | None = None
    type_ids: list[int] = Field(default_factory=list)
    issuer_id: int | None = None
    adoption_date: date | None = None
    document_number: str | None = None
    event_date: date | None = None
    publication_date: date | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class SourceRelationCandidate(BaseModel):
    from_external_id: str
    to_external_id: str
    relation_type: RelationType
    source: str = "rada"
    metadata: dict[str, Any] = Field(default_factory=dict)


class RadaCard(BaseModel):
    nreg: str
    dokid: int | None = None
    title: str
    status_id: int | None = None
    type_ids: list[int] = Field(default_factory=list)
    document_type: str | None = None
    issuer_id: int | None = None
    adoption_date: date | None = None
    document_number: str | None = None
    current_revision_date: date | None = None
    basis_nregs: list[str] = Field(default_factory=list)
    current_revision_basis_nregs: list[str] = Field(default_factory=list)
    specific_revision_basis_nregs: list[str] = Field(default_factory=list)
    effective_date: date | None = None
    publication_date: date | None = None
    revisions: list[RadaRevision] = Field(default_factory=list)
    relation_candidates: list[SourceRelationCandidate] = Field(default_factory=list)
    historical_relation_candidates: list[SourceRelationCandidate] = Field(default_factory=list)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
