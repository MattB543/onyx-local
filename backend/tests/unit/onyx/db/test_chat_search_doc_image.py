from unittest.mock import MagicMock

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import SavedSearchDoc
from onyx.context.search.models import SearchDoc
from onyx.db.chat import create_db_search_doc
from onyx.db.chat import create_search_doc_from_inference_section
from onyx.db.chat import create_search_doc_from_saved_search_doc
from onyx.db.chat import translate_db_search_doc_to_saved_search_doc
from onyx.db.models import SearchDoc as DBSearchDoc


def _make_search_doc(image: str | None = "https://example.com/image.png") -> SearchDoc:
    return SearchDoc(
        document_id="WEB_SEARCH_DOC_https://example.com/article",
        chunk_ind=0,
        semantic_identifier="Example",
        link="https://example.com/article",
        blurb="snippet",
        source_type=DocumentSource.WEB,
        boost=1,
        hidden=False,
        metadata={},
        score=1.0,
        match_highlights=["snippet"],
        is_internet=True,
        image=image,
    )


def _make_inference_section(
    image: str | list[str] | None = "https://example.com/image.png",
) -> InferenceSection:
    metadata = {"image": image} if image is not None else {}
    chunk = InferenceChunk(
        chunk_id=0,
        blurb="snippet",
        content="content",
        source_links={0: "https://example.com/article"},
        image_file_id=None,
        section_continuation=False,
        document_id="WEB_SEARCH_DOC_https://example.com/article",
        source_type=DocumentSource.WEB,
        semantic_identifier="Example",
        title="Example",
        boost=1,
        score=1.0,
        hidden=False,
        metadata=metadata,
        match_highlights=["snippet"],
        doc_summary="",
        chunk_context="",
        updated_at=None,
    )
    return InferenceSection(
        center_chunk=chunk,
        chunks=[chunk],
        combined_content="content",
    )


def _make_db_search_doc(image: str | None = "https://example.com/image.png") -> DBSearchDoc:
    return DBSearchDoc(
        id=1,
        document_id="WEB_SEARCH_DOC_https://example.com/article",
        chunk_ind=0,
        semantic_id="Example",
        link="https://example.com/article",
        blurb="snippet",
        boost=1,
        source_type=DocumentSource.WEB,
        hidden=False,
        doc_metadata={},
        score=1.0,
        match_highlights=["snippet"],
        is_internet=True,
        image=image,
    )


def test_create_db_search_doc_sanitizes_and_persists_image() -> None:
    mock_session = MagicMock()

    db_search_doc = create_db_search_doc(
        server_search_doc=_make_search_doc("https://example.com/image\x00.png"),
        db_session=mock_session,
        commit=False,
    )

    assert db_search_doc.image == "https://example.com/image.png"
    mock_session.add.assert_called_once_with(db_search_doc)
    mock_session.flush.assert_called_once()


def test_translate_db_search_doc_to_saved_search_doc_preserves_image() -> None:
    saved_doc = translate_db_search_doc_to_saved_search_doc(_make_db_search_doc())

    assert saved_doc.image == "https://example.com/image.png"


def test_create_search_doc_from_inference_section_copies_image_from_metadata() -> None:
    mock_session = MagicMock()

    db_search_doc = create_search_doc_from_inference_section(
        inference_section=_make_inference_section(" https://example.com/image.png "),
        is_internet=True,
        db_session=mock_session,
        commit=False,
    )

    assert db_search_doc.image == "https://example.com/image.png"
    mock_session.add.assert_called_once_with(db_search_doc)
    mock_session.flush.assert_called_once()


def test_create_search_doc_from_saved_search_doc_preserves_image() -> None:
    saved_search_doc = SavedSearchDoc.from_search_doc(_make_search_doc(), db_doc_id=7)

    db_search_doc = create_search_doc_from_saved_search_doc(saved_search_doc)

    assert db_search_doc.image == "https://example.com/image.png"
