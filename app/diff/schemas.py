from enum import StrEnum

from pydantic import BaseModel, Field


class ChangeType(StrEnum):
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    MODIFIED = "MODIFIED"


class DiffBlock(BaseModel):
    block_type: str = "paragraph"
    locator: str
    previous_text: str | None = None
    current_text: str | None = None
    change_type: ChangeType
    similarity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    previous_context: str | None = None
    current_context: str | None = None


class DiffSummaryStats(BaseModel):
    added_blocks: int = 0
    removed_blocks: int = 0
    changed_blocks: int = 0


class DocumentDiffResult(BaseModel):
    document_id: int
    previous_version_id: int | None
    current_version_id: int
    changed: bool
    summary_stats: DiffSummaryStats
    changes: list[DiffBlock] = Field(default_factory=list)
    truncated: bool = False
