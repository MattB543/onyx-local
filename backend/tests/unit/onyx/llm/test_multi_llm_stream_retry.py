from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from litellm.exceptions import RateLimitError as LiteLLMRateLimitError
from litellm.exceptions import ServiceUnavailableError as LiteLLMServiceUnavailableError
from litellm.exceptions import Timeout as LiteLLMTimeout

from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.model_response import Delta, ModelResponseStream, StreamingChoice
from onyx.llm.models import UserMessage
from onyx.llm.multi_llm import LitellmLLM, LLMRateLimitError


def _make_fake_llm() -> MagicMock:
    llm = MagicMock()
    llm.config.model_name = "gpt-test"
    llm.config.model_provider = "openai"
    llm._timeout = 30
    llm._track_llm_cost = MagicMock()
    return llm


def _make_prompt() -> LanguageModelInput:
    return [UserMessage(content="hello")]


def _make_stream_response(content: str) -> ModelResponseStream:
    return ModelResponseStream(
        id="chunk-1",
        created="1",
        choice=StreamingChoice(delta=Delta(content=content)),
    )


def test_stream_retries_timeout_before_first_chunk() -> None:
    fake_llm = _make_fake_llm()
    translated_chunk = _make_stream_response("hello")
    attempt_count = 0

    def completion_side_effect(**_kwargs: object) -> list[object]:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            raise LiteLLMTimeout("timed out", "gpt-test", "openai")
        return [object()]

    fake_llm._completion = MagicMock(side_effect=completion_side_effect)

    with (
        patch("onyx.llm.multi_llm.LLM_FIRST_CHUNK_MAX_RETRIES", 1),
        patch("onyx.llm.multi_llm.is_true_openai_model", return_value=False),
        patch(
            "onyx.llm.model_response.from_litellm_model_response_stream",
            return_value=translated_chunk,
        ),
        patch("onyx.llm.multi_llm.logger") as mock_logger,
    ):
        # Bind the unbound method to a fake self to isolate retry behavior.
        results = list(LitellmLLM.stream(fake_llm, prompt=_make_prompt()))

    assert len(results) == 1
    assert results[0].choice.delta.content == "hello"
    assert fake_llm._completion.call_count == 2
    mock_logger.warning.assert_called_once()


def test_stream_does_not_retry_after_first_chunk() -> None:
    fake_llm = _make_fake_llm()
    translated_chunk = _make_stream_response("partial")

    def stream_then_timeout() -> Iterator[object]:
        yield object()
        raise LiteLLMTimeout("timed out", "gpt-test", "openai")

    fake_llm._completion = MagicMock(return_value=stream_then_timeout())

    with (
        patch("onyx.llm.multi_llm.LLM_FIRST_CHUNK_MAX_RETRIES", 2),
        patch("onyx.llm.multi_llm.is_true_openai_model", return_value=False),
        patch(
            "onyx.llm.model_response.from_litellm_model_response_stream",
            return_value=translated_chunk,
        ),
        patch("onyx.llm.multi_llm.logger") as mock_logger,
    ):
        # Bind the unbound method to a fake self to isolate retry behavior.
        with pytest.raises(LiteLLMTimeout):
            list(LitellmLLM.stream(fake_llm, prompt=_make_prompt()))

    assert fake_llm._completion.call_count == 1
    mock_logger.warning.assert_not_called()


def _make_503() -> LiteLLMServiceUnavailableError:
    return LiteLLMServiceUnavailableError(
        message="BedrockException - Too many connections, please wait before trying again.",
        llm_provider="bedrock",
        model="us.anthropic.claude-opus-5",
    )


def test_stream_retries_503_with_exponential_backoff() -> None:
    fake_llm = _make_fake_llm()
    translated_chunk = _make_stream_response("hello")
    attempt_count = 0

    def completion_side_effect(**_kwargs: object) -> list[object]:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count <= 2:
            raise _make_503()
        return [object()]

    fake_llm._completion = MagicMock(side_effect=completion_side_effect)

    with (
        patch("onyx.llm.multi_llm.LLM_SERVICE_UNAVAILABLE_MAX_RETRIES", 5),
        patch("onyx.llm.multi_llm.LLM_SERVICE_UNAVAILABLE_BACKOFF_BASE_S", 2.0),
        patch("onyx.llm.multi_llm.LLM_SERVICE_UNAVAILABLE_BACKOFF_MAX_S", 20.0),
        patch("onyx.llm.multi_llm.is_true_openai_model", return_value=False),
        patch(
            "onyx.llm.model_response.from_litellm_model_response_stream",
            return_value=translated_chunk,
        ),
        patch("onyx.llm.multi_llm.logger"),
        patch("onyx.llm.multi_llm.time.sleep") as mock_sleep,
    ):
        results = list(LitellmLLM.stream(fake_llm, prompt=_make_prompt()))

    assert len(results) == 1
    assert fake_llm._completion.call_count == 3
    assert [call.args[0] for call in mock_sleep.call_args_list] == [2.0, 4.0]


