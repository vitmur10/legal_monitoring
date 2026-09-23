from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RawDocument(BaseModel):
    source_code: str
    external_id: str | None = None
    canonical_url: str | None = None
    title: str | None = None
    content: str | None = None
    document_type: str | None = None
    published_at: datetime | None = None
    effective_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedDocument(BaseModel):
    source_code: str
    external_id: str | None = None
    canonical_url: str | None = None
    title: str
    content: str
    document_type: str | None = None
    published_at: datetime | None = None
    effective_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceAdapter(ABC):
    @property
    @abstractmethod
    def source_code(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def fetch_items(self) -> list[RawDocument]:
        raise NotImplementedError

    async def fetch_document(self, item: RawDocument) -> RawDocument:
        return item

    @abstractmethod
    async def normalize(self, document: RawDocument) -> NormalizedDocument:
        raise NotImplementedError
