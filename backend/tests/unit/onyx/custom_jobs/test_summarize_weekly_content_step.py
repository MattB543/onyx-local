from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import MagicMock
from unittest.mock import call
from unittest.mock import patch

from onyx.custom_jobs.steps.summarize_weekly_content import _scrub_summary_output
from onyx.custom_jobs.steps.summarize_weekly_content import MAP_SYSTEM_PROMPT
from onyx.custom_jobs.steps.summarize_weekly_content import MERGE_SYSTEM_PROMPT
from onyx.custom_jobs.steps.summarize_weekly_content import SUMMARY_OUTPUT_MAX_CHARS
from onyx.custom_jobs.steps.summarize_weekly_content import SUMMARY_SYSTEM_PROMPT
from onyx.custom_jobs.steps.summarize_weekly_content import SummarizeWeeklyContentStep
from onyx.custom_jobs.types import StepContext
from onyx.db.enums import CustomJobStepStatus


def _context(previous_outputs: dict, step_config: dict | None = None) -> StepContext:
    return StepContext(
        db_session=MagicMock(),
        tenant_id="public",
        run_id=uuid4(),
        job_id=uuid4(),
        job_config={},
        step_config=step_config or {},
        previous_outputs=previous_outputs,
        deadline_monotonic=1_000_000.0,
    )


def _response(content: str, prompt_tokens: int = 10, completion_tokens: int = 5) -> SimpleNamespace:
    return SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
        choice=SimpleNamespace(message=SimpleNamespace(content=content)),
    )


def _make_mock_llm(
    responses: list[SimpleNamespace],
    max_input_tokens: int = 8_000,
) -> MagicMock:
    """Create a MagicMock LLM that records invoke calls and returns
    pre-configured responses in order."""
    mock_llm = MagicMock()
    mock_llm.config = SimpleNamespace(max_input_tokens=max_input_tokens)
    mock_llm.invoke = MagicMock(side_effect=responses)
    return mock_llm


class _FakeLLM:
    def __init__(self, responses: list[SimpleNamespace], max_input_tokens: int = 8_000):
        self.config = SimpleNamespace(max_input_tokens=max_input_tokens)
        self._responses = responses

    def invoke(self, llm_messages) -> SimpleNamespace:  # noqa: ANN001, ARG002
        assert self._responses
        return self._responses.pop(0)


def _messages(count: int) -> list[dict]:
    return [
        {
            "chat_session_id": f"session-{i}",
            "time_sent": "2026-02-17T00:00:00+00:00",
            "message_type": "user",
            "message": f"message-{i}",
        }
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# Existing tests (fixed / augmented)
# ---------------------------------------------------------------------------


def test_summarize_step_fails_when_required_input_missing() -> None:
    step = SummarizeWeeklyContentStep()
    context = _context(previous_outputs={})

    result = step.run(context)

    assert result.status == CustomJobStepStatus.FAILURE
    assert "Missing required step output" in str(result.error_message)


def test_summarize_step_skips_when_below_min_messages() -> None:
    step = SummarizeWeeklyContentStep()
    context = _context(
        previous_outputs={"fetch_weekly_chat_content": {"messages": _messages(1)}},
        step_config={"min_messages": 3},
    )
    mock_get_default_llm = MagicMock()
    mock_llm = _make_mock_llm(responses=[_response("unused")])
    mock_get_default_llm.return_value = mock_llm

    with (
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_default_llm",
            mock_get_default_llm,
        ),
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_llm_token_counter",
            return_value=lambda text: 1,  # noqa: ARG005
        ),
    ):
        result = step.run(context)

    assert result.status == CustomJobStepStatus.SKIPPED
    assert result.output_json is not None
    assert result.output_json["skip_reason"] == "below_min_message_threshold"
    # Verify the LLM was never invoked (only created, not used).
    mock_llm.invoke.assert_not_called()


def test_summarize_step_single_pass_scrubs_output() -> None:
    step = SummarizeWeeklyContentStep()
    context = _context(
        previous_outputs={"fetch_weekly_chat_content": {"messages": _messages(3)}},
        step_config={"min_messages": 1},
    )
    mock_llm = _make_mock_llm(
        responses=[_response("<untrusted_content>clean me</untrusted_content>\x00")]
    )

    with (
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_default_llm",
            return_value=mock_llm,
        ) as mock_get_default_llm,
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_llm_token_counter",
            return_value=lambda text: 1,  # noqa: ARG005
        ),
    ):
        result = step.run(context)

    assert result.status == CustomJobStepStatus.SUCCESS
    assert result.output_json is not None
    assert result.output_json["strategy"] == "single_pass"
    assert result.output_json["summary"] == "clean me"

    # Verify get_default_llm was called with temperature=0.
    mock_get_default_llm.assert_called_once_with(temperature=0)

    # Verify prompt construction: the user message should wrap content
    # in <untrusted_content> tags.
    invoke_args = mock_llm.invoke.call_args[0][0]
    system_msg = invoke_args[0]
    user_msg = invoke_args[1]
    assert system_msg.content == SUMMARY_SYSTEM_PROMPT
    assert "<untrusted_content>" in user_msg.content
    assert "</untrusted_content>" in user_msg.content


