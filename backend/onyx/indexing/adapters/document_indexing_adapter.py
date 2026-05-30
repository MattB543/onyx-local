import contextlib
import hashlib
import re
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from email.utils import getaddresses
from functools import lru_cache
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.access.access import get_access_for_documents
from onyx.access.models import DocumentAccess
from onyx.configs.app_configs import EMAIL_CRM_CUSTOM_JOB_ID
from onyx.configs.constants import DEFAULT_BOOST
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.models import IndexAttemptMetadata
from onyx.connectors.models import TextSection
from onyx.db.chunk import update_chunk_boost_components__no_commit
from onyx.db.custom_jobs import create_trigger_event
from onyx.db.document import fetch_chunk_counts_for_documents
from onyx.db.document import mark_document_as_indexed_for_cc_pair__no_commit
from onyx.db.document import prepare_to_modify_documents
from onyx.db.document import update_docs_chunk_count__no_commit
from onyx.db.document import update_docs_last_modified__no_commit
from onyx.db.document import update_docs_updated_at__no_commit
from onyx.db.document_set import fetch_document_sets_for_documents
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.indexing.indexing_pipeline import DocumentBatchPrepareContext
from onyx.indexing.indexing_pipeline import index_doc_batch_prepare
from onyx.indexing.models import ChunkEnrichmentContext
from onyx.indexing.models import DocAwareChunk
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.indexing.models import IndexChunk
from onyx.indexing.models import IndexingBatchAdapter
from onyx.indexing.models import UpdatableChunkData
from onyx.redis.redis_hierarchy import get_ancestors_from_raw_id
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger

logger = setup_logger()

_EMAIL_SOURCES = {DocumentSource.GMAIL, DocumentSource.IMAP}
_EMAIL_CRM_PAYLOAD_TEXT_LIMIT = 50_000
_EMAIL_TRIGGER_SOURCE_TYPE = "email_indexed"


@lru_cache(maxsize=1)
def _get_email_crm_custom_job_uuid() -> UUID | None:
    if not EMAIL_CRM_CUSTOM_JOB_ID:
        return None

    try:
        return UUID(EMAIL_CRM_CUSTOM_JOB_ID)
    except ValueError:
        logger.error(
            "Invalid EMAIL_CRM_CUSTOM_JOB_ID '%s'; skipping email trigger emission.",
            EMAIL_CRM_CUSTOM_JOB_ID,
        )
        return None


def _build_email_crm_dedupe_key(doc: Document) -> str:
    """Build a source-aware dedupe key for email trigger events.

    IMAP uses a stable message-level key since IMAP message IDs don't change.
    Gmail uses the doc ID plus an update fingerprint so thread updates
    produce new trigger events.
    """
    if doc.source == DocumentSource.IMAP:
        return f"imap:{doc.id}"

    # Gmail: include an update fingerprint so re-indexed thread updates
    # are not suppressed by deduplication.
    if doc.doc_updated_at is not None:
        update_token = doc.doc_updated_at.isoformat()
    else:
        update_token = hashlib.sha256(doc.id.encode()).hexdigest()[:12]
    return f"gmail:{doc.id}:{update_token}"


def _extract_document_text(doc: Document, limit: int) -> str:
    """Concatenate text sections from a Document, truncated to *limit* characters."""
    parts: list[str] = []
    total = 0
    for section in doc.sections:
        if isinstance(section, TextSection) and section.text:
            remaining = limit - total
            if remaining <= 0:
                break
            parts.append(section.text[:remaining])
            total += len(parts[-1])
    return "\n\n".join(parts)


def _owner_emails(owners: list | None) -> list[str]:
    """Extract non-None email addresses from a list of BasicExpertInfo."""
    if not owners:
        return []
    return [o.email for o in owners if o.email]


def _parse_email_address(value: str) -> str | None:
    for _display_name, address in getaddresses([value]):
        normalized = address.strip().lower()
        if normalized.count("@") == 1:
            return normalized
    return None


def _extract_sender_from_imap_sections(doc: Document) -> str | None:
    for section in doc.sections:
        if not isinstance(section, TextSection) or not section.text:
            continue
        from_match = re.search(r"(?im)^from:\s*(.+)$", section.text)
        if not from_match:
            continue
        sender_email = _parse_email_address(from_match.group(1))
        if sender_email:
            return sender_email
    return None


