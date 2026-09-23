from pydantic import ValidationError

from app.ai.prompts import CONTENT_PROMPT_VERSION, CONTENT_SYSTEM_PROMPT
from app.ai.provider import AIProvider, AIResponse
from app.ai.schemas import ContentGenerationResult, FullAnalysisResult, Stage2Input


class AIContentService:
    def __init__(
        self,
        provider: AIProvider,
        model: str,
        max_output_tokens: int | None = 2600,
    ) -> None:
        self.provider = provider
        self.model = model
        self.max_output_tokens = max_output_tokens

    async def generate(
        self,
        stage_input: Stage2Input,
        analysis: FullAnalysisResult,
        *,
        revision_comment: str | None = None,
        current_content: ContentGenerationResult | None = None,
        previous_content: ContentGenerationResult | None = None,
    ) -> tuple[ContentGenerationResult, AIResponse]:
        payload = {
            "schema_version": CONTENT_PROMPT_VERSION,
            "source": stage_input.source_code,
            "title": stage_input.title,
            "official_url": str(stage_input.official_url) if stage_input.official_url else None,
            "analysis": analysis.model_dump(mode="json"),
            "instruction": (
                "Згенеруй два готові тексти на основі analysis: "
                "1) knowledge_base_article - розгорнута стаття для Бази знань; "
                "2) telegram_post - практичний експрес-аналіз для Telegram. "
                "Не додавай фактів поза analysis."
            ),
            "output_schema": {
                "knowledge_base_recommendation": "object: recommendation (RECOMMENDED/OPTIONAL/NOT_RECOMMENDED), reason, confidence 0..1; copy analysis",
                "knowledge_base_article": (
                    "string, structured article with title, short context, what changed, "
                    "who is affected, practical impact, actions, risks, source"
                ),
                "telegram_post": "string, concise Telegram-ready text with key facts and source",
                "content_warnings": "array of strings for missing/uncertain information",
            },
        }
        if revision_comment is not None:
            direction = self._revision_direction(revision_comment)
            payload["revision"] = {
                "comment": revision_comment,
                "current_content": current_content.model_dump(mode="json")
                if current_content
                else None,
                "previous_content": previous_content.model_dump(mode="json")
                if previous_content
                else None,
                "current_lengths": {
                    "knowledge_base_article": len(current_content.knowledge_base_article),
                    "telegram_post": len(current_content.telegram_post),
                }
                if current_content
                else None,
                "length_requirement": self._length_requirement(direction, current_content),
                "instruction": (
                    "Перегенеруй обидва тексти з урахуванням коментаря редактора. "
                    "Коментар може змінювати структуру і стиль, але не є джерелом нових "
                    "юридичних фактів. Усі факти мають залишатися в межах analysis. "
                    "Якщо редактор просить зробити текст коротшим або докладнішим, "
                    "зміна обсягу має бути помітною порівняно з current_content, але "
                    "обидва формати мають залишатися у своїх установлених межах. "
                    "Не замінюй конкретні факти загальними фразами. Telegram-текст "
                    "має адаптувати структуру до документа і пояснювати практичний вплив."
                ),
            }
        response: AIResponse | None = None
        last_error: Exception | None = None
        for attempt in range(2):
            retry_payload = payload if attempt == 0 else {**payload, "validation_error": str(last_error)}
            response = await self.provider.structured_json(
                request_type="content_generation",
                model=self.model,
                system_prompt=CONTENT_SYSTEM_PROMPT,
                user_payload=retry_payload,
                max_output_tokens=self.max_output_tokens,
                document_id=stage_input.document_id,
                version_id=stage_input.current_version_id,
            )
            try:
                generated = ContentGenerationResult.model_validate(
                    self._extract_result(response.data)
                )
            except ValidationError as exc:
                last_error = exc
                continue
            generated = self._ensure_official_source(
                generated,
                str(stage_input.official_url)
                if stage_input.official_url
                else analysis.official_source_url,
            )
            generated = self._explain_sparse_source(
                generated, stage_input, analysis, revision_comment=revision_comment
            )
            format_error = self._validate_format(
                generated,
                analysis,
                revision_comment=revision_comment,
                current_content=current_content,
            )
            if format_error is None:
                generated.knowledge_base_recommendation = analysis.knowledge_base_recommendation
                return generated, response
            last_error = ValueError(format_error)
        raise last_error or RuntimeError("Content generation failed")

    def _explain_sparse_source(
        self,
        generated: ContentGenerationResult,
        stage_input: Stage2Input,
        analysis: FullAnalysisResult,
        *,
        revision_comment: str | None = None,
    ) -> ContentGenerationResult:
        article_min = 600 if revision_comment else 1200
        if len(generated.knowledge_base_article) >= article_min or generated.content_warnings:
            return generated
        if len(stage_input.normalized_text.strip()) >= article_min:
            return generated

        missing = [item.strip() for item in analysis.missing_information if item.strip()]
        if missing:
            detail = "; ".join(missing[:3])
            warning = (
                f"У доступному тексті джерела бракує таких відомостей: {detail}. "
                "Статтю обмежено підтвердженими фактами; перед використанням звірте її "
                "з повним текстом документа."
            )
        else:
            warning = (
                "Джерело містить лише короткий опис, а не повний текст документа. Статтю "
                "обмежено доступними фактами; перед використанням звірте її з повним "
                "текстом документа."
            )
        return generated.model_copy(update={"content_warnings": [warning]})

    def _extract_result(self, data: dict) -> dict:
        if {"knowledge_base_article", "telegram_post"}.issubset(data):
            return data
        for key in ("result", "content", "generated_content"):
            nested = data.get(key)
            if isinstance(nested, dict):
                return nested
        return data

    @staticmethod
    def _ensure_official_source(
        generated: ContentGenerationResult,
        official_url: str | None,
    ) -> ContentGenerationResult:
        if not official_url or official_url in generated.telegram_post:
            return generated
        post = generated.telegram_post.rstrip() + f"\n\nДжерело: {official_url}"
        return generated.model_copy(update={"telegram_post": post})

    def _validate_format(
        self,
        generated: ContentGenerationResult,
        analysis: FullAnalysisResult,
        *,
        revision_comment: str | None = None,
        current_content: ContentGenerationResult | None = None,
    ) -> str | None:
        problems: list[str] = []
        telegram_min = 300 if revision_comment else 450
        article_min = 600 if revision_comment else 1200
        if len(generated.telegram_post) > 3000 or (len(generated.telegram_post) < telegram_min and not generated.content_warnings):
            problems.append("telegram_post має містити до 3000 символів; короткий текст потребує content_warnings")
        if len(generated.knowledge_base_article) < article_min and not generated.content_warnings:
            problems.append(
                f"knowledge_base_article має містити щонайменше {article_min} символів або "
                "content_warnings має пояснювати нестачу фактів"
            )
        direction = self._revision_direction(revision_comment)
        if current_content is not None and direction == "SHORTER":
            article_limit = int(len(current_content.knowledge_base_article) * 0.9)
            telegram_limit = int(len(current_content.telegram_post) * 0.9)
            if len(generated.knowledge_base_article) > article_limit:
                problems.append(
                    f"knowledge_base_article має бути не довшим за {article_limit} символів"
                )
            if len(generated.telegram_post) > telegram_limit:
                problems.append(f"telegram_post має бути не довшим за {telegram_limit} символів")
        if current_content is not None and direction == "LONGER":
            article_minimum = int(len(current_content.knowledge_base_article) * 1.1)
            if len(generated.knowledge_base_article) < article_minimum:
                problems.append(
                    f"knowledge_base_article має містити щонайменше {article_minimum} символів"
                )
        return "; ".join(problems) or None

    @staticmethod
    def _revision_direction(comment: str | None) -> str | None:
        normalized = " ".join((comment or "").casefold().split())
        if any(word in normalized for word in ("коротш", "скорот", "стисліш", "стисни")):
            return "SHORTER"
        if any(
            word in normalized
            for word in ("розгорнут", "детальніш", "детальним", "докладніш", "довш", "збільш")
        ):
            return "LONGER"
        return None

    @staticmethod
    def _length_requirement(
        direction: str | None,
        current_content: ContentGenerationResult | None,
    ) -> dict[str, int | str] | None:
        if current_content is None or direction is None:
            return None
        if direction == "SHORTER":
            return {
                "direction": direction,
                "knowledge_base_article_max": int(
                    len(current_content.knowledge_base_article) * 0.9
                ),
                "telegram_post_max": int(len(current_content.telegram_post) * 0.9),
            }
        return {
            "direction": direction,
            "knowledge_base_article_min": int(
                len(current_content.knowledge_base_article) * 1.1
            ),
        }