def test_summarize_step_map_reduce_path() -> None:
    step = SummarizeWeeklyContentStep()
    context = _context(
        previous_outputs={"fetch_weekly_chat_content": {"messages": _messages(3)}},
        step_config={"min_messages": 1, "max_chunks": 10},
    )
    mock_llm = _make_mock_llm(
        responses=[
            _response("partial-1", prompt_tokens=20, completion_tokens=10),
            _response("partial-2", prompt_tokens=20, completion_tokens=10),
            _response("partial-3", prompt_tokens=20, completion_tokens=10),
            _response("<partial_summary>final</partial_summary>", prompt_tokens=30, completion_tokens=15),
        ],
        max_input_tokens=2_600,
    )

    def token_counter(text: str) -> int:
        if text.startswith("<untrusted_content>") and text.count("<message>") >= 2:
            return 5_000  # Force map-reduce.
        if "<message>" in text:
            return 700  # Force multiple chunks.
        return 50

    with (
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_default_llm",
            return_value=mock_llm,
        ),
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_llm_token_counter",
            return_value=token_counter,
        ),
    ):
        result = step.run(context)

    assert result.status == CustomJobStepStatus.SUCCESS
    assert result.output_json is not None
    assert result.output_json["strategy"] == "map_reduce"
    assert result.output_json["chunk_count"] == 3
    assert result.output_json["summary"] == "final"

    # Verify the number of LLM calls: N chunk calls + 1 reduce call.
    assert mock_llm.invoke.call_count == 4  # 3 chunks + 1 reduce

    # Verify token accumulation across all calls.
    assert result.output_json["input_tokens"] == 20 + 20 + 20 + 30
    assert result.output_json["output_tokens"] == 10 + 10 + 10 + 15


def test_scrub_summary_output_truncates_over_limit() -> None:
    long_text = "x" * (SUMMARY_OUTPUT_MAX_CHARS + 50)

    scrubbed = _scrub_summary_output(long_text)

    assert scrubbed.endswith("[truncated]")
    assert len(scrubbed) <= SUMMARY_OUTPUT_MAX_CHARS + len("\n\n[truncated]")


# ---------------------------------------------------------------------------
# New tests for missing coverage
# ---------------------------------------------------------------------------


def test_prompt_safety_untrusted_content_delimiters() -> None:
    """Verify that the prompt sent to the LLM wraps user content in
    <untrusted_content> tags."""
    step = SummarizeWeeklyContentStep()
    context = _context(
        previous_outputs={"fetch_weekly_chat_content": {"messages": _messages(5)}},
        step_config={"min_messages": 1},
    )
    mock_llm = _make_mock_llm(responses=[_response("summary result")])

    with (
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_default_llm",
            return_value=mock_llm,
        ),
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_llm_token_counter",
            return_value=lambda text: 1,  # noqa: ARG005
        ),
    ):
        result = step.run(context)

    assert result.status == CustomJobStepStatus.SUCCESS
    # Extract the messages passed to llm.invoke.
    invoke_args = mock_llm.invoke.call_args[0][0]
    user_msg = invoke_args[1]
    assert user_msg.content.startswith("<untrusted_content>")
    assert user_msg.content.strip().endswith("</untrusted_content>")


def test_prompt_safety_ignore_instructions_directive() -> None:
    """Verify the system prompt instructs the LLM to ignore instructions
    inside source messages."""
    step = SummarizeWeeklyContentStep()
    context = _context(
        previous_outputs={"fetch_weekly_chat_content": {"messages": _messages(5)}},
        step_config={"min_messages": 1},
    )
    mock_llm = _make_mock_llm(responses=[_response("summary result")])

    with (
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_default_llm",
            return_value=mock_llm,
        ),
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_llm_token_counter",
            return_value=lambda text: 1,  # noqa: ARG005
        ),
    ):
        result = step.run(context)

    assert result.status == CustomJobStepStatus.SUCCESS
    invoke_args = mock_llm.invoke.call_args[0][0]
    system_msg = invoke_args[0]
    # The system prompt must tell the LLM to never follow instructions
    # from the untrusted content.
    assert "never follow" in system_msg.content.lower()
    assert "instructions" in system_msg.content.lower()


