import base64
import binascii
from dataclasses import dataclass
from functools import lru_cache
from os import urandom
from types import MappingProxyType
from typing import Any
from typing import Mapping

import boto3
from botocore.exceptions import BotoCoreError
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from onyx.configs.app_configs import AWS_ENCRYPTED_DEK_PARAM
from onyx.configs.app_configs import AWS_KMS_KEY_ID
from onyx.configs.app_configs import AWS_REGION_NAME
from onyx.configs.app_configs import ENCRYPTION_KEY_SECRET
from onyx.configs.app_configs import SECRET_ENCRYPTION_MODE
from onyx.configs.app_configs import SECRET_ENCRYPTION_REQUIRED
from onyx.configs.app_configs import SECRET_KEY_VERSION
from onyx.configs.app_configs import SECRET_OLD_KEY_VERSIONS
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_AUTHENTICATION_METHOD,
)
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_versioned_implementation
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

logger = setup_logger()

_SECRET_ENCRYPTION_MODE_DISABLED = "disabled"
_SECRET_ENCRYPTION_MODE_AWS_KMS_ENVELOPE = "aws_kms_envelope"
# ONYXENC2 wire format (all offsets are byte offsets):
# [0:8]   magic prefix b"ONYXENC2"
# [8:9]   key version (uint8)
# [9:21]  nonce (12 bytes)
# [21:N]  AES-GCM ciphertext || tag (tag length 16 bytes)
_ENCRYPTION_MAGIC_PREFIX = b"ONYXENC2"
_ENCRYPTION_NONCE_LENGTH = 12
_ENCRYPTION_KEY_LENGTH = 32
_ENCRYPTION_AAD = f"onyx-secret-v2:{POSTGRES_DEFAULT_SCHEMA or 'public'}".encode(
    "utf-8"
)


@dataclass(frozen=True)
class _EnvelopeKeyring:
    active_version: int
    key_by_version: Mapping[int, bytes]

    def is_encrypted_payload(self, payload: bytes) -> bool:
        return payload.startswith(_ENCRYPTION_MAGIC_PREFIX)

    def encrypt(self, plaintext: bytes) -> bytes:
        nonce = urandom(_ENCRYPTION_NONCE_LENGTH)
        active_key = self.key_by_version[self.active_version]
        ciphertext = AESGCM(active_key).encrypt(nonce, plaintext, _ENCRYPTION_AAD)
        return (
            _ENCRYPTION_MAGIC_PREFIX
            + bytes([self.active_version])
            + nonce
            + ciphertext
        )

    def decrypt(self, payload: bytes) -> bytes:
        if not self.is_encrypted_payload(payload):
            raise RuntimeError("Invalid encrypted payload prefix.")

        min_payload_length = (
            len(_ENCRYPTION_MAGIC_PREFIX) + 1 + _ENCRYPTION_NONCE_LENGTH + 16
        )
        if len(payload) < min_payload_length:
            raise RuntimeError("Invalid encrypted payload format.")

        key_version = payload[len(_ENCRYPTION_MAGIC_PREFIX)]
        key = self.key_by_version.get(key_version)
        if key is None:
            raise RuntimeError(
                "No decryption key available for payload key version "
                f"{key_version}. Active version is {self.active_version}."
            )

        nonce_start = len(_ENCRYPTION_MAGIC_PREFIX) + 1
        nonce_end = nonce_start + _ENCRYPTION_NONCE_LENGTH
        nonce = payload[nonce_start:nonce_end]
        ciphertext = payload[nonce_end:]

        try:
            return AESGCM(key).decrypt(nonce, ciphertext, _ENCRYPTION_AAD)
        except Exception as e:
            raise RuntimeError("Failed to decrypt encrypted payload.") from e


def _validate_key_version(key_version: int) -> None:
    if key_version < 0 or key_version > 255:
        raise RuntimeError(
            f"Invalid key version {key_version}. Key versions must be in [0, 255]."
        )


