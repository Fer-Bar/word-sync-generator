import subprocess
from unittest.mock import patch

import pytest

from karaoke_app import cli
from karaoke_app.terminal import ProcessFailure
from karaoke_app.upload_diagnostics import LARGE_UPLOAD_BYTES, upload_size, warn_large_upload


@pytest.mark.parametrize(
    ("cause", "expected"),
    [
        ("413 Client Error: Request Entity Too Large", "rejected the request as too large"),
        ("400 Client Error: Bad Request", "not confirmed by this status"),
        ("401 Client Error: Unauthorized", "no evidence here that file size caused it"),
        ("Connection timed out", "no evidence here that file size caused it"),
    ],
)
def test_failed_upload_preserves_cause_and_reports_size(tmp_path, cause, expected):
    path = tmp_path / "render.zip"
    path.write_bytes(b"test")
    error = ProcessFailure(
        "Uploading project", subprocess.CompletedProcess([], 1, "", f"[colab] Upload failed: {cause}")
    )
    with patch.object(cli, "_run", side_effect=error) as runner:
        with pytest.raises(RuntimeError) as failure:
            cli._upload(["colab", "--auth=oauth2"], "session", path, tmp_path / "remote.zip")
    assert failure.value.__cause__ is error
    assert expected in str(failure.value)
    assert cause in str(failure.value)
    assert "render.zip" in str(failure.value)
    assert "base64 payload" in str(failure.value)
    runner.assert_called_once()


def test_large_upload_warning_is_advisory_and_does_not_read_file(tmp_path, caplog):
    path = tmp_path / "large.zip"
    with path.open("wb") as stream:
        stream.truncate(LARGE_UPLOAD_BYTES)
    warn_large_upload(path)
    assert "not a confirmed Colab limit" in caplog.text
    assert "64.0 MiB" in caplog.text
    assert "85.3 MiB" in upload_size(path)


def test_small_upload_has_no_size_warning(tmp_path, caplog):
    path = tmp_path / "small.zip"
    path.write_bytes(b"test")
    warn_large_upload(path)
    assert not caplog.records