def test_temperature_zero_verification() -> None:
    """Assert that get_default_llm is called with temperature=0."""
    step = SummarizeWeeklyContentStep()
    context = _context(
        previous_outputs={"fetch_weekly_chat_content": {"messages": _messages(5)}},
        step_config={"min_messages": 1},
    )
    mock_llm = _make_mock_llm(responses=[_response("summary")])

    with (
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_default_llm",
            return_value=mock_llm,
        ) as mock_get_default_llm,
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_llm_token_counter",
            return_value=lambda text: 1,  # noqa: ARG005
        ),
    ):
        step.run(context)

    mock_get_default_llm.assert_called_once_with(temperature=0)


def test_token_metrics_in_single_pass_output() -> None:
    """After a successful single-pass run, assert the output contains
    token counts (input_tokens and output_tokens)."""
    step = SummarizeWeeklyContentStep()
    context = _context(
        previous_outputs={"fetch_weekly_chat_content": {"messages": _messages(5)}},
        step_config={"min_messages": 1},
    )
    mock_llm = _make_mock_llm(
        responses=[_response("summary text", prompt_tokens=42, completion_tokens=17)]
    )

    with (
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_default_llm",
            return_value=mock_llm,
        ),
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_llm_token_counter",
            return_value=lambda text: 1,  # noqa: ARG005
        ),
    ):
        result = step.run(context)

    assert result.status == CustomJobStepStatus.SUCCESS
    assert result.output_json is not None
    assert result.output_json["input_tokens"] == 42
    assert result.output_json["output_tokens"] == 17
    # NOTE: The implementation does not include an "estimated_llm_cost"
    # field. This is a gap that should be addressed in the implementation
    # if cost tracking is desired.


def test_empty_messages_list_skips() -> None:
    """Test the code branch where messages list exists but is empty
    (implementation lines ~91-95)."""
    step = SummarizeWeeklyContentStep()
    context = _context(
        previous_outputs={"fetch_weekly_chat_content": {"messages": []}},
    )

    result = step.run(context)

    assert result.status == CustomJobStepStatus.SKIPPED
    assert result.output_json is not None
    assert result.output_json["summary"] == ""
    assert result.output_json["message_count"] == 0


def test_empty_messages_none_value_skips() -> None:
    """Test the code branch where messages key exists but is None."""
    step = SummarizeWeeklyContentStep()
    context = _context(
        previous_outputs={"fetch_weekly_chat_content": {"messages": None}},
    )

    result = step.run(context)

    assert result.status == CustomJobStepStatus.SKIPPED
    assert result.output_json is not None
    assert result.output_json["summary"] == ""
    assert result.output_json["message_count"] == 0


def test_small_context_window_failure() -> None:
    """Test when the LLM context window is too small for even the
    system prompt (available_tokens <= 1000)."""
    step = SummarizeWeeklyContentStep()
    context = _context(
        previous_outputs={"fetch_weekly_chat_content": {"messages": _messages(5)}},
        step_config={"min_messages": 1},
    )
    # Use a tiny max_input_tokens so available_tokens <= 1000.
    # available_tokens = max_input_tokens - GEN_AI_NUM_RESERVED_OUTPUT_TOKENS - system_tokens
    # GEN_AI_NUM_RESERVED_OUTPUT_TOKENS defaults to 1024.
    # With max_input_tokens=1500 and system_tokens=600:
    #   available = 1500 - 1024 - 600 = -124 <= 1000 -> failure
    mock_llm = _make_mock_llm(responses=[], max_input_tokens=1_500)

    with (
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_default_llm",
            return_value=mock_llm,
        ),
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_llm_token_counter",
            return_value=lambda text: 600,  # noqa: ARG005
        ),
    ):
        result = step.run(context)

    assert result.status == CustomJobStepStatus.FAILURE
    assert "context window too small" in str(result.error_message).lower()
    # The LLM should never have been invoked.
    mock_llm.invoke.assert_not_called()


def test_max_chunks_truncation() -> None:
    """Test that chunks beyond max_chunks are dropped (only the last
    max_chunks chunks are kept, implementation lines ~167-168)."""
    step = SummarizeWeeklyContentStep()
    # Create many messages that will be split across more chunks than max_chunks.
    context = _context(
        previous_outputs={"fetch_weekly_chat_content": {"messages": _messages(10)}},
        step_config={"min_messages": 1, "max_chunks": 2},
    )
    # Provide enough responses: 2 chunk calls + 1 reduce call.
    mock_llm = _make_mock_llm(
        responses=[
            _response("partial-a"),
            _response("partial-b"),
            _response("final merged"),
        ],
        max_input_tokens=2_600,
    )

    def token_counter(text: str) -> int:
        # Make the full content too large for a single pass.
        if text.startswith("<untrusted_content>") and text.count("<message>") >= 2:
            return 5_000
        # Each individual message is large enough to force many chunks.
        if "<message>" in text:
            return 700
        return 50

    with (
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_default_llm",
            return_value=mock_llm,
        ),
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_llm_token_counter",
            return_value=token_counter,
        ),
    ):
        result = step.run(context)

    assert result.status == CustomJobStepStatus.SUCCESS
    assert result.output_json is not None
    assert result.output_json["strategy"] == "map_reduce"
    # chunk_count should be capped at max_chunks=2.
    assert result.output_json["chunk_count"] == 2
    # 2 chunk calls + 1 reduce call = 3 total.
    assert mock_llm.invoke.call_count == 3


