import os
from types import MappingProxyType

import pytest

from onyx.utils import encryption


@pytest.fixture(autouse=True)
def _reset_encryption_cache() -> None:
    encryption.clear_secret_encryption_cache()


def _set_aws_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(encryption, "SECRET_ENCRYPTION_MODE", "aws_kms_envelope")
    monkeypatch.setattr(encryption, "SECRET_ENCRYPTION_REQUIRED", False)


def test_encrypt_decrypt_round_trip_in_aws_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_aws_mode(monkeypatch)
    keyring = encryption._EnvelopeKeyring(
        active_version=1,
        key_by_version={1: os.urandom(32)},
    )
    monkeypatch.setattr(encryption, "_load_envelope_keyring", lambda: keyring)

    encrypted = encryption._encrypt_string("super-secret")
    assert encryption.is_versioned_encrypted_payload(encrypted)
    assert encrypted[len(encryption._ENCRYPTION_MAGIC_PREFIX)] == 1
    assert encryption._decrypt_bytes(encrypted) == "super-secret"


def test_tampered_ciphertext_fails_decryption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_aws_mode(monkeypatch)
    keyring = encryption._EnvelopeKeyring(
        active_version=1,
        key_by_version={1: os.urandom(32)},
    )
    monkeypatch.setattr(encryption, "_load_envelope_keyring", lambda: keyring)

    encrypted = bytearray(encryption._encrypt_string("sensitive-value"))
    encrypted[-1] ^= 1

    with pytest.raises(RuntimeError):
        encryption._decrypt_bytes(bytes(encrypted))


def test_legacy_plaintext_fallback_in_aws_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_aws_mode(monkeypatch)
    keyring = encryption._EnvelopeKeyring(
        active_version=1,
        key_by_version={1: os.urandom(32)},
    )
    monkeypatch.setattr(encryption, "_load_envelope_keyring", lambda: keyring)

    assert encryption._decrypt_bytes(b'{"token":"legacy"}') == '{"token":"legacy"}'


def test_can_decrypt_old_key_version_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_aws_mode(monkeypatch)
    v1_key = os.urandom(32)
    v2_key = os.urandom(32)

    old_keyring = encryption._EnvelopeKeyring(active_version=1, key_by_version={1: v1_key})
    new_keyring = encryption._EnvelopeKeyring(
        active_version=2,
        key_by_version={1: v1_key, 2: v2_key},
    )
    monkeypatch.setattr(encryption, "_load_envelope_keyring", lambda: new_keyring)

    old_payload = old_keyring.encrypt(b"token-v1")
    assert encryption._decrypt_bytes(old_payload) == "token-v1"

    new_payload = encryption._encrypt_string("token-v2")
    assert new_payload[len(encryption._ENCRYPTION_MAGIC_PREFIX)] == 2


def test_required_mode_fails_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(encryption, "SECRET_ENCRYPTION_MODE", "disabled")
    monkeypatch.setattr(encryption, "SECRET_ENCRYPTION_REQUIRED", True)

    with pytest.raises(RuntimeError):
        encryption._ensure_secret_encryption_ready()


def test_decrypt_rejects_invalid_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_aws_mode(monkeypatch)
    keyring = encryption._EnvelopeKeyring(
        active_version=1,
        key_by_version={1: os.urandom(32)},
    )
    monkeypatch.setattr(encryption, "_load_envelope_keyring", lambda: keyring)

    with pytest.raises(RuntimeError, match="prefix"):
        keyring.decrypt(b"legacy-plaintext")


def test_dek_param_template_replace_does_not_require_format_placeholders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        encryption,
        "AWS_ENCRYPTED_DEK_PARAM",
        "/onyx/{env}/encrypted_dek-v{version}",
    )
    monkeypatch.setattr(encryption, "SECRET_KEY_VERSION", 1)

    resolved = encryption._resolve_dek_param_name(2)
    assert resolved == "/onyx/{env}/encrypted_dek-v2"


def test_decrypt_rejects_truncated_payload() -> None:
    keyring = encryption._EnvelopeKeyring(
        active_version=1,
        key_by_version={1: os.urandom(32)},
    )
    truncated_payload = encryption._ENCRYPTION_MAGIC_PREFIX + b"\x01" + b"\x00" * 3

    with pytest.raises(RuntimeError, match="format"):
        keyring.decrypt(truncated_payload)


def test_load_envelope_keyring_uses_mapping_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_aws_mode(monkeypatch)
    monkeypatch.setattr(encryption, "SECRET_KEY_VERSION", 1)
    monkeypatch.setattr(encryption, "SECRET_OLD_KEY_VERSIONS", [2])
    monkeypatch.setattr(
        encryption,
        "AWS_ENCRYPTED_DEK_PARAM",
        "/onyx/prod/encrypted_dek/v{version}",
    )
    monkeypatch.setattr(
        encryption,
        "_fetch_encrypted_dek_from_ssm",
        lambda _: b"encrypted-dek",
    )
    monkeypatch.setattr(
        encryption,
        "_decrypt_dek_with_kms",
        lambda _: os.urandom(32),
    )

    keyring = encryption._load_envelope_keyring()

    assert isinstance(keyring.key_by_version, MappingProxyType)
    with pytest.raises(TypeError):
        keyring.key_by_version[3] = os.urandom(32)
