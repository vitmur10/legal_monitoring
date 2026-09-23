from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

import httpx

from app.core.http import system_ssl_context
from app.knowledge_base.service import KnowledgeBasePublicationResult
from app.knowledge_base.labels import label
from app.knowledge_base.errors import PublicationRejected


NotionPublicationResult = KnowledgeBasePublicationResult


class NotionClient:
    API_VERSION = "2026-03-11"
    def __init__(self, *, token: str | None, database_id: str | None,
                 enabled: bool = False, timeout_seconds: float = 30.0,
                 property_map: str = "") -> None:
        self.token = token
        self.database_id = database_id
        self.enabled = enabled
        self.timeout_seconds = timeout_seconds
        self.property_map = self._parse_map(property_map)

    @staticmethod
    def _parse_map(value: str) -> dict[str, str]:
        if not value:
            return {}
        try:
            parsed = json.loads(value)
            return {str(k): str(v) for k, v in parsed.items()}
        except (TypeError, ValueError):
            return {}

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.token and self.database_id)

    @staticmethod
    def content_version(document_id: int, version_id: int, content: str) -> str:
        return sha256(f"{document_id}:{version_id}:{content}".encode()).hexdigest()

    async def publish(self, *, document_id: int, version_id: int, content_version: int,
                      title: str, analysis: dict[str, Any], article: str,
                      telegram_message_id: str | None, previous_page_id: str | None = None) -> NotionPublicationResult:
        if not self.configured:
            return NotionPublicationResult(status="NOT_CONFIGURED", error="Notion is not configured")
        version_key = sha256(f"{document_id}:{version_id}:{content_version}".encode()).hexdigest()
        creating = False
        try:
            existing = await self._find_existing(version_key)
            if existing:
                return NotionPublicationResult(status="PUBLISHED", page_id=existing["id"], page_url=existing.get("url"))
            payload = self._page_payload(title, analysis, article, document_id, version_id,
                                         content_version, version_key, telegram_message_id, previous_page_id)
            creating = True
            body = await self._request("POST", "/pages", payload)
            return NotionPublicationResult(status="PUBLISHED", page_id=body["id"], page_url=body.get("url"),
                                           published_at=datetime.now(timezone.utc))
        except PublicationRejected:
            return NotionPublicationResult(status="FAILED", error="Notion відхилив запит; перевірте доступ і схему бази")
        except Exception:
            return NotionPublicationResult(status="UNKNOWN" if creating else "FAILED", error="Результат Notion невідомий; потрібна звірка" if creating else "Помилка читання Notion; сторінку не створювали")

    async def _find_existing(self, version_key: str) -> dict[str, Any] | None:
        body = await self._request("POST", f"/data_sources/{self.database_id}/query", {
            "filter": {"property": self.property_map.get("Version ID", "Ключ редакції"),
                        "rich_text": {"equals": version_key}}, "page_size": 1})
        return (body.get("results") or [None])[0]

    async def ensure_database_schema(self) -> None:
        """Explicit setup operation; ordinary publishing never mutates database schema."""
        data_source = await self._request("GET", f"/data_sources/{self.database_id}", {})
        existing = data_source.get("properties") or {}
        sample = self._page_payload("Назва", {}, "Текст", 0, 0, 1, "key", None, None)
        changes = {}
        title_name = next((name for name, prop in existing.items() if prop.get("type") == "title"), None)
        for name, value in sample["properties"].items():
            kind = next(iter(value))
            if name in existing:
                if existing[name].get("type") != kind:
                    raise RuntimeError(f"Неправильний тип поля: {name}")
                continue
            if kind == "title" and title_name:
                changes[title_name] = {"name": name}
            else:
                changes[name] = {kind: {}}
        await self._request("PATCH", f"/data_sources/{self.database_id}", {
            "title": [{"type": "text", "text": {"content": "TaxSignal UA | База знань"}}],
            "properties": changes,
        })

    def _page_payload(self, title: str, analysis: dict[str, Any], article: str, document_id: int,
                      version_id: int, content_version: int, version_key: str,
                      telegram_message_id: str | None, previous_page_id: str | None) -> dict[str, Any]:
        names = {"Name": "Назва", "Category": "Напрям", "Importance": "Важливість", "Document status": "Статус документа", "Affected entities": "Кого стосується", "Publication status": "Статус публікації", "Source URL": "Офіційне джерело", "Document ID": "Ідентифікатор документа", "Version ID": "Ключ редакції", "Telegram message ID": "Повідомлення Telegram"}
        p = lambda name: self.property_map.get(name, names.get(name, name))
        def text(value: Any) -> list[dict[str, Any]]:
            return [{"type": "text", "text": {"content": str(value or "не визначено")[:2000]}}]
        properties = {
            p("Name"): {"title": text(title)},
            p("Category"): {"multi_select": [{"name": label(x)} for x in analysis.get("categories") or []]},
            p("Importance"): {"select": {"name": label(analysis.get("importance"))}},
            p("Document status"): {"select": {"name": label(analysis.get("document_status"))}},
            p("Affected entities"): {"multi_select": [
                {"name": label(x)} for x in analysis.get("affected_entities") or []
            ]},
            p("Publication status"): {"select": {"name": "Опубліковано"}},
            p("Source URL"): {"url": analysis.get("official_source_url")},
            p("Document ID"): {"number": document_id}, p("Version ID"): {"rich_text": text(version_key)},
            p("Telegram message ID"): {"rich_text": text(telegram_message_id)},
        }
        for name, key in {"Дата документа": "document_date", "Дата набрання чинності": "effective_date", "Дата початку застосування": "application_date"}.items():
            value = analysis.get(key)
            properties[p(name)] = {"date": {"start": str(value)} if value else None}
        source_published_at = analysis.get("source_published_at")
        properties[p("Дата публікації джерела")] = {
            "date": {"start": str(source_published_at)} if source_published_at else None
        }
        for name, value in {
            "Номер документа": analysis.get("document_number"),
            "Що змінилося": "\n".join(x.get("explanation", "") for x in analysis.get("changes") or []),
            "Практичний вплив": analysis.get("practical_impact"),
            "Необхідні дії": "\n".join(analysis.get("required_actions") or []),
            "Строки": "\n".join(f"{x.get('date') or 'Дата не визначена'}: {x.get('description', '')}" for x in analysis.get("deadlines") or []),
            "Ризики": "\n".join(x.get("description", "") for x in analysis.get("risks") or []),
            "Повний текст статті": article, "Попередня редакція": previous_page_id,
        }.items():
            value = str(value or "Не визначено")
            properties[p(name)] = {"rich_text": [{"type": "text", "text": {"content": value[i:i+1900]}} for i in range(0, len(value), 1900)]}
        properties[p("Тип документа")] = {"select": {"name": label(analysis.get("document_type"))}}
        properties[p("Орган")] = {"select": {"name": label(analysis.get("issuing_authority"))}}
        properties[p("Теми")] = {"multi_select": [
            {"name": label(x)} for x in analysis.get("topics") or []
        ]}
        recommendation = analysis.get("knowledge_base_recommendation") or {}
        properties[p("Рекомендація щодо Бази")] = {"select": {"name": label(recommendation.get("recommendation", "OPTIONAL"))}}
        children = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": text(article[i:i+1900])}}
                    for i in range(0, len(article), 1900)]
        return {"parent": {"type": "data_source_id", "data_source_id": self.database_id}, "properties": properties,
                "children": children, "icon": {"type": "emoji", "emoji": "📚"}}

    async def _request(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.token}", "Notion-Version": self.API_VERSION, "Content-Type": "application/json"}
        last: Exception | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds, verify=system_ssl_context()) as client:
                    response = await client.request(method, f"https://api.notion.com/v1{path}", headers=headers, json=payload)
                if path != "/pages" and response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    await asyncio.sleep(0.2 * (attempt + 1)); continue
                if response.is_error:
                    if 400 <= response.status_code < 500 and response.status_code != 408:
                        raise PublicationRejected(f"Notion відхилив запит: HTTP {response.status_code}")
                    raise RuntimeError(f"Notion API HTTP {response.status_code}")
                return response.json()
            except (httpx.HTTPError, KeyError) as exc:
                last = exc
                if path != "/pages" and attempt < 2: await asyncio.sleep(0.2 * (attempt + 1)); continue
                raise
        raise last or RuntimeError("Notion request failed")