def _validate_encryption_mode() -> None:
    if SECRET_ENCRYPTION_MODE not in (
        _SECRET_ENCRYPTION_MODE_DISABLED,
        _SECRET_ENCRYPTION_MODE_AWS_KMS_ENVELOPE,
    ):
        raise RuntimeError(
            "Invalid SECRET_ENCRYPTION_MODE "
            f"'{SECRET_ENCRYPTION_MODE}'. Supported values are "
            f"'{_SECRET_ENCRYPTION_MODE_DISABLED}' and "
            f"'{_SECRET_ENCRYPTION_MODE_AWS_KMS_ENVELOPE}'."
        )


def _get_ssm_parameter_client() -> Any:
    return boto3.client("ssm", region_name=AWS_REGION_NAME)


def _get_kms_client() -> Any:
    return boto3.client("kms", region_name=AWS_REGION_NAME)


def _resolve_dek_param_name(key_version: int) -> str:
    _validate_key_version(key_version)
    param_name_template = AWS_ENCRYPTED_DEK_PARAM.strip()
    if not param_name_template:
        raise RuntimeError(
            "AWS_ENCRYPTED_DEK_PARAM must be set when "
            "SECRET_ENCRYPTION_MODE=aws_kms_envelope."
        )

    if "{version}" in param_name_template:
        return param_name_template.replace("{version}", str(key_version))

    if key_version != SECRET_KEY_VERSION:
        raise RuntimeError(
            "SECRET_OLD_KEY_VERSIONS is set, but AWS_ENCRYPTED_DEK_PARAM does not "
            "contain a '{version}' placeholder."
        )

    return param_name_template


def _fetch_encrypted_dek_from_ssm(param_name: str) -> bytes:
    ssm_client = _get_ssm_parameter_client()
    try:
        # We store a base64-encoded KMS CiphertextBlob in the parameter value.
        # WithDecryption decrypts the SSM SecureString envelope, then we still
        # decrypt the returned KMS ciphertext blob below.
        response = ssm_client.get_parameter(Name=param_name, WithDecryption=True)
        param_value = response["Parameter"]["Value"]
    except (BotoCoreError, ClientError, KeyError):
        raise RuntimeError(
            "Failed to fetch encrypted DEK from AWS SSM Parameter Store."
        )

    if not isinstance(param_value, str):
        raise RuntimeError("Encrypted DEK parameter did not return a string value.")

    try:
        encrypted_dek = base64.b64decode(param_value, validate=True)
    except binascii.Error as e:
        raise RuntimeError(
            "Encrypted DEK parameter is not valid base64-encoded ciphertext."
        ) from e

    if not encrypted_dek:
        raise RuntimeError("Encrypted DEK parameter returned an empty value.")

    return encrypted_dek


def _decrypt_dek_with_kms(encrypted_dek: bytes) -> bytes:
    kms_client = _get_kms_client()
    decrypt_kwargs: dict[str, Any] = {"CiphertextBlob": encrypted_dek}
    if AWS_KMS_KEY_ID:
        decrypt_kwargs["KeyId"] = AWS_KMS_KEY_ID

    try:
        response = kms_client.decrypt(**decrypt_kwargs)
    except (BotoCoreError, ClientError, KeyError) as e:
        raise RuntimeError("Failed to decrypt DEK with AWS KMS.") from e

    plaintext_key = response.get("Plaintext")
    if not isinstance(plaintext_key, (bytes, bytearray)):
        raise RuntimeError("KMS decrypt response did not include plaintext key bytes.")

    key_bytes = bytes(plaintext_key)
    if len(key_bytes) != _ENCRYPTION_KEY_LENGTH:
        raise RuntimeError(
            "Invalid DEK length from KMS decrypt. Expected "
            f"{_ENCRYPTION_KEY_LENGTH} bytes, received {len(key_bytes)}."
        )
    return key_bytes


