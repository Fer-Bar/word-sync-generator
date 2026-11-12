import importlib.util
import json
import os
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from packaging.requirements import Requirement

from karaoke_app import notebook, resources


def test_config_accepts_external_read_only_inputs_without_writing(tmp_path):
    source = tmp_path / "input" / "song.wav"
    source.parent.mkdir()
    source.write_bytes(b"audio")
    runtime = tmp_path / "output" / "run"
    config = notebook.preparation_config(source, runtime, title="Song", artist="Singer", use_lrclib=False)
    assert config["source"]["value"] == str(source)
    assert config["lyrics"]["disable_lrclib"] is True
    assert config["archive_path"] == str(runtime / "prepared.zip")
    assert config["watermark"] == {"enabled": False}
    assert config["render_style"]["lyrics_effect"] == "classic"
    assert config["render_background"] == {"kind": "solid", "color": "#0B1020"}
    assert not runtime.exists()
    assert source.read_bytes() == b"audio"


@pytest.mark.parametrize("verify_word_timings", [False, True])
def test_preparation_passes_local_song_metadata_and_keeps_automatic_lyrics(tmp_path, monkeypatch, verify_word_timings):
    from colab import karaoke_job

    source = tmp_path / "song.wav"
    source.write_bytes(b"audio")
    seen = []
    monkeypatch.setattr(karaoke_job, "_probe_duration", lambda path: 120)

    def run(config_path, environment):
        config = json.loads(config_path.read_text())
        assert config["lyrics"]["disable_lrclib"] is False
        assert config["lyrics"]["text_path"] is None
        assert config["lyrics"]["verify_word_timings"] is True
        path, metadata = karaoke_job._acquire_source(config)
        assert path == source
        assert metadata["title"] == "Song title"
        assert metadata["artist"] == "Song artist"
        assert metadata["album"] == "Studio album"
        assert config["language"] == "es"
        seen.append(metadata)
        with zipfile.ZipFile(config["archive_path"], "w") as archive:
            archive.writestr("source.json", json.dumps(metadata))
        (config_path.parent / "karaoke_status.json").write_text('{"status":"completed"}')

    monkeypatch.setattr(notebook, "_run_preparation", run)
    result = notebook.prepare_audio(
        source, output_dir=tmp_path / "outputs", title="Song title", artist="Song artist",
        album="Studio album", language="es", verify_word_timings=verify_word_timings,
    )
    assert json.loads((result.directory / "source.json").read_text()) == seen[0]
    assert result.archive.is_file()
    assert source.read_bytes() == b"audio"


def test_invalid_source_does_not_create_output(tmp_path):
    output = tmp_path / "outputs"
    with pytest.raises(FileNotFoundError, match="Upload a local"):
        notebook.prepare_audio(tmp_path / "missing", output_dir=output)
    assert not output.exists()


def test_preparation_reuses_selected_model_cache_and_manual_language(tmp_path, monkeypatch):
    source = tmp_path / "song.wav"
    source.write_bytes(b"audio")
    cache = tmp_path / "persistent-models"

    def run(config_path, environment):
        config = json.loads(config_path.read_text())
        assert config["whisper_model"] == "medium"
        assert config["language"] == "fr"
        assert environment["KARAOKE_WHISPER_CACHE"] == str(cache)
        with zipfile.ZipFile(config["archive_path"], "w") as archive:
            archive.writestr("source.txt", "unchanged")
        (config_path.parent / "karaoke_status.json").write_text('{"status":"completed"}')

    monkeypatch.setattr(notebook, "_run_preparation", run)
    result = notebook.prepare_audio(
        source, output_dir=tmp_path / "output", language="fr", whisper_model="medium", whisper_cache=cache,
    )
    assert result.archive.is_file()
    assert source.read_bytes() == b"audio"


def test_preparation_uses_isolated_runtime_and_retains_both_runs(tmp_path, monkeypatch):
    source = tmp_path / "song.wav"
    source.write_bytes(b"audio")
    calls = []

    def launch(command, *, env, **kwargs):
        runtime = Path(env["KARAOKE_RUNTIME_DIR"])
        config_path = runtime / "karaoke_job.json"
        config = json.loads(config_path.read_text())
        assert command[-1] == str(resources.runtime_resource("karaoke_launch.py"))
        assert env["KARAOKE_STREAM_OUTPUT"] == "1"
        assert config["source"]["value"] == str(source)
        assert "source_bundle" not in config
        assert not (runtime / "source.zip").exists()
        with zipfile.ZipFile(config["archive_path"], "w") as archive:
            archive.writestr("lyrics.lyricsfile.yaml", "lines: []")
        (runtime / "karaoke_status.json").write_text('{"status":"completed"}')
        calls.append(runtime)
        process = MagicMock()
        process.__enter__.return_value = process
        process.stdout = []
        process.wait.return_value = 0
        return process

    monkeypatch.setattr(notebook.subprocess, "Popen", launch)
    first = notebook.prepare_audio(source, output_dir=tmp_path / "output")
    second = notebook.prepare_audio(source, output_dir=tmp_path / "output")
    assert first.directory != second.directory
    assert len(calls) == 2
    for result in (first, second):
        assert result.archive.is_file()
        assert result.archive.parent == tmp_path / "output"
        assert (result.directory / "lyrics.lyricsfile.yaml").is_file()
        assert (result.runtime / "karaoke_status.json").is_file()


