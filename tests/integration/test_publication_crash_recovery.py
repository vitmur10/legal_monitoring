from datetime import datetime, timedelta, timezone
import copy
import asyncio

import pytest

from app.knowledge_base.service import KnowledgeBaseService
from app.repositories.document_repository import DocumentRepository
from app.stage3.review_service import ReviewService
from app.stage3.schemas import PublicationRecoveryRequest, PublicationStatus, ReviewDecisionRequest
from tests.integration.test_review_api import seed_review_item
from tests.integration.test_review_api import client_for
from app.core.config import get_settings
from app.main import app
from tests.unit.test_stage3_telegram_workflow import FakeTelegram
from tests.unit.test_stage4_knowledge_base import Adapter


class ProcessCrash(BaseException):
    pass


class CrashingTelegram(FakeTelegram):
    async def publish(self, **payload):
        await super().publish(**payload)
        raise ProcessCrash()


@pytest.mark.parametrize("outcome", ["PUBLISHED", "NOT_PUBLISHED"])
async def test_durable_marker_blocks_restart_until_explicit_reconciliation(session_factory, outcome):
    telegram = CrashingTelegram()
    async with session_factory() as session:
        version_id = await seed_review_item(session)
        service = ReviewService(DocumentRepository(session), telegram)
        with pytest.raises(ProcessCrash):
            await service.approve_and_publish(version_id, ReviewDecisionRequest())
        await session.rollback()
    async with session_factory() as session:
        service = ReviewService(DocumentRepository(session), telegram)
        repeated = await service.approve_and_publish(version_id, ReviewDecisionRequest())
        assert repeated.status == PublicationStatus.RECONCILIATION_REQUIRED
        assert telegram.publications == 1
        with pytest.raises(ValueError):
            await service.request_revision(version_id, reviewer="owner", reviewer_id=1, chat_id="test")
        version = await service.repository.get_version_for_update(version_id)
        metadata = copy.deepcopy(version.version_metadata)
        attempt = metadata["stage3"]["publication_attempts"]["telegram:1"]
        request = PublicationRecoveryRequest(target="telegram", content_version=1, attempt_id=attempt["attempt_id"],
            outcome=outcome, reference_id="201" if outcome == "PUBLISHED" else None,
            note="Оператор перевірив канал після зупинки попереднього worker", previous_worker_stopped=True)
        with pytest.raises(ValueError, match="5 хвилин"):
            await service.recover_publication(version_id, request)
        attempt["started_at"] = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        version.version_metadata = metadata
        await session.commit()
        recovered = await service.recover_publication(version_id, request)
        assert recovered.status == (PublicationStatus.PUBLISHED if outcome == "PUBLISHED" else PublicationStatus.APPROVED)
        with pytest.raises(ValueError, match="вже завершено"):
            await service.recover_publication(version_id, request)
    async with session_factory() as session:
        # Confirmed absence requires an explicit new user action; recovery sends nothing.
        safe_publisher = FakeTelegram()
        service = ReviewService(DocumentRepository(session), safe_publisher)
        result = await service.approve_and_publish(version_id, ReviewDecisionRequest())
        assert result.status == PublicationStatus.PUBLISHED
        assert safe_publisher.publications == (0 if outcome == "PUBLISHED" else 1)


async def test_timeout_is_unknown_and_cannot_be_retried(session_factory):
    class TimeoutTelegram(FakeTelegram):
        async def publish(self, **payload):
            await super().publish(**payload)
            raise TimeoutError("Bearer SECRET")
    telegram = TimeoutTelegram()
    async with session_factory() as session:
        version_id = await seed_review_item(session)
        service = ReviewService(DocumentRepository(session), telegram)
        first = await service.approve_and_publish(version_id, ReviewDecisionRequest())
        assert first.status == PublicationStatus.RECONCILIATION_REQUIRED
    async with session_factory() as session:
        service = ReviewService(DocumentRepository(session), telegram)
        second = await service.approve_and_publish(version_id, ReviewDecisionRequest())
        assert second.status == PublicationStatus.RECONCILIATION_REQUIRED and telegram.publications == 1
        version = await service.repository.get_version(version_id)
        assert "SECRET" not in str(version.version_metadata)


async def test_knowledge_base_crash_blocks_only_knowledge_base(session_factory):
    class CrashingAdapter(Adapter):
        async def publish(self, **payload):
            await super().publish(**payload)
            raise ProcessCrash()
    telegram, adapter = FakeTelegram(), CrashingAdapter()
    async with session_factory() as session:
        version_id = await seed_review_item(session)
        service = ReviewService(DocumentRepository(session), telegram, knowledge_base_service=KnowledgeBaseService(adapter))
        with pytest.raises(ProcessCrash):
            await service.approve_and_publish(version_id, ReviewDecisionRequest(), include_knowledge_base=True)
        await session.rollback()
    async with session_factory() as session:
        service = ReviewService(DocumentRepository(session), telegram, knowledge_base_service=KnowledgeBaseService(adapter))
        result = await service.approve_and_publish(version_id, ReviewDecisionRequest(), include_knowledge_base=True)
        assert result.status == PublicationStatus.PUBLISHED and result.knowledge_base_status == "UNKNOWN"
        assert telegram.publications == 1 and len(adapter.calls) == 1


async def test_database_failure_before_send_never_calls_provider(session_factory, monkeypatch):
    telegram = FakeTelegram()
    async with session_factory() as session:
        version_id = await seed_review_item(session)
        service = ReviewService(DocumentRepository(session), telegram)
        async def fail_commit():
            raise RuntimeError("database unavailable")
        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(RuntimeError):
            await service.approve_and_publish(version_id, ReviewDecisionRequest())
        assert telegram.publications == 0


