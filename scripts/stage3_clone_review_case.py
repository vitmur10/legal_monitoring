import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import AsyncSessionLocal
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.repositories.document_repository import DocumentRepository
from app.stage3.factory import create_review_service
from app.utils.hashing import sha256_text


async def main(source_version_id: int, run_id: str) -> None:
    async with AsyncSessionLocal() as session:
        repository = DocumentRepository(session)
        source_version = await repository.get_version_for_update(source_version_id)
        if source_version is None or source_version.document is None:
            raise RuntimeError("Source version not found")
        stage2 = deepcopy((source_version.version_metadata or {}).get("stage2"))
        if not stage2 or stage2.get("status") != "ANALYZED" or not stage2.get("content"):
            raise RuntimeError("Source version has no generated AI content")

        now = datetime.now(timezone.utc)
        source_document = source_version.document
        canonical_base = (source_document.canonical_url or "https://example.test").split("#", 1)[0]
        document = Document(
            source_id=source_document.source_id,
            identity_key=f"stage3-review:{run_id}",
            identity_type="stage3_review",
            external_id=f"stage3-review-{run_id}",
            canonical_url=f"{canonical_base}#stage3-review-{run_id}",
            title=f"[Тест Privacy Mode] {source_document.title.removeprefix('[Фінальний тест] ')}",
            document_type=source_document.document_type,
            published_at=source_document.published_at,
            effective_at=source_document.effective_at,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(document)
        await session.flush()
        version = DocumentVersion(
            document_id=document.id,
            version_number=1,
            raw_content=source_version.raw_content,
            normalized_content=source_version.normalized_content,
            content_hash=sha256_text(source_version.normalized_content),
            version_metadata={"stage2": stage2, "demo": "privacy_mode_acceptance"},
            detected_at=now,
        )
        session.add(version)
        await session.flush()
        document.current_version_id = version.id
        await create_review_service(session).dispatch_to_moderation(version.id)
        await session.commit()
        print(f"document_id={document.id}")
        print(f"version_id={version.id}")
        print("moderation_status=SENT")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-version", type=int, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.source_version, args.run_id))
