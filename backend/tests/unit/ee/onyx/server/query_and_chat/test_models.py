from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from ee.onyx.server.query_and_chat.models import SearchDocWithContent


def test_search_doc_with_content_copies_image_from_metadata() -> None:
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
        metadata={"image": " https://example.com/image.png "},
        match_highlights=["snippet"],
        doc_summary="",
        chunk_context="",
        updated_at=None,
    )
    section = InferenceSection(
        center_chunk=chunk,
        chunks=[chunk],
        combined_content="content",
    )

    docs = SearchDocWithContent.from_inference_sections(
        [section],
        include_content=True,
        is_internet=True,
    )

    assert len(docs) == 1
    assert docs[0].image == "https://example.com/image.png"
    assert docs[0].content == "content"
    assert docs[0].is_internet is True
