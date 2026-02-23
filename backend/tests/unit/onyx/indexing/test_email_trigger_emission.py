from __future__ import annotations

import hashlib
from datetime import datetime
from datetime import timezone
from types import SimpleNamespace
from uuid import UUID
from uuid import uuid4
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import Document
from onyx.connectors.models import IndexAttemptMetadata
from onyx.connectors.models import TextSection
from onyx.indexing.adapters.document_indexing_adapter import (
    _build_email_crm_dedupe_key,
)
from onyx.indexing.adapters.document_indexing_adapter import (
    _extract_document_text,
)
from onyx.indexing.adapters.document_indexing_adapter import (
    _get_email_crm_custom_job_uuid,
)
from onyx.indexing.adapters.document_indexing_adapter import (
    DocumentIndexingBatchAdapter,
)
from onyx.indexing.indexing_pipeline import DocumentBatchPrepareContext
from onyx.indexing.models import BuildMetadataAwareChunksResult


def _make_doc(
    *,
    doc_id: str,
    source: DocumentSource,
    doc_updated_at: datetime | None = None,
) -> Document:
    return Document(
        id=doc_id,
        source=source,
        semantic_identifier="Quarterly Renewal",
        metadata={},
        doc_updated_at=doc_updated_at,
        sections=[TextSection(text="from: alice@example.com\nbody text")],
        primary_owners=[BasicExpertInfo(email="alice@example.com")],
        secondary_owners=[BasicExpertInfo(email="sales@example.com")],
    )


def _make_adapter(db_session: MagicMock) -> DocumentIndexingBatchAdapter:
    return DocumentIndexingBatchAdapter(
        db_session=db_session,
        connector_id=1,
        credential_id=2,
        tenant_id="public",
        index_attempt_metadata=IndexAttemptMetadata(
            connector_id=1,
            credential_id=2,
            batch_num=0,
            attempt_id=1,
        ),
    )


def _make_result() -> BuildMetadataAwareChunksResult:
    return BuildMetadataAwareChunksResult(
        chunks=[],
        doc_id_to_previous_chunk_cnt={},
        doc_id_to_new_chunk_cnt={},
        user_file_id_to_raw_text={},
        user_file_id_to_token_count={},
    )


def test_build_email_crm_dedupe_key_imap_uses_stable_message_key() -> None:
    doc = _make_doc(doc_id="imap-msg-1", source=DocumentSource.IMAP)
    assert _build_email_crm_dedupe_key(doc) == "imap:imap-msg-1"


def test_build_email_crm_dedupe_key_gmail_uses_doc_updated_at() -> None:
    updated_at = datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)
    doc = _make_doc(
        doc_id="gmail-thread-1",
        source=DocumentSource.GMAIL,
        doc_updated_at=updated_at,
    )
    assert _build_email_crm_dedupe_key(doc) == (
        f"gmail:gmail-thread-1:{updated_at.isoformat()}"
    )


def test_build_email_crm_dedupe_key_gmail_fallback_hash_when_missing_updated_at() -> None:
    doc = _make_doc(doc_id="gmail-thread-2", source=DocumentSource.GMAIL)
    expected_hash = hashlib.sha256(doc.id.encode()).hexdigest()[:12]
    assert _build_email_crm_dedupe_key(doc) == f"gmail:{doc.id}:{expected_hash}"


def test_extract_document_text_truncates_across_sections() -> None:
    doc = Document(
        id="doc-1",
        source=DocumentSource.FILE,
        semantic_identifier="doc",
        metadata={},
        sections=[
            TextSection(text="abc"),
            TextSection(text="def"),
            TextSection(text="xyz"),
        ],
    )
    assert _extract_document_text(doc, limit=5) == "abc\n\nde"


