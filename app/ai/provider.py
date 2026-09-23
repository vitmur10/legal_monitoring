from abc import ABC, abstractmethod
import asyncio
import json
import logging
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.http import system_ssl_context

logger = logging.getLogger(__name__)


class UsageMetadata(BaseModel):
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    request_type: str
    document_id: int | None = None
    version_id: int | None = None


class AIResponse(BaseModel):
    data: dict[str, Any]
    usage: UsageMetadata
    raw_model: str | None = None


class AIProviderError(RuntimeError):
    pass


class AIProvider(ABC):
    @abstractmethod
    async def structured_json(
        self,
        *,
        request_type: str,
        model: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        max_output_tokens: int | None = None,
        document_id: int | None = None,
        version_id: int | None = None,
    ) -> AIResponse:
        raise NotImplementedError


class OpenAICompatibleProvider(AIProvider):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        default_max_output_tokens: int | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.default_max_output_tokens = default_max_output_tokens

    async def structured_json(
        self,
        *,
        request_type: str,
        model: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        max_output_tokens: int | None = None,
        document_id: int | None = None,
        version_id: int | None = None,
    ) -> AIResponse:
        payload = {
            "model": model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False, default=str),
                },
            ],
        }
        output_limit = max_output_tokens or self.default_max_output_tokens
        if output_limit is not None:
            payload["max_tokens"] = output_limit
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds,
                    verify=system_ssl_context(),
                ) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions", headers=headers, json=payload
                    )
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise AIProviderError(f"transient_ai_error status={response.status_code}")
                if response.status_code >= 400:
                    raise AIProviderError(f"ai_request_failed status={response.status_code}")
                body = response.json()
                content = body["choices"][0]["message"]["content"]
                usage = body.get("usage") or {}
                logger.info(
                    "ai_usage request_type=%s model=%s document_id=%s version_id=%s total_tokens=%s",
                    request_type,
                    model,
                    document_id,
                    version_id,
                    usage.get("total_tokens"),
                )
                return AIResponse(
                    data=json.loads(content),
                    raw_model=body.get("model"),
                    usage=UsageMetadata(
                        model=model,
                        input_tokens=usage.get("prompt_tokens"),
                        output_tokens=usage.get("completion_tokens"),
                        total_tokens=usage.get("total_tokens"),
                        request_type=request_type,
                        document_id=document_id,
                        version_id=version_id,
                    ),
                )
            except (httpx.TimeoutException, httpx.TransportError, AIProviderError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                await asyncio.sleep(0.5 * (attempt + 1))
            except (KeyError, json.JSONDecodeError) as exc:
                raise AIProviderError("ai_response_not_valid_json") from exc
        raise AIProviderError(str(last_error) if last_error else "ai_request_failed")
