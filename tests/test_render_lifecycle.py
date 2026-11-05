"""Exercise remote-render orchestration locally with controlled command results."""

import json
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from karaoke_app import cli


@pytest.fixture
def render(tmp_path, monkeypatch):
    document = {
        "schema_version": 2, "title": "Song", "video": {"width": 640, "height": 360, "fps": 24},
        "media": {"lyrics": "lyrics.yaml", "vocals_audio": "vocals.flac",
                  "original_audio": "original.flac", "instrumental_audio": "instrumental.flac"},
        "background": {"kind": "solid", "color": "#000000"}, "watermark": {"enabled": False},
    }
    monkeypatch.setattr(cli, "_validate_installation", Mock())
    monkeypatch.setattr("karaoke_app.job_document.load_job_document", lambda root: document)
    monkeypatch.setattr("karaoke_app.job_document.resolve_job_asset", lambda *args: tmp_path / "lyrics.yaml")
    monkeypatch.setattr("karaoke_app.lyrics_file.load_lyrics_file", lambda *args, **kwargs: {})
    monkeypatch.setattr("karaoke_app.lyrics_file.lyrics_to_transcript", lambda lyrics: {"segments": []})
    monkeypatch.setattr("karaoke_app.ass.generate_ass", lambda *args, **kwargs: "ass")
    monkeypatch.setattr("karaoke_app.srt.generate_srt", lambda transcript: "srt")
    monkeypatch.setattr(cli, "_create_render_bundle", Mock())
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[2] == "download":
            destination = Path(command[-1])
            if command[-2] == str(cli.REMOTE_STATUS):
                destination.write_text(json.dumps({"status": "completed"}))
            else:
                with zipfile.ZipFile(destination, "w") as archive:
                    archive.writestr("Song_lyrics.mp4", b"encoded video")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(cli, "_run", run)
    return cli.build_render_parser().parse_args([str(tmp_path), "--mode", "lyrics"]), run, calls


@pytest.mark.parametrize("operation", ["new", "exec", "download"])
def test_cancelled_render_always_attempts_bounded_shutdown(render, monkeypatch, operation):
    args, run, calls = render

    def cancel(command, **kwargs):
        if command[2] == operation:
            raise KeyboardInterrupt
        return run(command, **kwargs)

    monkeypatch.setattr(cli, "_run", cancel)
    with pytest.raises(KeyboardInterrupt):
        cli.render_colab(args)
    assert calls[-1][0][2] == "stop"
    assert calls[-1][1]["timeout"] == 60


def test_stop_failure_is_reported_without_deleting_downloaded_video(render, monkeypatch):
    args, run, calls = render

    def stop_fails(command, **kwargs):
        if command[2] == "stop":
            return subprocess.CompletedProcess(command, 1)
        return run(command, **kwargs)

    monkeypatch.setattr(cli, "_run", stop_fails)
    with pytest.raises(RuntimeError, match="stop was not confirmed"):
        cli.render_colab(args)
    assert list(args.job_dir.glob("renders/*/Song_lyrics.mp4"))
    assert calls


def test_render_download_retries_before_publishing(render, monkeypatch):
    args, run, _ = render
    attempts = 0

    def transient(command, **kwargs):
        nonlocal attempts
        if command[2] == "download" and command[-2] == str(cli.REMOTE_ARCHIVE):
            attempts += 1
            if attempts < 3:
                Path(command[-1]).write_bytes(b"partial archive")
                return subprocess.CompletedProcess(command, 1)
        return run(command, **kwargs)

    monkeypatch.setattr(cli, "_run", transient)
    output = cli.render_colab(args)
    assert attempts == 3
    assert (output / "Song_lyrics.mp4").read_bytes() == b"encoded video"
    assert not list(output.glob("*.partial"))


def test_render_rejects_invalid_timeout_before_any_command(render):
    args, _, calls = render
    args.timeout = 0
    with pytest.raises(ValueError, match="Timeout"):
        cli.render_colab(args)
    assert not calls
