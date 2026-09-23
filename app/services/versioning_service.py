from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.stage2_service import Stage2AnalysisService, create_stage2_service_from_settings
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.enums import ProcessingStatus, RelationType
from app.models.source import Source
from app.repositories.document_repository import DocumentRepository
from app.repositories.relation_repository import DocumentRelationRepository
from app.schemas.common import ProcessingResult
from app.services.identity_service import DocumentIdentityService
from app.sources.base import NormalizedDocument
from app.utils.hashing import sha256_text
from app.core.config import get_settings
from app.stage3.factory import create_review_service


class VersioningService:
    def __init__(
        self,
        identity_service: DocumentIdentityService | None = None,
        stage2_service: Stage2AnalysisService | None = None,
        enable_stage2_from_env: bool = True,
    ) -> None:
        self.identity_service = identity_service or DocumentIdentityService()
        self.stage2_service = (
            stage2_service
            if stage2_service is not None
            else create_stage2_service_from_settings()
            if enable_stage2_from_env
            else None
        )

    async def process_document(
        self,
        session: AsyncSession,
        source: Source,
        normalized: NormalizedDocument,
        raw_content: str,
    ) -> ProcessingResult:
        content_hash = sha256_text(normalized.content)
        identity = self.identity_service.identify(normalized, content_hash)
        source_id = source.id
        source_code = source.code

        try:
            return await self._process_once(
                session,
                source_id,
                source_code,
                normalized,
                raw_content,
                content_hash,
                identity,
            )
        except IntegrityError:
            await session.rollback()
            return await self._process_once(
                session,
                source_id,
                source_code,
                normalized,
                raw_content,
                content_hash,
                identity,
            )

    async def _process_once(
        self,
        session: AsyncSession,
        source_id: int,
        source_code: str,
        normalized: NormalizedDocument,
        raw_content: str,
        content_hash: str,
        identity,
    ) -> ProcessingResult:
        repo = DocumentRepository(session)
        now = datetime.now(timezone.utc)
        document = await repo.get_by_identity_for_update(source_id, identity.identity_key)

        if document is None:
            document = Document(
                source_id=source_id,
                identity_key=identity.identity_key,
                identity_type=identity.identity_type,
                external_id=normalized.external_id,
                canonical_url=normalized.canonical_url,
                title=normalized.title,
                document_type=normalized.document_type,
                published_at=normalized.published_at,
                effective_at=normalized.effective_at,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(document)
            await session.flush()
            version = self._new_version(document.id, 1, raw_content, normalized, content_hash, now)
            session.add(version)
            await session.flush()
            document.current_version_id = version.id
            await self._run_stage2_if_configured(
                session=session,
                status=ProcessingStatus.NEW,
                document=document,
                current_version=version,
                previous_version=None,
                source_code=source_code,
            )
            await session.flush()
            await self._resolve_explicit_relations(session, source_id)
            return ProcessingResult(
                status=ProcessingStatus.NEW,
                document_id=document.id,
                current_version_id=version.id,
                source_code=source_code,
                external_id=normalized.external_id,
            )

        current_version = document.current_version
        previous_version_id = current_version.id if current_version else None
        if current_version and current_version.content_hash == content_hash:
            self._update_document_seen_fields(document, normalized, now)
            await session.flush()
            await self._resolve_explicit_relations(session, source_id)
            return ProcessingResult(
                status=ProcessingStatus.UNCHANGED,
                document_id=document.id,
                previous_version_id=previous_version_id,
                current_version_id=previous_version_id,
                source_code=source_code,
                external_id=normalized.external_id,
            )

        next_number = await repo.latest_version_number(document.id) + 1
        version = self._new_version(document.id, next_number, raw_content, normalized, content_hash, now)
        session.add(version)
        await session.flush()
        self._update_document_seen_fields(document, normalized, now)
        document.current_version_id = version.id
        await self._run_stage2_if_configured(
            session=session,
            status=ProcessingStatus.CHANGED,
            document=document,
            current_version=version,
            previous_version=current_version,
            source_code=source_code,
        )
        await session.flush()
        await self._resolve_explicit_relations(session, source_id)
        return ProcessingResult(
            status=ProcessingStatus.CHANGED,
            document_id=document.id,
            previous_version_id=previous_version_id,
            current_version_id=version.id,
            source_code=source_code,
            external_id=normalized.external_id,
        )

    def _new_version(
        self,
        document_id: int,
        version_number: int,
        raw_content: str,
        normalized: NormalizedDocument,
        content_hash: str,
        detected_at: datetime,
    ) -> DocumentVersion:
        return DocumentVersion(
            document_id=document_id,
            version_number=version_number,
            raw_content=raw_content,
            normalized_content=normalized.content,
            content_hash=content_hash,
            version_metadata=normalized.metadata,
            detected_at=detected_at,
        )

    def _update_document_seen_fields(
        self, document: Document, normalized: NormalizedDocument, seen_at: datetime
    ) -> None:
        document.last_seen_at = seen_at
        document.external_id = document.external_id or normalized.external_id
        document.canonical_url = document.canonical_url or normalized.canonical_url
        document.title = normalized.title
        document.document_type = normalized.document_type
        document.published_at = normalized.published_at
        document.effective_at = normalized.effective_at

    async def _resolve_explicit_relations(self, session: AsyncSession, source_id: int) -> None:
        repo = DocumentRepository(session)
        documents = await repo.list_by_source_with_current_versions(source_id)
        documents_by_external_id = {
            document.external_id: document for document in documents if document.external_id
        }
        relation_repo = DocumentRelationRepository(session)

        for document in documents:
            version = document.current_version
            if version is None:
                continue
            candidates = []
            candidates.extend(version.version_metadata.get("relation_candidates") or [])
            candidates.extend(version.version_metadata.get("historical_relation_candidates") or [])
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                metadata = candidate.get("metadata") or {}
                if metadata.get("deterministic") is not True or metadata.get("explicit") is not True:
                    continue

                from_external_id = candidate.get("from_external_id")
                to_external_id = candidate.get("to_external_id")
                relation_type_value = candidate.get("relation_type")
                try:
                    relation_type = RelationType(relation_type_value)
                except ValueError:
                    continue
                from_document = documents_by_external_id.get(from_external_id)
                to_document = documents_by_external_id.get(to_external_id)
                if from_document is None or to_document is None:
                    continue
                if await relation_repo.exists(from_document.id, to_document.id, relation_type):
                    continue
                await relation_repo.create(
                    from_document_id=from_document.id,
                    to_document_id=to_document.id,
                    relation_type=relation_type,
                    metadata={**metadata, "source": candidate.get("source")},
                )

    async def _run_stage2_if_configured(
        self,
        *,
        session: AsyncSession,
        status: ProcessingStatus,
        document: Document,
        current_version: DocumentVersion,
        previous_version: DocumentVersion | None,
        source_code: str,
    ) -> None:
        if self.stage2_service is None:
            return
        metadata = await self.stage2_service.process(
            status=status,
            document=document,
            current_version=current_version,
            previous_version=previous_version,
            source_code=source_code,
        )
        if metadata is None:
            return
        current_metadata = dict(current_version.version_metadata or {})
        current_metadata["stage2"] = metadata
        current_version.version_metadata = current_metadata
        await session.flush()
        settings = get_settings()
        if settings.telegram_enabled and metadata.get("status") == "ANALYZED":
            try:
                await create_review_service(session, settings).dispatch_to_moderation(
                    current_version.id
                )
            except Exception as exc:
                logger_metadata = dict(current_version.version_metadata or {})
                stage3 = dict(logger_metadata.get("stage3") or {})
                stage3.update(
                    {
                        "status": "FAILED",
                        "error": f"Moderation dispatch failed: {exc}",
                        "failed_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                logger_metadata["stage3"] = stage3
                current_version.version_metadata = logger_metadata
                await session.flush()
