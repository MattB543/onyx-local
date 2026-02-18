from onyx.configs.constants import DocumentSource
from onyx.connectors.google_utils.shared_constants import GOOGLE_SCOPES


def test_google_drive_scopes_include_read_and_write_permissions() -> None:
    drive_scopes = GOOGLE_SCOPES[DocumentSource.GOOGLE_DRIVE]

    assert "https://www.googleapis.com/auth/drive.readonly" in drive_scopes
    assert "https://www.googleapis.com/auth/drive.metadata.readonly" in drive_scopes
    assert "https://www.googleapis.com/auth/drive.file" in drive_scopes
    assert "https://www.googleapis.com/auth/documents" in drive_scopes
