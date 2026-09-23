"""Create a source-backed Stage 4 moderation case from ZIR 41820."""

import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai.stage2_service import create_stage2_service_from_settings
from app.db.session import AsyncSessionLocal
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.enums import ProcessingStatus
from app.sources.zir.adapter import ZirAdapter
from app.sources.zir.client import ZirClient
from app.stage3.factory import create_review_service
from app.utils.hashing import sha256_text


async def main(run_id: str) -> None:
    async with ZirClient() as source_client:
        adapter = ZirAdapter(client=source_client)
        raw = await adapter.fetch_by_id("41820", "ques")
        normalized = await adapter.normalize(raw)

    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)
        source_document = (
            await session.execute(
                select(Document).where(Document.canonical_url == normalized.canonical_url)
            )
        ).scalars().first()
        if source_document is None:
            raise RuntimeError("The source-backed ZIR 41820 smoke record was not found")

        document = Document(
            source_id=source_document.source_id,
            identity_key=f"stage4-moderation:zir:41820:{run_id}",
            identity_type="stage4_acceptance",
            external_id=f"41820-stage4-{run_id}",
            canonical_url=f"{normalized.canonical_url}#stage4-{run_id}",
            title=f"[Stage 4 — тест] {normalized.title}",
            document_type=normalized.document_type,
            published_at=normalized.published_at,
            effective_at=normalized.effective_at,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(document)
        await session.flush()

        version = DocumentVersion(
            document_id=document.id,
            version_number=1,
            raw_content=raw.content or normalized.content,
            normalized_content=normalized.content,
            content_hash=sha256_text(normalized.content),
            version_metadata={
                "acceptance_case": "ZIR_41820",
                "official_source_url": normalized.canonical_url,
            },
            detected_at=now,
        )
        session.add(version)
        await session.flush()
        document.current_version_id = version.id

        stage2_service = create_stage2_service_from_settings()
        if stage2_service is None:
            raise RuntimeError("AI Stage 2 is not configured")
        # The acceptance card must stay source-backed even if free-form content
        # generation fails validation. AI still performs relevance and analysis.
        stage2_service.content_service = None
        stage2 = await stage2_service.process(
            status=ProcessingStatus.NEW,
            document=document,
            current_version=version,
            previous_version=None,
            source_code="zir",
        )
        if not stage2 or stage2.get("status") != "ANALYZED":
            status = (stage2 or {}).get("status", "NO_RESULT")
            reason = ((stage2 or {}).get("relevance") or {}).get("reason", "")
            raise RuntimeError(f"AI analysis status={status}; reason={reason}")
        recommendation = (stage2.get("analysis") or {}).get(
            "knowledge_base_recommendation"
        ) or {
            "recommendation": "OPTIONAL",
            "reason": "Офіційне роз’яснення ДПС може бути корисним у Базі знань; остаточне рішення приймає користувач.",
            "confidence": 0.7,
        }
        stage2["content"] = {
            "knowledge_base_recommendation": recommendation,
            "telegram_post": (
                "📌 ФОП-єдинники мають зберігати первинні документи\n\n"
                "Що сталося: ДПС у ЗІР роз’яснила вимоги до зберігання первинних документів для ФОП — платників єдиного податку.\n\n"
                "Що змінилося: це офіційне роз’яснення, а не новий нормативний акт. ДПС нагадує, що мінімальні строки визначає ст. 44 ПКУ: залежно від виду документів — 1095, 1825 або 2555 днів.\n\n"
                "Кого стосується: ФОП на ЄП 1–2 груп та 3 групи, які не є платниками ПДВ, крім е-резидентів.\n\n"
                "Практичний вплив: за незберігання документів, на підставі яких вівся облік доходів, п. 121.1 ПКУ передбачає штраф 1020 грн, а за повторне порушення протягом року — 2040 грн. У роз’ясненні окремо наведені винятки для документів на витрати та спеціальні правила для територій бойових дій чи окупації.\n\n"
                "Що зробити: визначити строк зберігання для кожного типу документа, не формувати звітність за непідтвердженими даними та забезпечити паперове або електронне зберігання.\n\n"
                f"Офіційне джерело: {normalized.canonical_url}"
            ),
            "knowledge_base_article": normalized.content,
            "content_warnings": [],
        }
        metadata = dict(version.version_metadata or {})
        metadata["stage2"] = stage2
        version.version_metadata = metadata
        await session.flush()

        result = await create_review_service(session).dispatch_to_moderation(version.id)
        await session.commit()
        print(f"document_id={document.id}")
        print(f"version_id={version.id}")
        print(f"moderation_message_id={result.message_id}")
        print("moderation_status=SENT")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.run_id))
