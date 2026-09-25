"""litellm maps an unmapped provider error to APIConnectionError. A Bedrock 403
raised while streaming (no AWS Marketplace access to the model) arrives that
way, so the classifier looks at the error it was raised from: an access denial
is PERMISSION_DENIED with the provider's own message, not a connection error.
"""

import httpx
import litellm
import pytest
from litellm.exceptions import APIConnectionError, PermissionDeniedError
from litellm.litellm_core_utils.exception_mapping_utils import exception_type
from litellm.llms.bedrock.common_utils import BedrockError

from onyx.llm.utils import (
    find_access_denial,
    litellm_exception_to_error_msg,
    provider_error_detail,
)

MODEL = "us.anthropic.claude-opus-5-5"
MARKETPLACE_MESSAGE = (
    "Model access is denied due to IAM user or service role is not authorized "
    "to perform the required AWS Marketplace actions "
    "(aws-marketplace:ViewSubscriptions, aws-marketplace:Subscribe) to enable "
    "access to this model. Refer to the Amazon Bedrock documentation for further "
    "details. Your AWS Marketplace subscription for this model cannot be "
    "completed at this time. If you recently fixed this issue, try again after "
    "5 minutes."
)
# The streaming handler reads the error body as bytes, so the message is the
# repr of those bytes.
MARKETPLACE_BODY = str(('{"message":"%s"}' % MARKETPLACE_MESSAGE).encode())


@pytest.fixture(autouse=True)
def _quiet_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(litellm, "suppress_debug_info", True)


def _mapped_by_litellm(original: Exception) -> Exception:
    """The exception litellm raises for `original`, raised (as litellm does)
    while handling it."""
    try:
        try:
            raise original
        except Exception as provider_error:
            raise exception_type(
                model=MODEL,
                original_exception=provider_error,
                custom_llm_provider="bedrock",
            )
    except Exception as mapped:
        return mapped
    raise AssertionError("unreachable")


def test_bedrock_403_mapped_to_connection_error_is_permission_denied() -> None:
    mapped = _mapped_by_litellm(BedrockError(status_code=403, message=MARKETPLACE_BODY))
    # Guard the premise: this litellm version maps the 403 to a connection
    # error and puts the raw bytes wrapper in the message.
    assert isinstance(mapped, APIConnectionError)
    assert "b'{" in str(mapped)

    msg, code, is_retryable = litellm_exception_to_error_msg(mapped, None)

    assert code == "PERMISSION_DENIED"
    assert is_retryable is False
    assert msg == f"Permission denied: {MARKETPLACE_MESSAGE}"


def test_403_raised_as_cause_is_permission_denied() -> None:
    """`raise APIConnectionError(...) from provider_error` puts the 403 in
    __cause__, which the classifier's unwrap steps past to the bare
    BedrockError. The denial must still win over UNKNOWN_ERROR."""
    try:
        try:
            raise BedrockError(status_code=403, message=MARKETPLACE_BODY)
        except BedrockError as provider_error:
            raise APIConnectionError(
                message=f"BedrockException - {MARKETPLACE_BODY}",
                llm_provider="bedrock",
                model=MODEL,
            ) from provider_error
    except APIConnectionError as mapped:
        wrapped = RuntimeError(mapped)
        results = [
            litellm_exception_to_error_msg(error, None) for error in (mapped, wrapped)
        ]

    for msg, code, is_retryable in results:
        assert (code, is_retryable) == ("PERMISSION_DENIED", False)
        assert msg == f"Permission denied: {MARKETPLACE_MESSAGE}"


def test_local_access_denied_stays_connection_error() -> None:
    """Access-denied words in a local failure (not a provider response) that
    litellm wraps are not a provider access denial."""
    mapped = _mapped_by_litellm(PermissionError("[WinError 5] Access is denied"))
    assert isinstance(mapped, APIConnectionError)
    assert "access is denied" in str(mapped).lower()

    _, code, is_retryable = litellm_exception_to_error_msg(mapped, None)

    assert (code, is_retryable) == ("CONNECTION_ERROR", True)
    assert find_access_denial(mapped) is None


def test_access_denied_text_without_status_is_permission_denied() -> None:
    error = APIConnectionError(
        message=f"BedrockException - {MARKETPLACE_BODY}",
        llm_provider="bedrock",
        model=MODEL,
    )

    msg, code, is_retryable = litellm_exception_to_error_msg(error, None)

    assert (code, is_retryable) == ("PERMISSION_DENIED", False)
    assert msg == f"Permission denied: {MARKETPLACE_MESSAGE}"


def test_401_under_connection_error_is_auth_error() -> None:
    # litellm maps a Bedrock 401 itself; other providers' catch-all does not.
    try:
        try:
            raise BedrockError(status_code=401, message='{"message":"Bad token"}')
        except BedrockError:
            raise APIConnectionError(
                message='SomeException - {"message":"Bad token"}',
                llm_provider="some",
                model=MODEL,
            )
    except APIConnectionError as mapped:
        msg, code, is_retryable = litellm_exception_to_error_msg(mapped, None)

    assert (code, is_retryable) == ("AUTH_ERROR", False)
    assert msg.endswith("Provider error: Bad token")


def test_network_failure_stays_connection_error() -> None:
    request = httpx.Request("POST", "https://bedrock-runtime.example.com")
    mapped = _mapped_by_litellm(
        httpx.ConnectError("[Errno 111] Connection refused", request=request)
    )
    assert isinstance(mapped, APIConnectionError)

    msg, code, is_retryable = litellm_exception_to_error_msg(mapped, None)

    assert (code, is_retryable) == ("CONNECTION_ERROR", True)
    assert msg.startswith("API connection error:")
    assert find_access_denial(mapped) is None


def test_permission_denied_error_shows_provider_message() -> None:
    error = PermissionDeniedError(
        message=f"BedrockException PermissionDeniedError - {MARKETPLACE_BODY}",
        llm_provider="bedrock",
        model=MODEL,
        response=httpx.Response(
            403, request=httpx.Request("POST", "https://example.com")
        ),
    )

    msg, code, is_retryable = litellm_exception_to_error_msg(error, None)

    assert (code, is_retryable) == ("PERMISSION_DENIED", False)
    assert msg == f"Permission denied: {MARKETPLACE_MESSAGE}"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            'litellm.APIConnectionError: AnthropicException - {"type":"error",'
            '"error":{"type":"permission_error","message":"No access"}}',
            "No access",
        ),
        ("plain   text\nover lines", "plain text over lines"),
        ("b'not json'", "not json"),
        ("x" * 5000, "x" * 599 + "…"),
    ],
)
def test_provider_error_detail_unwraps_envelopes(raw: str, expected: str) -> None:
    assert provider_error_detail(Exception(raw)) == expected