def test_failure_preserves_status_and_reports_runtime(tmp_path, monkeypatch):
    source = tmp_path / "song.wav"
    source.write_bytes(b"audio")

    def fail(config_path, environment):
        (config_path.parent / "karaoke_status.json").write_text('{"status":"failed","stage":"lyrics"}')
        raise subprocess.CalledProcessError(1, ["pipeline"])

    monkeypatch.setattr(notebook, "_run_preparation", fail)
    with pytest.raises(RuntimeError, match="retained diagnostics and checkpoints"):
        notebook.prepare_audio(source, output_dir=tmp_path / "output")
    assert len(list((tmp_path / "output" / ".runs").glob("*/karaoke_status.json"))) == 1


def test_success_exit_without_completed_status_is_failure(tmp_path, monkeypatch):
    source = tmp_path / "song.wav"
    source.write_bytes(b"audio")

    def incomplete(config_path, environment):
        (config_path.parent / "karaoke_status.json").write_text('{"status":"failed","error":"alignment failed"}')

    monkeypatch.setattr(notebook, "_run_preparation", incomplete)
    with pytest.raises(RuntimeError, match="alignment failed"):
        notebook.prepare_audio(source, output_dir=tmp_path / "output")


@pytest.mark.parametrize("filename", ["../outside.txt", "/tmp/outside.txt"])
def test_extract_rejects_unsafe_member_before_writing(tmp_path, filename):
    archive_path = tmp_path / "input.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("safe.txt", "safe")
        archive.writestr(filename, "unsafe")
    destination = tmp_path / "project"
    with pytest.raises(ValueError, match="Unsafe project"):
        notebook._extract_project(archive_path, destination)
    assert not destination.exists()


def test_pipeline_uses_runtime_root_in_fresh_process(tmp_path):
    command = (
        "import importlib.util, sys; "
        "s=importlib.util.spec_from_file_location('pipeline', sys.argv[1]); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "print(m.CONFIG_PATH); print(m.WORK_DIR); print(m.RENDER_JOB_PATH)"
    )
    process = subprocess.run(
        [sys.executable, "-c", command, str(resources.runtime_resource("karaoke_job.py"))],
        env={**os.environ, "KARAOKE_RUNTIME_DIR": str(tmp_path)}, capture_output=True, text=True, check=True,
    )
    assert process.stdout.splitlines() == [
        str(tmp_path / "karaoke_job.json"), str(tmp_path / "karaoke_workspace"),
        str(tmp_path / "karaoke_render_job.zip"),
    ]
    assert list(tmp_path.iterdir()) == []


def test_runtime_report_never_starts_models(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    report = notebook.runtime_report()
    assert report["python_supported"]
    assert not any(report["modules"].values())
    assert Path(report["requirements"]).is_file()


def test_bundled_resources_have_sources():
    for name in ("karaoke_job.py", "karaoke_launch.py", "requirements.txt"):
        assert resources.runtime_resource(name).is_file()
    with pytest.raises(ValueError):
        resources.runtime_resource("../../other")


def test_notebook_interrupt_stops_child_process(monkeypatch, tmp_path):
    class InterruptedStream:
        def __iter__(self):
            raise KeyboardInterrupt

    class Process:
        pid = 12345
        stdout = InterruptedStream()
        stopped = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def poll(self):
            return None

        def terminate(self):
            self.stopped = True

        def wait(self, timeout=None):
            return -15

    process = Process()

    def launch(*args, **kwargs):
        assert kwargs["start_new_session"] == (os.name == "posix")
        return process

    if os.name == "posix":
        def stop_group(pid, signal):
            assert pid == process.pid
            assert signal == notebook.signal.SIGTERM
            process.stopped = True
        monkeypatch.setattr(notebook.os, "killpg", stop_group)
    monkeypatch.setattr(notebook.subprocess, "Popen", launch)
    with pytest.raises(KeyboardInterrupt):
        notebook._run_preparation(tmp_path / "config.json", {})
    assert process.stopped


def test_launcher_sets_runtime_before_child_starts(tmp_path, monkeypatch):
    from colab import karaoke_launch

    monkeypatch.setattr(karaoke_launch, "cuda_environment", lambda: os.environ.copy())
    config_path = tmp_path / "karaoke_job.json"
    archive_path = tmp_path / "source.zip"
    observed = tmp_path / "observed.txt"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("karaoke_pipeline.py", (
            "import os\nfrom pathlib import Path\n"
            f"Path({str(observed)!r}).write_text(os.environ['KARAOKE_RUNTIME_DIR'])\n"
        ))
    config_path.write_text(json.dumps({"source_bundle": str(archive_path)}))
    karaoke_launch.main(config_path)
    assert observed.read_text() == str(tmp_path)


def test_remote_pins_satisfy_application_requirements():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    application = {
        requirement.name.lower(): requirement
        for requirement in map(Requirement, project["project"]["dependencies"])
    }
    for line in resources.runtime_resource("requirements.txt").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        remote = Requirement(line)
        local = application.get(remote.name.lower())
        if local is None:
            continue
        for specifier in remote.specifier:
            if specifier.operator == "==" and "*" not in specifier.version:
                assert local.specifier.contains(specifier.version), f"Incompatible pin: {remote} versus {local}"
