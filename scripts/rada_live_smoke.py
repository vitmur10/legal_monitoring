import asyncio

from app.sources.rada.adapter import RadaAdapter
from app.utils.hashing import sha256_text


async def main() -> None:
    adapter = RadaAdapter(discovery_limit=3)
    cases = [
        ("2755-17", None),
        ("2755-17", "2026-01-01"),
        ("2755-17", "2026-04-15"),
        ("4835-20", None),
    ]
    for nreg, revision in cases:
        document = await adapter.fetch_by_nreg(nreg, revision)
        normalized = await adapter.normalize(document)
        print(
            "{nreg} {revision} title_len={title_len} content_len={content_len} "
            "url={url} revision_date={revision_date} effective_at={effective_at} "
            "basis={basis} relations={relations} historical_relations={historical_relations} "
            "hash={content_hash}".format(
                nreg=nreg,
                revision=revision or "current",
                title_len=len(normalized.title),
                content_len=len(normalized.content),
                url=normalized.canonical_url,
                revision_date=normalized.metadata.get("revision_date"),
                effective_at=normalized.effective_at.isoformat()
                if normalized.effective_at
                else None,
                basis=normalized.metadata.get("specific_revision_basis_nregs"),
                relations=len(normalized.metadata.get("relation_candidates", [])),
                historical_relations=len(
                    normalized.metadata.get("historical_relation_candidates", [])
                ),
                content_hash=sha256_text(normalized.content),
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
