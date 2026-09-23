from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import MonitoringRunStatus, ProcessingStatus, RelationType


class ProcessingResult(BaseModel):
    status: ProcessingStatus
    document_id: int | None = None
    previous_version_id: int | None = None
    current_version_id: int | None = None
    source_code: str
    external_id: str | None = None
    error: str | None = None


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    base_url: str | None
    enabled: bool
    check_interval_minutes: int
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    current_version_id: int | None
    identity_key: str
    identity_type: str
    external_id: str | None
    canonical_url: str | None
    title: str
    document_type: str | None
    published_at: datetime | None
    effective_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime


class DocumentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    version_number: int
    raw_content: str
    normalized_content: str
    content_hash: str
    version_metadata: dict[str, Any]
    detected_at: datetime
    created_at: datetime


class DocumentRelationCreate(BaseModel):
    to_document_id: int
    relation_type: RelationType
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentRelationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_document_id: int
    to_document_id: int
    relation_type: RelationType
    relation_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class MonitoringRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    started_at: datetime
    finished_at: datetime | None
    status: MonitoringRunStatus
    items_found: int
    new_count: int
    changed_count: int
    unchanged_count: int
    failed_count: int
    error_message: str | None
    created_at: datetime