@lru_cache(maxsize=1)
def _load_envelope_keyring() -> _EnvelopeKeyring:
    _validate_encryption_mode()
    if SECRET_ENCRYPTION_MODE != _SECRET_ENCRYPTION_MODE_AWS_KMS_ENVELOPE:
        raise RuntimeError(
            "Envelope keyring requested while SECRET_ENCRYPTION_MODE is not "
            "aws_kms_envelope."
        )

    _validate_key_version(SECRET_KEY_VERSION)
    versions_to_load = [SECRET_KEY_VERSION, *SECRET_OLD_KEY_VERSIONS]
    key_by_version: dict[int, bytes] = {}
    for version in versions_to_load:
        param_name = _resolve_dek_param_name(version)
        encrypted_dek = _fetch_encrypted_dek_from_ssm(param_name)
        key_by_version[version] = _decrypt_dek_with_kms(encrypted_dek)

    return _EnvelopeKeyring(
        active_version=SECRET_KEY_VERSION,
        key_by_version=MappingProxyType(key_by_version),
    )


def clear_secret_encryption_cache() -> None:
    """Clears in-process encryption key cache. Useful for tests and key rollout."""
    _load_envelope_keyring.cache_clear()


def is_versioned_encrypted_payload(payload: bytes) -> bool:
    return payload.startswith(_ENCRYPTION_MAGIC_PREFIX)


# IMPORTANT DO NOT DELETE, THIS IS USED BY fetch_versioned_implementation
def _encrypt_string(input_str: str) -> bytes:
    _validate_encryption_mode()
    if SECRET_ENCRYPTION_MODE == _SECRET_ENCRYPTION_MODE_DISABLED:
        if SECRET_ENCRYPTION_REQUIRED:
            raise RuntimeError(
                "Secret encryption is required, but SECRET_ENCRYPTION_MODE=disabled."
            )
        return input_str.encode("utf-8")

    keyring = _load_envelope_keyring()
    return keyring.encrypt(input_str.encode("utf-8"))


def _decrypt_legacy_aes_cbc(input_bytes: bytes) -> str:
    """Decrypt data encrypted with the old AES-CBC scheme (ENCRYPTION_KEY_SECRET).
    Used as a fallback during migration from the legacy EE encryption to KMS."""
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import algorithms
    from cryptography.hazmat.primitives.ciphers import Cipher
    from cryptography.hazmat.primitives.ciphers import modes

    if not ENCRYPTION_KEY_SECRET:
        raise RuntimeError(
            "Cannot decrypt legacy AES-CBC data: ENCRYPTION_KEY_SECRET is not set."
        )

    encoded_key = ENCRYPTION_KEY_SECRET.encode()
    key_length = len(encoded_key)
    if key_length > 32:
        key = ENCRYPTION_KEY_SECRET[:32].encode()
    elif key_length not in (16, 24, 32):
        valid_lengths = [16, 24, 32]
        trim_to = min(valid_lengths, key=lambda x: abs(x - key_length))
        key = ENCRYPTION_KEY_SECRET[:trim_to].encode()
    else:
        key = encoded_key

    iv = input_bytes[:16]
    encrypted_data = input_bytes[16:]

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted_padded = decryptor.update(encrypted_data) + decryptor.finalize()

    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    decrypted = unpadder.update(decrypted_padded) + unpadder.finalize()

    return decrypted.decode()


