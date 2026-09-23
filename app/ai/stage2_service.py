from datetime import datetime, timezone
import logging
from typing import Any

from pydantic import ValidationError

from app.ai.analysis_service import AIAnalysisService
from app.ai.content_service import AIContentService
from app.ai.provider import AIProviderError, OpenAICompatibleProvider
from app.ai.prompts import ANALYSIS_PROMPT_VERSION, CONTENT_PROMPT_VERSION, RELEVANCE_PROMPT_VERSION
from app.ai.relevance_service import AIRelevanceService
from app.ai.schemas import Stage2Input
from app.core.config import Settings, get_settings
from app.diff.engine import DocumentDiffEngine
from app.diff.schemas import DocumentDiffResult
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.enums import ProcessingStatus

logger = logging.getLogger(__name__)


class Stage2AnalysisService:
    def __init__(
        self,
        *,
        relevance_service: AIRelevanceService,
        analysis_service: AIAnalysisService,
        content_service: AIContentService | None = None,
        diff_engine: DocumentDiffEngine | None = None,
        max_total_tokens_per_document: int | None = None,
    ) -> None:
        self.relevance_service = relevance_service
        self.analysis_service = analysis_service
        self.content_service = content_service
        self.diff_engine = diff_engine or DocumentDiffEngine()
        self.max_total_tokens_per_document = max_total_tokens_per_document

    async def process(
        self,
        *,
        status: ProcessingStatus,
        document: Document,
        current_version: DocumentVersion,
        previous_version: DocumentVersion | None = None,
        source_code: str,
    ) -> dict[str, Any] | None:
        if status in {ProcessingStatus.UNCHANGED, ProcessingStatus.FAILED}:
            return None

        diff = None
        if status == ProcessingStatus.CHANGED and previous_version is not None:
            diff = self.diff_engine.build(
                document_id=document.id,
                previous_version_id=previous_version.id,
                current_version_id=current_version.id,
                previous_text=previous_version.normalized_content,
                current_text=current_version.normalized_content,
            )
            if not diff.changed:
                return self._metadata("NO_MEANINGFUL_CHANGE", diff=diff)

        stage_input = Stage2Input(
            source_code=source_code,
            document_id=document.id,
            previous_version_id=previous_version.id if previous_version else None,
            current_version_id=current_version.id,
            title=document.title,
            document_type=document.document_type,
            normalized_text=current_version.normalized_content,
            metadata=current_version.version_metadata,
            official_url=document.canonical_url,
        )

        usage = []
        relevance_metadata = None
        analysis_metadata = None
        try:
            relevance, relevance_response = await self.relevance_service.classify(stage_input, diff)
            relevance_metadata = relevance.model_dump(mode="json")
            usage.append(relevance_response.usage.model_dump(mode="json"))
            if self._usage_exceeds_limit(usage):
                return self._metadata(
                    "TOKEN_LIMIT_EXCEEDED",
                    diff=diff,
                    relevance=relevance_metadata,
                    usage=usage,
                    error="AI token budget exceeded after relevance classification",
                )
            if not relevance.relevant:
                return self._metadata(
                    "FILTERED_OUT",
                    diff=diff,
                    relevance=relevance_metadata,
                    usage=usage,
                )
            analysis, analysis_response = await self.analysis_service.analyze(
                stage_input, relevance, diff
            )
            analysis_metadata = analysis.model_dump(mode="json")
            usage.append(analysis_response.usage.model_dump(mode="json"))
            content_metadata = None
            if self.content_service is not None and not self._usage_exceeds_limit(usage):
                content, content_response = await self.content_service.generate(stage_input, analysis)
                content_metadata = content.model_dump(mode="json")
                usage.append(content_response.usage.model_dump(mode="json"))
            return self._metadata(
                "ANALYZED",
                diff=diff,
                relevance=relevance_metadata,
                analysis=analysis_metadata,
                content=content_metadata,
                usage=usage,
            )
        except (AIProviderError, ValidationError, ValueError) as exc:
            logger.warning(
                "stage2_ai_failed document_id=%s version_id=%s error=%s",
                document.id,
                current_version.id,
                exc,
            )
            return self._metadata(
                "AI_FAILED",
                diff=diff,
                relevance=relevance_metadata,
                analysis=analysis_metadata,
                error=str(exc),
                usage=usage,
            )

    def _usage_exceeds_limit(self, usage: list[dict[str, Any]]) -> bool:
        if self.max_total_tokens_per_document is None:
            return False
        known_total = sum(item.get("total_tokens") or 0 for item in usage)
        return known_total >= self.max_total_tokens_per_document

    def _metadata(
        self,
        status: str,
        *,
        diff: DocumentDiffResult | None = None,
        relevance: dict[str, Any] | None = None,
        analysis: dict[str, Any] | None = None,
        content: dict[str, Any] | None = None,
        usage: list[dict[str, Any]] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "prompt_versions": {
                "relevance": RELEVANCE_PROMPT_VERSION,
                "analysis": ANALYSIS_PROMPT_VERSION,
                "content": CONTENT_PROMPT_VERSION,
            },
            "diff": diff.model_dump(mode="json") if diff else None,
            "relevance": relevance,
            "analysis": analysis,
            "content": content,
            "usage": usage or [],
            "error": error,
        }


def create_stage2_service_from_settings(settings: Settings | None = None) -> Stage2AnalysisService | None:
    settings = settings or get_settings()
    if not settings.ai_enabled or not settings.ai_api_key:
        return None
    provider = OpenAICompatibleProvider(
        api_key=settings.ai_api_key,
        base_url=settings.ai_base_url,
        timeout_seconds=settings.ai_timeout_seconds,
        max_retries=settings.ai_max_retries,
    )
    return Stage2AnalysisService(
        relevance_service=AIRelevanceService(
            provider,
            settings.ai_model_relevance,
            max_input_chars=settings.ai_relevance_max_input_chars,
            max_output_tokens=settings.ai_relevance_max_output_tokens,
        ),
        analysis_service=AIAnalysisService(
            provider,
            settings.ai_model_analysis,
            max_input_chars=settings.ai_analysis_max_input_chars,
            max_output_tokens=settings.ai_analysis_max_output_tokens,
        ),
        content_service=AIContentService(
            provider,
            settings.ai_model_content or settings.ai_model_analysis,
            max_output_tokens=settings.ai_content_max_output_tokens,
        ),
        max_total_tokens_per_document=settings.ai_max_total_tokens_per_document,
    )
