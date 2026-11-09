"""Real local render preparation and recovery; only Colab transport is controlled."""

import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from karaoke_app import cli
from karaoke_app.job_document import JOB_FILENAME


@pytest.fixture
def render(prepared_project, monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[2] == "upload":
            for item in command:
                if str(item).endswith("render-job.zip") and Path(item).is_file():
                    with zipfile.ZipFile(item) as archive:
                        assert archive.testzip() is None
                        document = json.loads(archive.read(JOB_FILENAME))
                        assert document["media"]["original_audio"] in archive.namelist()
                        assert {"lyrics.ass", "lyrics.srt"} <= set(archive.namelist())
                        assert "Hello world" in archive.read("lyrics.srt").decode()
                        assert "Dialogue:" in archive.read("lyrics.ass").decode()
        if command[2] == "download":
            destination = Path(command[-1])
            if command[-2] == str(cli.REMOTE_STATUS):
                destination.write_text(json.dumps({"status": "completed"}))
            else:
                with zipfile.ZipFile(destination, "w") as archive:
                    archive.writestr("Song_lyrics.mp4", b"remote encoded video")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(cli, "_run", run)
    return cli.build_render_parser().parse_args([str(prepared_project), "--mode", "lyrics"]), run, calls


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
    assert (output / "Song_lyrics.mp4").read_bytes() == b"remote encoded video"
    assert not list(output.glob("*.partial"))


def test_render_rejects_invalid_timeout_before_any_command(render):
    args, _, calls = render
    args.timeout = 0
    with pytest.raises(ValueError, match="Timeout"):
        cli.render_colab(args)
    assert not calls


@pytest.mark.parametrize("problem", ["missing_audio", "invalid_lyrics", "missing_word_timings"])
def test_invalid_project_fails_before_requesting_a_session(render, problem):
    args, _, calls = render
    if problem == "missing_audio":
        (args.job_dir / "original.wav").unlink()
    elif problem == "invalid_lyrics":
        (args.job_dir / "lyrics.yaml").write_text("version: [broken")
    else:
        (args.job_dir / "lyrics.yaml").write_text(
            'version: "1.0"\nmetadata: {title: Song}\n'
            'lines: [{text: Hello, start_ms: 200, end_ms: 800}]\n'
        )
    before = {p.relative_to(args.job_dir): p.read_bytes() for p in args.job_dir.rglob("*") if p.is_file()}
    with pytest.raises((FileNotFoundError, ValueError)):
        cli.render_colab(args)
    assert not calls
    assert not (args.job_dir / "renders").exists()
    assert {p.relative_to(args.job_dir): p.read_bytes() for p in args.job_dir.rglob("*") if p.is_file()} == before


def test_dry_run_validates_real_project_without_writes_or_colab(render):
    args, _, calls = render
    args.dry_run = True
    before = {p.relative_to(args.job_dir): p.read_bytes() for p in args.job_dir.rglob("*") if p.is_file()}
    assert cli.render_colab(args) == args.job_dir
    assert not calls
    assert {p.relative_to(args.job_dir): p.read_bytes() for p in args.job_dir.rglob("*") if p.is_file()} == before


def test_remote_failure_stops_session_without_publishing_result(render, monkeypatch):
    args, run, calls = render

    def failed_status(command, **kwargs):
        result = run(command, **kwargs)
        if command[2] == "download" and command[-2] == str(cli.REMOTE_STATUS):
            Path(command[-1]).write_text(json.dumps({"status": "failed", "error_summary": "Encoder failed"}))
        return result

    monkeypatch.setattr(cli, "_run", failed_status)
    with pytest.raises(RuntimeError, match="Encoder failed"):
        cli.render_colab(args)
    assert calls[-1][0][2] == "stop"
    assert not (args.job_dir / "renders").exists()
    assert not any(c[2] == "download" and c[-2] == str(cli.REMOTE_ARCHIVE) for c, _ in calls)