def test_post_index_emits_email_trigger_events_before_commit() -> None:
    db_session = MagicMock()
    adapter = _make_adapter(db_session=db_session)
    updated_at = datetime(2026, 2, 20, 15, 30, tzinfo=timezone.utc)
    email_doc = _make_doc(
        doc_id="gmail-thread-99",
        source=DocumentSource.GMAIL,
        doc_updated_at=updated_at,
    )
    non_email_doc = _make_doc(doc_id="file-doc-1", source=DocumentSource.FILE)
    context = DocumentBatchPrepareContext(
        updatable_docs=[email_doc, non_email_doc],
        id_to_boost_map={},
    )
    call_order: list[str] = []
    captured_events: list[dict] = []

    def _capture_event(**kwargs: object) -> SimpleNamespace:
        call_order.append("create_trigger_event")
        captured_events.append(kwargs)
        return SimpleNamespace(id=uuid4())

    db_session.commit.side_effect = lambda: call_order.append("commit")

    with (
        patch(
            "onyx.indexing.adapters.document_indexing_adapter.update_docs_updated_at__no_commit"
        ),
        patch(
            "onyx.indexing.adapters.document_indexing_adapter.update_docs_last_modified__no_commit"
        ),
        patch(
            "onyx.indexing.adapters.document_indexing_adapter.update_docs_chunk_count__no_commit"
        ),
        patch(
            "onyx.indexing.adapters.document_indexing_adapter.mark_document_as_indexed_for_cc_pair__no_commit"
        ),
        patch(
            "onyx.indexing.adapters.document_indexing_adapter.update_chunk_boost_components__no_commit"
        ),
        patch(
            "onyx.indexing.adapters.document_indexing_adapter._get_email_crm_custom_job_uuid",
            return_value=UUID("11111111-1111-1111-1111-111111111111"),
        ),
        patch(
            "onyx.indexing.adapters.document_indexing_adapter.create_trigger_event",
            side_effect=_capture_event,
        ),
    ):
        adapter.post_index(
            context=context,
            updatable_chunk_data=[],
            filtered_documents=[email_doc, non_email_doc],
            result=_make_result(),
        )

    assert call_order == ["create_trigger_event", "commit"]
    assert len(captured_events) == 1

    event_kwargs = captured_events[0]
    assert event_kwargs["source_type"] == "email_indexed"
    assert event_kwargs["source_event_id"] == "gmail-thread-99"
    assert event_kwargs["dedupe_key"].startswith("gmail:gmail-thread-99:")
    payload = event_kwargs["payload_json"]
    assert isinstance(payload, dict)
    assert payload["from"] == "alice@example.com"
    assert payload["to"] == "sales@example.com"
    assert payload["subject"] == "Quarterly Renewal"
    assert payload["date"] == updated_at.isoformat()
    assert payload["body"]
    assert payload["source"] == "gmail"


def test_post_index_skips_trigger_emission_when_job_id_not_configured() -> None:
    db_session = MagicMock()
    adapter = _make_adapter(db_session=db_session)
    email_doc = _make_doc(doc_id="imap-msg-2", source=DocumentSource.IMAP)
    context = DocumentBatchPrepareContext(
        updatable_docs=[email_doc],
        id_to_boost_map={},
    )

    with (
        patch(
            "onyx.indexing.adapters.document_indexing_adapter.update_docs_updated_at__no_commit"
        ),
        patch(
            "onyx.indexing.adapters.document_indexing_adapter.update_docs_last_modified__no_commit"
        ),
        patch(
            "onyx.indexing.adapters.document_indexing_adapter.update_docs_chunk_count__no_commit"
        ),
        patch(
            "onyx.indexing.adapters.document_indexing_adapter.mark_document_as_indexed_for_cc_pair__no_commit"
        ),
        patch(
            "onyx.indexing.adapters.document_indexing_adapter.update_chunk_boost_components__no_commit"
        ),
        patch(
            "onyx.indexing.adapters.document_indexing_adapter._get_email_crm_custom_job_uuid",
            return_value=None,
        ),
        patch(
            "onyx.indexing.adapters.document_indexing_adapter.create_trigger_event"
        ) as mock_create_trigger_event,
    ):
        adapter.post_index(
            context=context,
            updatable_chunk_data=[],
            filtered_documents=[email_doc],
            result=_make_result(),
        )

    mock_create_trigger_event.assert_not_called()
    db_session.commit.assert_called_once()


def test_get_email_crm_custom_job_uuid_invalid_value_returns_none() -> None:
    _get_email_crm_custom_job_uuid.cache_clear()
    try:
        with (
            patch(
                "onyx.indexing.adapters.document_indexing_adapter.EMAIL_CRM_CUSTOM_JOB_ID",
                "definitely-not-a-uuid",
            ),
            patch("onyx.indexing.adapters.document_indexing_adapter.logger.error") as mock_error,
        ):
            parsed = _get_email_crm_custom_job_uuid()
            assert parsed is None
            mock_error.assert_called_once()
    finally:
        _get_email_crm_custom_job_uuid.cache_clear()
