from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import (
    BasicExpertInfo,
    Document,
    IndexAttemptMetadata,
    TextSection,
)
from onyx.indexing.adapters.document_indexing_adapter import (
    DocumentIndexingBatchAdapter,
    _build_email_crm_dedupe_key,
    _extract_document_text,
    _get_email_crm_custom_job_uuid,
)
from onyx.indexing.indexing_pipeline import DocumentBatchPrepareContext
from onyx.indexing.models import ChunkEnrichmentContext


def _make_doc(
    *,
    doc_id: str,
    source: DocumentSource,
    doc_updated_at: datetime | None = None,
    section_text: str = "from: alice@example.com\nbody text",
    primary_owner_emails: list[str] | None = None,
    secondary_owner_emails: list[str] | None = None,
) -> Document:
    primary_emails = primary_owner_emails or ["alice@example.com"]
    secondary_emails = secondary_owner_emails or ["sales@example.com"]
    return Document(
        id=doc_id,
        source=source,
        semantic_identifier="Quarterly Renewal",
        metadata={},
        doc_updated_at=doc_updated_at,
        sections=[TextSection(text=section_text)],
        primary_owners=[BasicExpertInfo(email=email) for email in primary_emails],
        secondary_owners=[BasicExpertInfo(email=email) for email in secondary_emails],
    )


def _make_adapter() -> DocumentIndexingBatchAdapter:
    # NOTE: upstream's DocumentIndex interface refactor moved session ownership
    # out of __init__; each phase now receives a short-lived db_session as a
    # parameter. post_index(..., db_session=...) carries the session that the
    # email-CRM trigger emission + final commit use.
    return DocumentIndexingBatchAdapter(
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


def _make_result() -> ChunkEnrichmentContext:
    enrichment = MagicMock(spec=ChunkEnrichmentContext)
    enrichment.doc_id_to_previous_chunk_cnt = {}
    enrichment.doc_id_to_new_chunk_cnt = {}
    return enrichment


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


def test_build_email_crm_dedupe_key_gmail_fallback_hash_when_missing_updated_at() -> (
    None
):
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
    adapter = _make_adapter()
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
            enrichment=_make_result(),
            db_session=db_session,
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

    # NOTE: sender-domain allowlist filtering was intentionally removed from the
    # indexing adapter (see comment in `_emit_email_crm_trigger_events`): the
    # downstream CRM prompt handles internal-vs-external classification itself,
    # and early filtering would prevent external-lead emails from ever reaching
    # the CRM pipeline. The test that asserted the filter's presence was
    # deleted alongside the filter.
    db_session.commit.assert_called_once()


def test_post_index_skips_trigger_emission_when_job_id_not_configured() -> None:
    db_session = MagicMock()
    adapter = _make_adapter()
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
            enrichment=_make_result(),
            db_session=db_session,
        )

    mock_create_trigger_event.assert_not_called()
    db_session.commit.assert_called_once()


def test_post_index_passes_its_db_session_to_trigger_creation() -> None:
    """Regression guard for the upstream DocumentIndex interface refactor.

    Upstream removed ``db_session`` from ``DocumentIndexingBatchAdapter.__init__``
    and now passes a short-lived session INTO ``post_index(..., db_session=...)``.
    The email-CRM trigger emission MUST use that passed-in session. If someone
    reintroduces an adapter-owned ``self.db_session`` (or wires the wrong
    session through), indexing crashes in production.

    This test asserts:
      * the adapter does NOT hold its own ``self.db_session`` attribute, and
      * ``create_trigger_event`` (the trigger-event persistence call) receives
        the EXACT session object that was passed to ``post_index``.
    """
    sentinel_session = MagicMock(name="post_index_db_session")
    adapter = _make_adapter()

    # The sync's contract: session ownership moved out of __init__.
    assert not hasattr(adapter, "db_session"), (
        "adapter must not own a db_session; it is passed into post_index()"
    )

    email_doc = _make_doc(
        doc_id="gmail-thread-77",
        source=DocumentSource.GMAIL,
        doc_updated_at=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
    )
    context = DocumentBatchPrepareContext(
        updatable_docs=[email_doc],
        id_to_boost_map={},
    )

    captured_sessions: list[object] = []

    def _capture_session(**kwargs: object) -> SimpleNamespace:
        captured_sessions.append(kwargs["db_session"])
        return SimpleNamespace(id=uuid4())

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
            return_value=UUID("22222222-2222-2222-2222-222222222222"),
        ),
        patch(
            "onyx.indexing.adapters.document_indexing_adapter.create_trigger_event",
            side_effect=_capture_session,
        ) as mock_create_trigger_event,
    ):
        adapter.post_index(
            context=context,
            updatable_chunk_data=[],
            filtered_documents=[email_doc],
            enrichment=_make_result(),
            db_session=sentinel_session,
        )

    # The trigger-event persistence used the session passed into post_index,
    # not some adapter-owned or otherwise-constructed session.
    mock_create_trigger_event.assert_called_once()
    assert captured_sessions == [sentinel_session]
    assert mock_create_trigger_event.call_args.kwargs["db_session"] is sentinel_session

    # And the final commit happens on that same session.
    sentinel_session.commit.assert_called_once()


def test_get_email_crm_custom_job_uuid_invalid_value_returns_none() -> None:
    _get_email_crm_custom_job_uuid.cache_clear()
    try:
        with (
            patch(
                "onyx.indexing.adapters.document_indexing_adapter.EMAIL_CRM_CUSTOM_JOB_ID",
                "definitely-not-a-uuid",
            ),
            patch(
                "onyx.indexing.adapters.document_indexing_adapter.logger.error"
            ) as mock_error,
        ):
            parsed = _get_email_crm_custom_job_uuid()
            assert parsed is None
            mock_error.assert_called_once()
    finally:
        _get_email_crm_custom_job_uuid.cache_clear()