def _extract_sender_email(doc: Document) -> str | None:
    if doc.source == DocumentSource.IMAP:
        sender_from_header = _extract_sender_from_imap_sections(doc)
        if sender_from_header:
            return sender_from_header

    for owner_email in _owner_emails(doc.primary_owners):
        sender_email = _parse_email_address(owner_email)
        if sender_email:
            return sender_email
    return None



class DocumentIndexingBatchAdapter(IndexingBatchAdapter):
    """Default adapter: handles DB prep, locking, metadata enrichment, and finalize.

    Keeps orchestration logic in the pipeline and side-effects in the adapter.
    Each phase opens its own short-lived session so no connection is held idle
    during the long embedding and Vespa-write phases.
    """

    def __init__(
        self,
        connector_id: int,
        credential_id: int,
        tenant_id: str,
        index_attempt_metadata: IndexAttemptMetadata,
    ):
        self.connector_id = connector_id
        self.credential_id = credential_id
        self.tenant_id = tenant_id
        self.index_attempt_metadata = index_attempt_metadata

    def prepare(
        self, documents: list[Document], ignore_time_skip: bool
    ) -> DocumentBatchPrepareContext | None:
        """Upsert docs, map CC pairs, return context or mark as indexed if no-op.

        Opens and closes its own short-lived session so the caller holds no
        connection after this method returns.
        """
        with get_session_with_current_tenant() as db_session:
            context = index_doc_batch_prepare(
                documents=documents,
                index_attempt_metadata=self.index_attempt_metadata,
                db_session=db_session,
                ignore_time_skip=ignore_time_skip,
            )

            if not context:
                # even though we didn't actually index anything, we should still
                # mark them as "completed" for the CC Pair in order to make the
                # counts match
                mark_document_as_indexed_for_cc_pair__no_commit(
                    connector_id=self.index_attempt_metadata.connector_id,
                    credential_id=self.index_attempt_metadata.credential_id,
                    document_ids=[doc.id for doc in documents],
                    db_session=db_session,
                )
            db_session.commit()

        return context

    @contextlib.contextmanager
    def lock_context(self, documents: list[Document]) -> Generator[Session, None, None]:
        """Acquire transaction/row locks on docs and yield the session.

        Commits once after the caller's body returns (still inside the
        prepare_to_modify_documents begin() block), then closes the session.
        The single commit both flushes post_index's writes and releases the lock.
        """
        with get_session_with_current_tenant() as db_session:
            with prepare_to_modify_documents(
                db_session=db_session,
                document_ids=[doc.id for doc in documents],
            ):
                yield db_session
                db_session.commit()

    def prepare_enrichment(
        self,
        context: DocumentBatchPrepareContext,
        tenant_id: str,
        chunks: list[DocAwareChunk],
        db_session: Session,
    ) -> "DocumentChunkEnricher":
        """Do all DB lookups once and return a per-chunk enricher."""
        updatable_ids = [doc.id for doc in context.updatable_docs]

        doc_id_to_new_chunk_cnt: dict[str, int] = {
            doc_id: 0 for doc_id in updatable_ids
        }
        for chunk in chunks:
            if chunk.source_document.id in doc_id_to_new_chunk_cnt:
                doc_id_to_new_chunk_cnt[chunk.source_document.id] += 1

        no_access = DocumentAccess.build(
            user_emails=[],
            user_groups=[],
            external_user_emails=[],
            external_user_group_ids=[],
            is_public=False,
        )

        return DocumentChunkEnricher(
            doc_id_to_access_info=get_access_for_documents(
                document_ids=updatable_ids, db_session=db_session
            ),
            doc_id_to_document_set={
                document_id: document_sets
                for document_id, document_sets in fetch_document_sets_for_documents(
                    document_ids=updatable_ids, db_session=db_session
                )
            },
            doc_id_to_ancestor_ids=self._get_ancestor_ids_for_documents(
                context.updatable_docs, tenant_id, db_session
            ),
            id_to_boost_map=context.id_to_boost_map,
            doc_id_to_previous_chunk_cnt={
                document_id: chunk_count
                for document_id, chunk_count in fetch_chunk_counts_for_documents(
                    document_ids=updatable_ids,
                    db_session=db_session,
                )
            },
            doc_id_to_new_chunk_cnt=dict(doc_id_to_new_chunk_cnt),
            no_access=no_access,
            tenant_id=tenant_id,
        )

    def _get_ancestor_ids_for_documents(
        self,
        documents: list[Document],
        tenant_id: str,
        db_session: Session,
    ) -> dict[str, list[int]]:
        """
        Get ancestor hierarchy node IDs for a batch of documents.

        Uses Redis cache for fast lookups - no DB calls are made unless
        there's a cache miss. Documents provide parent_hierarchy_raw_node_id
        directly from the connector.

        Returns a mapping from document_id to list of ancestor node IDs.
        """
        if not documents:
            return {}

        redis_client = get_redis_client(tenant_id=tenant_id)
        result: dict[str, list[int]] = {}

        for doc in documents:
            # Use parent_hierarchy_raw_node_id directly from the document
            # If None, get_ancestors_from_raw_id will return just the SOURCE node
            ancestors = get_ancestors_from_raw_id(
                redis_client=redis_client,
                source=doc.source,
                parent_hierarchy_raw_node_id=doc.parent_hierarchy_raw_node_id,
                db_session=db_session,
            )
            result[doc.id] = ancestors

        return result

    def post_index(
        self,
        context: DocumentBatchPrepareContext,
        updatable_chunk_data: list[UpdatableChunkData],
        filtered_documents: list[Document],
        enrichment: ChunkEnrichmentContext,
        db_session: Session,
    ) -> None:
        """Finalize DB updates, store plaintext, and mark docs as indexed."""
        updatable_ids = [doc.id for doc in context.updatable_docs]
        last_modified_ids = []
        ids_to_new_updated_at = {}
        for doc in context.updatable_docs:
            last_modified_ids.append(doc.id)
            # doc_updated_at is the source's idea (on the other end of the connector)
            # of when the doc was last modified
            if doc.doc_updated_at is None:
                continue
            ids_to_new_updated_at[doc.id] = doc.doc_updated_at

        update_docs_updated_at__no_commit(
            ids_to_new_updated_at=ids_to_new_updated_at, db_session=db_session
        )

        update_docs_last_modified__no_commit(
            document_ids=last_modified_ids, db_session=db_session
        )

        update_docs_chunk_count__no_commit(
            document_ids=updatable_ids,
            doc_id_to_chunk_count=enrichment.doc_id_to_new_chunk_cnt,
            db_session=db_session,
        )

        # these documents can now be counted as part of the CC Pairs
        # document count, so we need to mark them as indexed
        # NOTE: even documents we skipped since they were already up
        # to date should be counted here in order to maintain parity
        # between CC Pair and index attempt counts
        mark_document_as_indexed_for_cc_pair__no_commit(
            connector_id=self.index_attempt_metadata.connector_id,
            credential_id=self.index_attempt_metadata.credential_id,
            document_ids=[doc.id for doc in filtered_documents],
            db_session=db_session,
        )

        # save the chunk boost components to postgres
        update_chunk_boost_components__no_commit(
            chunk_data=updatable_chunk_data, db_session=db_session
        )

        # --- Email-to-CRM trigger event emission ---
        # Only runs when EMAIL_CRM_CUSTOM_JOB_ID is configured.
        custom_job_id = _get_email_crm_custom_job_uuid()
        if custom_job_id is not None:
            try:
                self._emit_email_crm_trigger_events(
                    context=context,
                    custom_job_id=custom_job_id,
                )
            except Exception:
                logger.exception(
                    "Failed to emit email-CRM trigger events; "
                    "indexing will proceed without them."
                )

        self.db_session.commit()

    def _emit_email_crm_trigger_events(
        self,
        context: DocumentBatchPrepareContext,
        custom_job_id: UUID,
    ) -> None:
        """Emit CustomJobTriggerEvents for GMAIL/IMAP documents.

        Called at the end of post_index() when EMAIL_CRM_CUSTOM_JOB_ID is set.
        Each qualifying document produces one trigger event. Deduplication is
        handled at the DB level via a unique constraint on (custom_job_id, dedupe_key).
        """
        email_docs = [
            doc
            for doc in context.updatable_docs
            if doc.source in _EMAIL_SOURCES
        ]
        if not email_docs:
            return

        # NOTE: We intentionally do NOT filter by sender domain here.
        # The downstream CRM prompt (process_email_crm.py) is already equipped
        # to distinguish internal vs. external contacts using the
        # VALID_EMAIL_DOMAINS list.  Filtering here would prevent emails from
        # external senders from ever reaching the CRM pipeline, which is the
        # primary use-case (capturing inbound leads/contacts).

        for doc in email_docs:
            sender_email = _extract_sender_email(doc)

            dedupe_key = _build_email_crm_dedupe_key(doc)
            primary_owner_emails = _owner_emails(doc.primary_owners)
            secondary_owner_emails = _owner_emails(doc.secondary_owners)
            extracted_text = _extract_document_text(doc, _EMAIL_CRM_PAYLOAD_TEXT_LIMIT)

            payload: dict[str, object] = {
                "document_id": doc.id,
                "source": doc.source.value,
                "semantic_identifier": doc.semantic_identifier,
                "doc_updated_at": (
                    doc.doc_updated_at.isoformat() if doc.doc_updated_at else None
                ),
                "primary_owner_emails": primary_owner_emails,
                "secondary_owner_emails": secondary_owner_emails,
                "text": extracted_text,
                # Explicit fields consumed by downstream CRM prompt construction.
                # Keep these in addition to legacy fields for compatibility.
                "from": sender_email
                or (primary_owner_emails[0] if primary_owner_emails else ""),
                "to": ", ".join(secondary_owner_emails),
                "subject": doc.semantic_identifier,
                "date": doc.doc_updated_at.isoformat() if doc.doc_updated_at else "",
                "body": extracted_text,
            }

            event = create_trigger_event(
                db_session=self.db_session,
                custom_job_id=custom_job_id,
                source_type=_EMAIL_TRIGGER_SOURCE_TYPE,
                source_event_id=doc.id,
                dedupe_key=dedupe_key,
                dedupe_key_prefix=_EMAIL_TRIGGER_SOURCE_TYPE,
                event_time=doc.doc_updated_at or datetime.now(timezone.utc),
                payload_json=payload,
            )

            if event is not None:
                logger.info(
                    "Email-CRM trigger event created for doc '%s' "
                    "(dedupe_key=%s, event_id=%s)",
                    doc.id,
                    dedupe_key,
                    event.id,
                )
            else:
                logger.debug(
                    "Email-CRM trigger event dedupe-suppressed for doc '%s' "
                    "(dedupe_key=%s)",
                    doc.id,
                    dedupe_key,
                )