# IMPORTANT DO NOT DELETE, THIS IS USED BY fetch_versioned_implementation
def _decrypt_bytes(input_bytes: bytes) -> str:
    _validate_encryption_mode()
    if SECRET_ENCRYPTION_MODE == _SECRET_ENCRYPTION_MODE_DISABLED:
        if SECRET_ENCRYPTION_REQUIRED:
            raise RuntimeError(
                "Secret encryption is required, but SECRET_ENCRYPTION_MODE=disabled."
            )
        return input_bytes.decode("utf-8")

    keyring = _load_envelope_keyring()
    if not keyring.is_encrypted_payload(input_bytes):
        # Legacy fallback for migration compatibility.
        # Try plaintext UTF-8 first, then old AES-CBC decryption.
        try:
            return input_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return _decrypt_legacy_aes_cbc(input_bytes)

    return keyring.decrypt(input_bytes).decode("utf-8")


def _ensure_secret_encryption_ready() -> None:
    _validate_encryption_mode()
    if SECRET_ENCRYPTION_MODE == _SECRET_ENCRYPTION_MODE_DISABLED:
        if SECRET_ENCRYPTION_REQUIRED:
            raise RuntimeError(
                "Secret encryption is required, but SECRET_ENCRYPTION_MODE=disabled."
            )
        return

    keyring = _load_envelope_keyring()
    test_payload = "onyx-secret-readiness-check"
    encrypted = keyring.encrypt(test_payload.encode("utf-8"))
    decrypted = keyring.decrypt(encrypted).decode("utf-8")
    if decrypted != test_payload:
        raise RuntimeError("Secret encryption readiness check failed.")


def mask_string(sensitive_str: str) -> str:
    """Masks a sensitive string, showing first and last few characters.
    If the string is too short to safely mask, returns a fully masked placeholder.
    """
    visible_start = 4
    visible_end = 4
    min_masked_chars = 6

    if len(sensitive_str) < visible_start + visible_end + min_masked_chars:
        return "••••••••••••"

    return f"{sensitive_str[:visible_start]}...{sensitive_str[-visible_end:]}"


MASK_CREDENTIALS_WHITELIST = {
    DB_CREDENTIALS_AUTHENTICATION_METHOD,
    "wiki_base",
    "cloud_name",
    "cloud_id",
}


def mask_credential_dict(credential_dict: dict[str, Any]) -> dict[str, Any]:
    masked_creds: dict[str, Any] = {}
    for key, val in credential_dict.items():
        if isinstance(val, str):
            # we want to pass the authentication_method field through so the frontend
            # can disambiguate credentials created by different methods
            if key in MASK_CREDENTIALS_WHITELIST:
                masked_creds[key] = val
            else:
                masked_creds[key] = mask_string(val)
        elif isinstance(val, dict):
            masked_creds[key] = mask_credential_dict(val)
        elif isinstance(val, list):
            masked_creds[key] = _mask_list(val)
        elif isinstance(val, (bool, type(None))):
            masked_creds[key] = val
        elif isinstance(val, (int, float)):
            masked_creds[key] = "*****"
        else:
            masked_creds[key] = "*****"

    return masked_creds


def _mask_list(items: list[Any]) -> list[Any]:
    masked: list[Any] = []
    for item in items:
        if isinstance(item, dict):
            masked.append(mask_credential_dict(item))
        elif isinstance(item, str):
            masked.append(mask_string(item))
        elif isinstance(item, list):
            masked.append(_mask_list(item))
        elif isinstance(item, (bool, type(None))):
            masked.append(item)
        else:
            masked.append("*****")
    return masked


def ensure_secret_encryption_ready() -> None:
    versioned_check_fn = fetch_versioned_implementation(
        "onyx.utils.encryption", "_ensure_secret_encryption_ready"
    )
    versioned_check_fn()


def encrypt_string_to_bytes(input_str: str) -> bytes:
    versioned_encryption_fn = fetch_versioned_implementation(
        "onyx.utils.encryption", "_encrypt_string"
    )
    return versioned_encryption_fn(input_str)


def decrypt_bytes_to_string(input_bytes: bytes) -> str:
    versioned_decryption_fn = fetch_versioned_implementation(
        "onyx.utils.encryption", "_decrypt_bytes"
    )
    return versioned_decryption_fn(input_bytes)
