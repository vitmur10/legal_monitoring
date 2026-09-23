from app.knowledge_base.service import KnowledgeBaseService
from app.repositories.document_repository import DocumentRepository
from app.stage3.review_service import ReviewService
from app.stage3.schemas import ReviewDecisionRequest
from tests.integration.test_review_api import seed_review_item
from tests.unit.test_stage3_telegram_workflow import FakeTelegram
from tests.unit.test_stage4_knowledge_base import Adapter


async def test_telegram_commit_survives_knowledge_base_transaction_rollback(session_factory):
    telegram, adapter = FakeTelegram(), Adapter(fail=True)
    async with session_factory() as session:
        version_id = await seed_review_item(session)
        service = ReviewService(DocumentRepository(session), telegram,
                                knowledge_base_service=KnowledgeBaseService(adapter))
        first = await service.approve_and_publish(version_id, ReviewDecisionRequest(), include_knowledge_base=True)
        assert first.knowledge_base_status == "FAILED"
        # Lose the independent KB transaction: Telegram success must remain durable.
        await session.rollback()
    async with session_factory() as session:
        service = ReviewService(DocumentRepository(session), telegram,
                                knowledge_base_service=KnowledgeBaseService(adapter))
        second = await service.approve_and_publish(version_id, ReviewDecisionRequest(), include_knowledge_base=True)
        await session.commit()
        assert second.message_id == first.message_id
        assert second.knowledge_base_status == "PUBLISHED"
        assert telegram.publications == 1
