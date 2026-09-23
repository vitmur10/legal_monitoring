"""Provider-independent publication contract for the knowledge base."""
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel
from app.knowledge_base.errors import PublicationRejected


class KnowledgeBasePublicationResult(BaseModel):
    status: str
    page_id: str | None = None
    page_url: str | None = None
    published_at: datetime | None = None
    error: str | None = None


class KnowledgeBaseAdapter(Protocol):
    async def publish(self, **payload: Any) -> KnowledgeBasePublicationResult: ...


class KnowledgeBaseService:
    def __init__(self, adapter: KnowledgeBaseAdapter) -> None:
        self.adapter = adapter

    async def publish_to_knowledge_base(self, **payload: Any) -> KnowledgeBasePublicationResult:
        try:
            return await self.adapter.publish(**payload)
        except PublicationRejected:
            return KnowledgeBasePublicationResult(status="FAILED", error="Запит до Бази відхилено")
        except Exception:
            # Provider exceptions may contain authorization URLs or request bodies.
            return KnowledgeBasePublicationResult(status="UNKNOWN", error="Результат публікації невідомий; потрібна звірка")