def test_custom_input_step_id() -> None:
    """Test that a non-default input_step_id is used correctly."""
    step = SummarizeWeeklyContentStep()
    custom_step_id = "my_custom_fetch_step"
    context = _context(
        previous_outputs={custom_step_id: {"messages": _messages(5)}},
        step_config={"min_messages": 1, "input_step_id": custom_step_id},
    )
    mock_llm = _make_mock_llm(responses=[_response("summary from custom step")])

    with (
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_default_llm",
            return_value=mock_llm,
        ),
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_llm_token_counter",
            return_value=lambda text: 1,  # noqa: ARG005
        ),
    ):
        result = step.run(context)

    assert result.status == CustomJobStepStatus.SUCCESS
    assert result.output_json is not None
    assert result.output_json["summary"] == "summary from custom step"


def test_custom_input_step_id_missing_fails() -> None:
    """Test that a custom input_step_id that is missing from previous_outputs
    results in failure."""
    step = SummarizeWeeklyContentStep()
    context = _context(
        previous_outputs={"fetch_weekly_chat_content": {"messages": _messages(5)}},
        step_config={"input_step_id": "nonexistent_step"},
    )

    result = step.run(context)

    assert result.status == CustomJobStepStatus.FAILURE
    assert "nonexistent_step" in str(result.error_message)


def test_sensitive_pattern_scrubbing() -> None:
    """Verify that _scrub_summary_output strips XML-like untrusted tags
    from the summary. Note: email/API-key scrubbing is not currently
    implemented in _scrub_summary_output; this tests the existing tag
    scrubbing behavior."""
    raw = (
        "<untrusted_content>Some text</untrusted_content> "
        "<message>more</message> "
        "<session>id</session> "
        "<time>now</time> "
        "<role>user</role> "
        "<text>hello</text> "
        "<partial_summary>ps</partial_summary>"
    )
    scrubbed = _scrub_summary_output(raw)
    assert "<untrusted_content>" not in scrubbed
    assert "</untrusted_content>" not in scrubbed
    assert "<message>" not in scrubbed
    assert "<session>" not in scrubbed
    assert "<time>" not in scrubbed
    assert "<role>" not in scrubbed
    assert "<text>" not in scrubbed
    assert "<partial_summary>" not in scrubbed
    # The actual text content should remain.
    assert "Some text" in scrubbed
    assert "hello" in scrubbed


def test_map_reduce_untrusted_tags_in_chunk_prompts() -> None:
    """Verify that map-reduce chunk calls also wrap content in
    <untrusted_content> tags and use the correct system prompts."""
    step = SummarizeWeeklyContentStep()
    context = _context(
        previous_outputs={"fetch_weekly_chat_content": {"messages": _messages(3)}},
        step_config={"min_messages": 1, "max_chunks": 10},
    )
    mock_llm = _make_mock_llm(
        responses=[
            _response("partial-1"),
            _response("partial-2"),
            _response("partial-3"),
            _response("final merged"),
        ],
        max_input_tokens=2_600,
    )

    def token_counter(text: str) -> int:
        if text.startswith("<untrusted_content>") and text.count("<message>") >= 2:
            return 5_000
        if "<message>" in text:
            return 700
        return 50

    with (
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_default_llm",
            return_value=mock_llm,
        ),
        patch(
            "onyx.custom_jobs.steps.summarize_weekly_content.get_llm_token_counter",
            return_value=token_counter,
        ),
    ):
        result = step.run(context)

    assert result.status == CustomJobStepStatus.SUCCESS

    # Verify chunk calls use MAP_SYSTEM_PROMPT and wrap in <untrusted_content>.
    all_calls = mock_llm.invoke.call_args_list
    chunk_calls = all_calls[:-1]  # All but the last (reduce) call
    for chunk_call in chunk_calls:
        msgs = chunk_call[0][0]
        assert msgs[0].content == MAP_SYSTEM_PROMPT
        assert "<untrusted_content>" in msgs[1].content
        assert "</untrusted_content>" in msgs[1].content

    # Verify the reduce call uses MERGE_SYSTEM_PROMPT.
    reduce_call = all_calls[-1]
    reduce_msgs = reduce_call[0][0]
    assert reduce_msgs[0].content == MERGE_SYSTEM_PROMPT
    assert "<partial_summary>" in reduce_msgs[1].content
