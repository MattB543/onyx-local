import importlib
import os

import pytest

from onyx.configs import app_configs


@pytest.fixture(autouse=True)
def _reset_secret_encryption_env() -> None:
    original_mode = os.environ.get("SECRET_ENCRYPTION_MODE")
    original_key_version = os.environ.get("SECRET_KEY_VERSION")
    original_old_versions = os.environ.get("SECRET_OLD_KEY_VERSIONS")

    yield

    if original_mode is None:
        os.environ.pop("SECRET_ENCRYPTION_MODE", None)
    else:
        os.environ["SECRET_ENCRYPTION_MODE"] = original_mode

    if original_key_version is None:
        os.environ.pop("SECRET_KEY_VERSION", None)
    else:
        os.environ["SECRET_KEY_VERSION"] = original_key_version

    if original_old_versions is None:
        os.environ.pop("SECRET_OLD_KEY_VERSIONS", None)
    else:
        os.environ["SECRET_OLD_KEY_VERSIONS"] = original_old_versions

    importlib.reload(app_configs)


def test_invalid_secret_key_version_raises_when_encryption_enabled() -> None:
    os.environ["SECRET_ENCRYPTION_MODE"] = "aws_kms_envelope"
    os.environ["SECRET_KEY_VERSION"] = "two"
    os.environ["SECRET_OLD_KEY_VERSIONS"] = ""

    with pytest.raises(RuntimeError, match="Invalid SECRET_KEY_VERSION"):
        importlib.reload(app_configs)


def test_invalid_secret_key_version_falls_back_when_disabled() -> None:
    os.environ["SECRET_ENCRYPTION_MODE"] = "disabled"
    os.environ["SECRET_KEY_VERSION"] = "two"
    os.environ["SECRET_OLD_KEY_VERSIONS"] = ""

    reloaded = importlib.reload(app_configs)
    assert reloaded.SECRET_KEY_VERSION == 1


def test_invalid_old_key_versions_raises_when_encryption_enabled() -> None:
    os.environ["SECRET_ENCRYPTION_MODE"] = "aws_kms_envelope"
    os.environ["SECRET_KEY_VERSION"] = "1"
    os.environ["SECRET_OLD_KEY_VERSIONS"] = "2,three"

    with pytest.raises(RuntimeError, match="Invalid SECRET_OLD_KEY_VERSIONS item"):
        importlib.reload(app_configs)


def test_invalid_old_key_versions_ignored_when_disabled() -> None:
    os.environ["SECRET_ENCRYPTION_MODE"] = "disabled"
    os.environ["SECRET_KEY_VERSION"] = "1"
    os.environ["SECRET_OLD_KEY_VERSIONS"] = "2,three,4"

    reloaded = importlib.reload(app_configs)
    assert reloaded.SECRET_OLD_KEY_VERSIONS == [2, 4]
