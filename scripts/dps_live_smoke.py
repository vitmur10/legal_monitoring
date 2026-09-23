import asyncio

from app.sources.dps.client import DpsHTTPError
from app.sources.dps.adapter import DpsAdapter
from app.utils.hashing import sha256_text


async def main() -> None:
    adapter = DpsAdapter(max_pages_per_section=1)
    try:
        items = await adapter.fetch_items()
        print(
            "discovery count={count} sample={sample}".format(
                count=len(items),
                sample=[item.external_id for item in items[:5]],
            )
        )
    except DpsHTTPError as exc:
        print(f"discovery failed status={exc.status_code} url={exc.url}")
    except Exception as exc:
        print(f"discovery failed error={exc}")

    for page_id in ["80085", "80205", "80206", "80200", "1025759"]:
        try:
            raw = await adapter.fetch_by_page_id(page_id)
            normalized = await adapter.normalize(raw)
            print(
                "{page_id} external_id={external_id} type={document_type} "
                "title_len={title_len} content_len={content_len} published={published} "
                "effective={effective} attachments={attachments} refs={refs} relations={relations} "
                "hash={content_hash}".format(
                    page_id=page_id,
                    external_id=normalized.external_id,
                    document_type=normalized.document_type,
                    title_len=len(normalized.title),
                    content_len=len(normalized.content),
                    published=normalized.published_at.isoformat()
                    if normalized.published_at
                    else None,
                    effective=normalized.effective_at.isoformat()
                    if normalized.effective_at
                    else None,
                    attachments=len(normalized.metadata.get("attachments", [])),
                    refs=[
                        (ref.get("issuer"), ref.get("number"), ref.get("date"))
                        for ref in normalized.metadata.get("references", [])
                    ],
                    relations=[
                        (rel.get("from_external_id"), rel.get("relation_type"), rel.get("to_external_id"))
                        for rel in normalized.metadata.get("relation_candidates", [])
                    ],
                    content_hash=sha256_text(normalized.content),
                )
            )
        except DpsHTTPError as exc:
            print(f"{page_id} failed status={exc.status_code} url={exc.url}")
        except Exception as exc:
            print(f"{page_id} failed error={exc}")


if __name__ == "__main__":
    asyncio.run(main())
