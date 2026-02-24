from functools import lru_cache
from os import urandom

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers import modes

from onyx.configs.app_configs import ENCRYPTION_KEY_SECRET
from onyx.configs.app_configs import SECRET_ENCRYPTION_MODE
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_versioned_implementation

logger = setup_logger()


@lru_cache(maxsize=1)
def _get_trimmed_key(key: str) -> bytes:
    encoded_key = key.encode()
    key_length = len(encoded_key)
    if key_length < 16:
        raise RuntimeError("Invalid ENCRYPTION_KEY_SECRET - too short")
    elif key_length > 32:
        key = key[:32]
    elif key_length not in (16, 24, 32):
        valid_lengths = [16, 24, 32]
        key = key[: min(valid_lengths, key=lambda x: abs(x - key_length))]

    return key.encode()


@lru_cache(maxsize=1)
def _warn_on_secret_encryption_mode_mismatch() -> None:
    if SECRET_ENCRYPTION_MODE != "disabled":
        logger.warning(
            "SECRET_ENCRYPTION_MODE=%s is configured, but EE currently uses "
            "ENCRYPTION_KEY_SECRET for credential encryption.",
            SECRET_ENCRYPTION_MODE,
        )


def _encrypt_string(input_str: str) -> bytes:
    _warn_on_secret_encryption_mode_mismatch()
    if not ENCRYPTION_KEY_SECRET:
        raise RuntimeError(
            "ENCRYPTION_KEY_SECRET is not set. Refusing to store credentials "
            "as plaintext. Set this environment variable before creating credentials."
        )

    key = _get_trimmed_key(ENCRYPTION_KEY_SECRET)
    iv = urandom(16)
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded_data = padder.update(input_str.encode()) + padder.finalize()

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    encrypted_data = encryptor.update(padded_data) + encryptor.finalize()

    return iv + encrypted_data


def _decrypt_bytes(input_bytes: bytes) -> str:
    _warn_on_secret_encryption_mode_mismatch()
    if not ENCRYPTION_KEY_SECRET:
        raise RuntimeError(
            "ENCRYPTION_KEY_SECRET is not set. Cannot decrypt credentials. "
            "Set this environment variable before starting the server."
        )

    # AES-CBC ciphertext is always at least 32 bytes (16-byte IV + 16-byte block).
    # Shorter data was stored before encryption was enabled — return as plain text.
    if len(input_bytes) < 32:
        return input_bytes.decode()

    key = _get_trimmed_key(ENCRYPTION_KEY_SECRET)
    iv = input_bytes[:16]
    encrypted_data = input_bytes[16:]

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted_padded_data = decryptor.update(encrypted_data) + decryptor.finalize()

    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    decrypted_data = unpadder.update(decrypted_padded_data) + unpadder.finalize()

    return decrypted_data.decode()


def _ensure_secret_encryption_ready() -> None:
    _warn_on_secret_encryption_mode_mismatch()
    if not ENCRYPTION_KEY_SECRET:
        raise RuntimeError(
            "ENCRYPTION_KEY_SECRET is not set. Cannot validate secret encryption readiness."
        )

    test_payload = "onyx-secret-readiness-check"
    encrypted = _encrypt_string(test_payload)
    decrypted = _decrypt_bytes(encrypted)
    if decrypted != test_payload:
        raise RuntimeError("Secret encryption readiness check failed")


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


def test_encryption() -> None:
    test_string = "Onyx is the BEST!"
    encrypted_bytes = encrypt_string_to_bytes(test_string)
    decrypted_string = decrypt_bytes_to_string(encrypted_bytes)
    if test_string != decrypted_string:
        raise RuntimeError("Encryption decryption test failed")
