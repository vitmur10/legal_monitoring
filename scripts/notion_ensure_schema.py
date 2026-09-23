"""Create any missing Ukrainian Knowledge Base properties without publishing a page."""
import asyncio

from app.core.config import get_settings
from app.notion.client import NotionClient


async def main() -> None:
    settings = get_settings()
    client = NotionClient(
        token=settings.notion_token,
        database_id=settings.notion_database_id,
        enabled=True,
        timeout_seconds=settings.notion_timeout_seconds,
        property_map=settings.notion_property_map,
    )
    if not client.configured:
        raise SystemExit("Notion не налаштовано: перевірте NOTION_ENABLED, NOTION_TOKEN і NOTION_DATABASE_ID")
    await client.ensure_database_schema()
    print("Схему Бази знань перевірено й оновлено; сторінки не створювалися.")


if __name__ == "__main__":
    asyncio.run(main())
