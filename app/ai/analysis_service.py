from pydantic import ValidationError

from app.ai.prompts import ANALYSIS_PROMPT_VERSION, ANALYSIS_SYSTEM_PROMPT
from app.ai.provider import AIProvider, AIResponse
from app.ai.schemas import FullAnalysisResult, RelevanceResult, Stage2Input
from app.diff.schemas import DocumentDiffResult


class AIAnalysisService:
    def __init__(
        self,
        provider: AIProvider,
        model: str,
        max_input_chars: int = 36000,
        max_output_tokens: int | None = 2200,
    ) -> None:
        self.provider = provider
        self.model = model
        self.max_input_chars = max_input_chars
        self.max_output_tokens = max_output_tokens

    async def analyze(
        self,
        stage_input: Stage2Input,
        relevance: RelevanceResult,
        diff: DocumentDiffResult | None = None,
    ) -> tuple[FullAnalysisResult, AIResponse]:
        payload = {
            "schema_version": ANALYSIS_PROMPT_VERSION,
            "source": stage_input.source_code,
            "document_type": stage_input.document_type,
            "title": stage_input.title,
            "metadata": stage_input.metadata,
            "official_url": str(stage_input.official_url) if stage_input.official_url else None,
            "relevance": relevance.model_dump(mode="json"),
            "diff": diff.model_dump(mode="json") if diff else None,
            "normalized_text": self._text_for_analysis(stage_input, diff),
            "instruction": (
                "Поверни структурований результат українською. Усі поля нижче мають бути "
                "присутні на верхньому рівні JSON. Якщо даних немає, для текстових полів "
                'використовуй "не визначено", для дат null, для масивів [].'
            ),
            "output_schema": {
                "knowledge_base_recommendation": {"recommendation": "RECOMMENDED | OPTIONAL | NOT_RECOMMENDED", "reason": "string in Ukrainian; user decides", "confidence": "0.0-1.0"},
                "application_date": "YYYY-MM-DD or null",
                "document_number": "string or null",
                "document_type": "string in Ukrainian or null",
                "issuing_authority": "string in Ukrainian or null",
                "topics": "array of strings in Ukrainian",
                "relevant": "boolean",
                "categories": "array of relevance category enum values",
                "document_status": (
                    "DRAFT | ADOPTED | SIGNED | PUBLISHED | EFFECTIVE | EXPIRED | "
                    "NON_CURRENT | EXPLANATION | OTHER | NOT_DETERMINED"
                ),
                "document_date": "YYYY-MM-DD or null",
                "effective_date": "YYYY-MM-DD or null",
                "summary": "string",
                "changes": [
                    {
                        "provision": "string or null",
                        "before": "string or null",
                        "after": "string or null",
                        "explanation": "string",
                        "evidence": [
                            {
                                "version_id": "integer or null",
                                "text_excerpt": "string",
                                "source_url": "string or null",
                            }
                        ],
                    }
                ],
                "affected_entities": (
                    "array using ALL_TAXPAYERS, LEGAL_ENTITIES, VAT_PAYERS, "
                    "CORPORATE_INCOME_TAX_PAYERS, FOP, EMPLOYERS, TAX_AGENTS, "
                    "SINGLE_TAX_PAYERS, LARGE_TAXPAYERS, FINANCIAL_INSTITUTIONS, "
                    "INTERNATIONAL_BUSINESS, CONTROLLED_TRANSACTION_PARTICIPANTS, "
                    "CFC_OWNERS, SPECIFIC_INDUSTRY, OTHER"
                ),
                "affected_entities_explanation": "string",
                "practical_impact": "string",
                "required_actions": "array of strings",
                "deadlines": [{"date": "YYYY-MM-DD or null", "description": "string"}],
                "risks": [
                    {
                        "type": "financial | tax | penalty | reporting | operational | other",
                        "description": "string",
                    }
                ],
                "importance": "CRITICAL | HIGH | MEDIUM | LOW",
                "importance_reason": "string",
                "official_source_url": "string or null",
                "missing_information": "array of strings",
                "confidence": "0.0-1.0",
            },
        }
        response: AIResponse | None = None
        last_error: ValidationError | None = None
        for attempt in range(2):
            retry_payload = payload if attempt == 0 else {**payload, "validation_error": str(last_error)}
            response = await self.provider.structured_json(
                request_type="analysis",
                model=self.model,
                system_prompt=ANALYSIS_SYSTEM_PROMPT,
                user_payload=retry_payload,
                max_output_tokens=self.max_output_tokens,
                document_id=stage_input.document_id,
                version_id=stage_input.current_version_id,
            )
            try:
                return FullAnalysisResult.model_validate(self._extract_result(response.data)), response
            except ValidationError as exc:
                last_error = exc
        raise last_error  # type: ignore[misc]

    def _text_for_analysis(self, stage_input: Stage2Input, diff: DocumentDiffResult | None) -> str:
        if diff and diff.changes:
            parts = []
            for change in diff.changes:
                before = change.previous_text or "null"
                after = change.current_text or "null"
                parts.append(f"{change.locator}\nБуло: {before}\nСтало: {after}")
            text = "\n\n".join(parts)
        else:
            text = stage_input.normalized_text
        return text if len(text) <= self.max_input_chars else text[: self.max_input_chars]

    def _extract_result(self, data: dict) -> dict:
        if {"document_status", "summary", "importance", "confidence"}.issubset(data):
            return data
        for key in ("result", "analysis"):
            nested = data.get(key)
            if isinstance(nested, dict):
                return nested
        return data