class DocumentChunkEnricher:
    """Pre-computed metadata for per-chunk enrichment of connector documents."""

    def __init__(
        self,
        doc_id_to_access_info: dict[str, DocumentAccess],
        doc_id_to_document_set: dict[str, list[str]],
        doc_id_to_ancestor_ids: dict[str, list[int]],
        id_to_boost_map: dict[str, int],
        doc_id_to_previous_chunk_cnt: dict[str, int],
        doc_id_to_new_chunk_cnt: dict[str, int],
        no_access: DocumentAccess,
        tenant_id: str,
    ) -> None:
        self._doc_id_to_access_info = doc_id_to_access_info
        self._doc_id_to_document_set = doc_id_to_document_set
        self._doc_id_to_ancestor_ids = doc_id_to_ancestor_ids
        self._id_to_boost_map = id_to_boost_map
        self._no_access = no_access
        self._tenant_id = tenant_id
        self.doc_id_to_previous_chunk_cnt = doc_id_to_previous_chunk_cnt
        self.doc_id_to_new_chunk_cnt = doc_id_to_new_chunk_cnt

    def enrich_chunk(
        self, chunk: IndexChunk, score: float
    ) -> DocMetadataAwareIndexChunk:
        return DocMetadataAwareIndexChunk.from_index_chunk(
            index_chunk=chunk,
            access=self._doc_id_to_access_info.get(
                chunk.source_document.id, self._no_access
            ),
            document_sets=set(
                self._doc_id_to_document_set.get(chunk.source_document.id, [])
            ),
            user_project=[],
            personas=[],
            boost=(
                self._id_to_boost_map[chunk.source_document.id]
                if chunk.source_document.id in self._id_to_boost_map
                else DEFAULT_BOOST
            ),
            tenant_id=self._tenant_id,
            aggregated_chunk_boost_factor=score,
            ancestor_hierarchy_node_ids=self._doc_id_to_ancestor_ids[
                chunk.source_document.id
            ],
        )