def test_stream_503_exhausts_retries_and_caps_backoff() -> None:
    fake_llm = _make_fake_llm()
    fake_llm._completion = MagicMock(side_effect=_make_503())

    with (
        patch("onyx.llm.multi_llm.LLM_SERVICE_UNAVAILABLE_MAX_RETRIES", 5),
        patch("onyx.llm.multi_llm.LLM_SERVICE_UNAVAILABLE_BACKOFF_BASE_S", 2.0),
        patch("onyx.llm.multi_llm.LLM_SERVICE_UNAVAILABLE_BACKOFF_MAX_S", 20.0),
        patch("onyx.llm.multi_llm.is_true_openai_model", return_value=False),
        patch("onyx.llm.multi_llm.logger"),
        patch("onyx.llm.multi_llm.time.sleep") as mock_sleep,
    ):
        with pytest.raises(LiteLLMServiceUnavailableError):
            list(LitellmLLM.stream(fake_llm, prompt=_make_prompt()))

    # 1 initial attempt + 5 retries
    assert fake_llm._completion.call_count == 6
    # Exponential with cap: 2, 4, 8, 16, then capped at 20 (not 32)
    assert [call.args[0] for call in mock_sleep.call_args_list] == [2.0, 4.0, 8.0, 16.0, 20.0]


def test_stream_503_does_not_retry_after_first_chunk() -> None:
    fake_llm = _make_fake_llm()
    translated_chunk = _make_stream_response("partial")

    def stream_then_503() -> Iterator[object]:
        yield object()
        raise _make_503()

    fake_llm._completion = MagicMock(return_value=stream_then_503())

    with (
        patch("onyx.llm.multi_llm.LLM_SERVICE_UNAVAILABLE_MAX_RETRIES", 5),
        patch("onyx.llm.multi_llm.is_true_openai_model", return_value=False),
        patch(
            "onyx.llm.model_response.from_litellm_model_response_stream",
            return_value=translated_chunk,
        ),
        patch("onyx.llm.multi_llm.logger"),
        patch("onyx.llm.multi_llm.time.sleep") as mock_sleep,
    ):
        with pytest.raises(LiteLLMServiceUnavailableError):
            list(LitellmLLM.stream(fake_llm, prompt=_make_prompt()))

    assert fake_llm._completion.call_count == 1
    mock_sleep.assert_not_called()


def test_stream_retries_throttling_with_backoff() -> None:
    """Bedrock ThrottlingException surfaces as RateLimitError (raw during
    iteration, wrapped as LLMRateLimitError at call time) — both should get
    the capacity backoff budget."""
    fake_llm = _make_fake_llm()
    translated_chunk = _make_stream_response("hello")
    attempt_count = 0

    def completion_side_effect(**_kwargs: object) -> list[object]:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            raise LLMRateLimitError(
                LiteLLMRateLimitError(
                    message="ThrottlingException - Too many requests",
                    llm_provider="bedrock",
                    model="us.anthropic.claude-opus-5",
                )
            )
        if attempt_count == 2:
            raise LiteLLMRateLimitError(
                message="ThrottlingException - Too many requests",
                llm_provider="bedrock",
                model="us.anthropic.claude-opus-5",
            )
        return [object()]

    fake_llm._completion = MagicMock(side_effect=completion_side_effect)

    with (
        patch("onyx.llm.multi_llm.LLM_SERVICE_UNAVAILABLE_MAX_RETRIES", 5),
        patch("onyx.llm.multi_llm.LLM_SERVICE_UNAVAILABLE_BACKOFF_BASE_S", 2.0),
        patch("onyx.llm.multi_llm.LLM_SERVICE_UNAVAILABLE_BACKOFF_MAX_S", 20.0),
        patch("onyx.llm.multi_llm.is_true_openai_model", return_value=False),
        patch(
            "onyx.llm.model_response.from_litellm_model_response_stream",
            return_value=translated_chunk,
        ),
        patch("onyx.llm.multi_llm.logger"),
        patch("onyx.llm.multi_llm.time.sleep") as mock_sleep,
    ):
        results = list(LitellmLLM.stream(fake_llm, prompt=_make_prompt()))

    assert len(results) == 1
    assert fake_llm._completion.call_count == 3
    assert [call.args[0] for call in mock_sleep.call_args_list] == [2.0, 4.0]


def test_stream_does_not_retry_quota_exhaustion() -> None:
    fake_llm = _make_fake_llm()
    fake_llm._completion = MagicMock(
        side_effect=LiteLLMRateLimitError(
            message="insufficient_quota: You exceeded your current quota.",
            llm_provider="openai",
            model="gpt-test",
        )
    )

    with (
        patch("onyx.llm.multi_llm.LLM_SERVICE_UNAVAILABLE_MAX_RETRIES", 5),
        patch("onyx.llm.multi_llm.is_true_openai_model", return_value=False),
        patch("onyx.llm.multi_llm.logger"),
        patch("onyx.llm.multi_llm.time.sleep") as mock_sleep,
    ):
        with pytest.raises(LiteLLMRateLimitError):
            list(LitellmLLM.stream(fake_llm, prompt=_make_prompt()))

    assert fake_llm._completion.call_count == 1
    mock_sleep.assert_not_called()
