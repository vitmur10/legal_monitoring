import re

from pydantic import ValidationError

from app.ai.prompts import RELEVANCE_PROMPT_VERSION, RELEVANCE_SYSTEM_PROMPT
from app.ai.provider import AIProvider, AIResponse
from app.ai.schemas import DecisionMetadata, RelevanceCategory, RelevanceResult, Stage2Input
from app.diff.schemas import DocumentDiffResult


class AIRelevanceService:
    def __init__(
        self,
        provider: AIProvider,
        model: str,
        max_input_chars: int = 24000,
        max_output_tokens: int | None = 800,
    ) -> None:
        self.provider = provider
        self.model = model
        self.max_input_chars = max_input_chars
        self.max_output_tokens = max_output_tokens

    async def classify(
        self, stage_input: Stage2Input, diff: DocumentDiffResult | None = None
    ) -> tuple[RelevanceResult, AIResponse]:
        payload = {
            "schema_version": RELEVANCE_PROMPT_VERSION,
            "source": stage_input.source_code,
            "document_type": stage_input.document_type,
            "title": stage_input.title,
            "normalized_text": self._clip(stage_input.normalized_text),
            "metadata": stage_input.metadata,
            "document_status": stage_input.document_status,
            "diff_summary": diff.model_dump(mode="json") if diff else None,
            "official_url": str(stage_input.official_url) if stage_input.official_url else None,
            "output_schema": {
                "relevant": "boolean",
                "categories": "array of category enum values",
                "reason": "short Ukrainian explanation",
                "confidence": "0.0-1.0",
            },
        }
        response: AIResponse | None = None
        last_error: ValidationError | None = None
        for attempt in range(2):
            retry_payload = payload if attempt == 0 else {**payload, "validation_error": str(last_error)}
            response = await self.provider.structured_json(
                request_type="relevance",
                model=self.model,
                system_prompt=RELEVANCE_SYSTEM_PROMPT,
                user_payload=retry_payload,
                max_output_tokens=self.max_output_tokens,
                document_id=stage_input.document_id,
                version_id=stage_input.current_version_id,
            )
            try:
                result = RelevanceResult.model_validate(self._extract_result(response.data))
                result = self._apply_tax_reporting_override(result, stage_input.title)
                result.decision_metadata = self._decision_metadata(result)
                return result, response
            except ValidationError as exc:
                last_error = exc
        raise last_error  # type: ignore[misc]

    def _decision_metadata(self, result: RelevanceResult) -> DecisionMetadata:
        if result.confidence >= 0.80:
            band = "auto_decision"
        elif result.confidence >= 0.55:
            band = "needs_review"
        else:
            band = "low_confidence"
        return DecisionMetadata(decision="relevant" if result.relevant else "filtered_out", confidence_band=band)

    @staticmethod
    def _apply_tax_reporting_override(result: RelevanceResult, title: str) -> RelevanceResult:
        normalized_title = title.casefold()
        names_tax_declaration = bool(
            re.search(r"податков\w*\s+(?:деклараці\w*|звітн\w*)", normalized_title)
        )
        changes_form_or_rules = any(
            phrase in normalized_title
            for phrase in ("внесення змін", "змін до форми", "затвердження форми", "нової форми")
        )
        if result.relevant or not (names_tax_declaration and changes_form_or_rules):
            return result
        categories = list(result.categories)
        if RelevanceCategory.TAX_REPORTING not in categories:
            categories.append(RelevanceCategory.TAX_REPORTING)
        return result.model_copy(
            update={
                "relevant": True,
                "categories": categories,
                "reason": "Назва вказує на зміни до форми податкової декларації; документ передано на аналіз звітності.",
                "confidence": max(result.confidence, 0.9),
            }
        )

    def _clip(self, text: str) -> str:
        return text if len(text) <= self.max_input_chars else text[: self.max_input_chars]

    def _extract_result(self, data: dict) -> dict:
        if {"relevant", "reason", "confidence"}.issubset(data):
            return data
        for key in ("result", "relevance", "classification"):
            nested = data.get(key)
            if isinstance(nested, dict):
                return nested
        return data