async def test_concurrent_callback_sees_durable_sending_marker(file_session_factory):
    entered, release = asyncio.Event(), asyncio.Event()
    class WaitingTelegram(FakeTelegram):
        async def publish(self, **payload):
            entered.set()
            await release.wait()
            return await super().publish(**payload)
    telegram = WaitingTelegram()
    async with file_session_factory() as session:
        version_id = await seed_review_item(session)
        first_service = ReviewService(DocumentRepository(session), telegram)
        task = asyncio.create_task(first_service.approve_and_publish(version_id, ReviewDecisionRequest()))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            async with file_session_factory() as other_session:
                second_service = ReviewService(DocumentRepository(other_session), telegram)
                repeated = await second_service.approve_and_publish(version_id, ReviewDecisionRequest())
                assert repeated.status == PublicationStatus.RECONCILIATION_REQUIRED
        finally:
            release.set()
            first = await asyncio.wait_for(task, timeout=5)
        assert first.status == PublicationStatus.PUBLISHED and telegram.publications == 1


async def test_crash_during_success_commit_leaves_durable_sending(session_factory, monkeypatch):
    telegram = FakeTelegram()
    async with session_factory() as session:
        version_id = await seed_review_item(session)
        service = ReviewService(DocumentRepository(session), telegram)
        original_commit = session.commit
        commits = 0
        async def crash_on_second_commit():
            nonlocal commits
            commits += 1
            if commits == 2:
                raise ProcessCrash()
            await original_commit()
        monkeypatch.setattr(session, "commit", crash_on_second_commit)
        with pytest.raises(ProcessCrash):
            await service.approve_and_publish(version_id, ReviewDecisionRequest())
        await session.rollback()
    async with session_factory() as session:
        service = ReviewService(DocumentRepository(session), telegram)
        repeated = await service.approve_and_publish(version_id, ReviewDecisionRequest())
        assert repeated.status == PublicationStatus.RECONCILIATION_REQUIRED and telegram.publications == 1


async def test_recovery_api_authentication_and_attempt_validation(session, monkeypatch):
    version_id = await seed_review_item(session)
    repo = DocumentRepository(session)
    version = await repo.get_version(version_id)
    metadata = copy.deepcopy(version.version_metadata)
    metadata["stage3"] = {"content_version": 1, "status": "RECONCILIATION_REQUIRED", "publication_attempts": {
        "telegram:1": {"attempt_id": "test-attempt", "status": "UNKNOWN", "destination": "test-channel"}}}
    version.version_metadata = metadata
    await session.commit()
    payload = dict(target="telegram", content_version=1, attempt_id="test-attempt", outcome="PUBLISHED",
                   reference_id="201", note="Канал перевірено оператором вручну", previous_worker_stopped=True)
    try:
        async with await client_for(session) as client:
            path = f"/review/items/{version_id}/recover-publication"
            monkeypatch.setattr(get_settings(), "publication_recovery_secret", None)
            assert (await client.post(path, json=payload)).status_code == 503
            monkeypatch.setattr(get_settings(), "publication_recovery_secret", "test-recovery-secret")
            assert (await client.post(path, json=payload)).status_code == 403
            headers = {"X-Publication-Recovery-Secret": "test-recovery-secret"}
            assert (await client.post(path, json={**payload, "attempt_id": "wrong-attempt"}, headers=headers)).status_code == 409
            assert (await client.post(path, json={**payload, "reference_id": None}, headers=headers)).status_code == 409
            assert (await client.post(path, json={**payload, "previous_worker_stopped": False}, headers=headers)).status_code == 422
            success = await client.post(path, json=payload, headers=headers)
            assert success.status_code == 200 and success.json()["status"] == "PUBLISHED"
            assert (await client.post(path, json=payload, headers=headers)).status_code == 409
    finally:
        app.dependency_overrides.clear()


async def test_recovered_knowledge_base_page_is_not_created_again(session_factory):
    class UncertainAdapter(Adapter):
        async def publish(self, **payload):
            await super().publish(**payload)
            raise TimeoutError("response lost")
    telegram, adapter = FakeTelegram(), UncertainAdapter()
    async with session_factory() as session:
        version_id = await seed_review_item(session)
        service = ReviewService(DocumentRepository(session), telegram, knowledge_base_service=KnowledgeBaseService(adapter))
        result = await service.approve_and_publish(version_id, ReviewDecisionRequest(), include_knowledge_base=True)
        assert result.knowledge_base_status == "UNKNOWN"
    async with session_factory() as session:
        service = ReviewService(DocumentRepository(session), telegram, knowledge_base_service=KnowledgeBaseService(adapter))
        version = await service.repository.get_version_for_update(version_id)
        attempt = version.version_metadata["stage3"]["publication_attempts"]["knowledge_base:1"]
        await service.recover_publication(version_id, PublicationRecoveryRequest(
            target="knowledge_base", content_version=1, attempt_id=attempt["attempt_id"], outcome="PUBLISHED",
            reference_id="existing-page", page_url="https://example.test/page", note="Сторінку знайдено за ключем редакції", previous_worker_stopped=True))
        repeated = await service.approve_and_publish(version_id, ReviewDecisionRequest(), include_knowledge_base=True)
        assert repeated.knowledge_base_status == "PUBLISHED"
        assert telegram.publications == 1 and len(adapter.calls) == 1
