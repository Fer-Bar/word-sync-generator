"""Notebook inputs cross the real runtime boundary; only GPU inference is replaced."""

import importlib.util
import json
import logging
import os
import wave

import pytest

from karaoke_app import notebook
from karaoke_app.resources import runtime_resource


def load_runtime(name):
    spec = importlib.util.spec_from_file_location(f"notebook_{name}", runtime_resource(name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("reference", [False, True])
def test_notebook_local_inputs_reach_real_pipeline_gpu_boundary(tmp_path, monkeypatch, caplog, reference):
    inputs = tmp_path / "content"
    inputs.mkdir()
    source = inputs / "song.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * 4000)
    original = source.read_bytes()
    source.chmod(0o444)
    lyrics = inputs / "lyrics.txt"
    lyrics.write_text("A local reference line\n", encoding="utf-8")
    lyrics.chmod(0o444)
    runtime = tmp_path / "kaggle" / "working" / "run"
    runtime.mkdir(parents=True)
    config = notebook.preparation_config(
        source, runtime, title="Synthetic fixture", artist="Tests", use_lrclib=reference,
        lyrics_text=lyrics if reference else None,
    )
    # A transfer bundle changes /content paths into uploaded members in the CLI pipeline.
    # Notebook files are already local and must never enter that protocol.
    assert "source_bundle" not in config
    (runtime / "karaoke_job.json").write_text(json.dumps(config))
    monkeypatch.setenv("KARAOKE_RUNTIME_DIR", str(runtime))
    pipeline = load_runtime("karaoke_job.py")
    reached = []

    class GpuBoundaryReached(Exception):
        pass

    def stop_at_gpu(mixture, model):
        assert mixture.is_file()
        assert pipeline._probe_duration(mixture) == pytest.approx(0.25, abs=0.01)
        assert pipeline._load_lyrics_module().__name__ == "karaoke_app.lyrics_file"
        assert pipeline._load_references_module().__name__ == "karaoke_app.lyric_references"
        reached.append(mixture)
        raise GpuBoundaryReached

    monkeypatch.setattr(pipeline, "_separate_vocals", stop_at_gpu)
    logger = logging.getLogger()
    handlers, level = list(logger.handlers), logger.level
    try:
        with pytest.raises(GpuBoundaryReached):
            pipeline.main()
    finally:
        for handler in set(logger.handlers) - set(handlers):
            logger.removeHandler(handler)
            handler.close()
        logger.setLevel(level)
    assert len(reached) == 1
    if reference:
        assert any("Lyrics found: TXT" in message for message in caplog.messages)
    assert source.read_bytes() == original
    assert lyrics.read_text() == "A local reference line\n"
    assert not (runtime / "source.zip").exists()
    assert not (runtime / "karaoke_pipeline.py").exists()
    assert config["lyrics"]["text_path"] == (str(lyrics) if reference else None)


def test_launcher_without_bundle_starts_real_pipeline(tmp_path, monkeypatch):
    karaoke_launch = load_runtime("karaoke_launch.py")

    # CUDA package discovery is an environment boundary; subprocess and pipeline are real.
    monkeypatch.setattr(karaoke_launch, "cuda_environment", lambda: os.environ.copy())
    config = tmp_path / "karaoke_job.json"
    config.write_text(json.dumps({"operation": "render", "archive_path": str(tmp_path / "result.zip")}))
    with pytest.raises(RuntimeError, match="Process exited with code"):
        karaoke_launch.main(config)
    status = json.loads((tmp_path / "karaoke_status.json").read_text())
    assert status["status"] == "failed"
    assert "Missing uploaded render job" in status["error"]
    assert not (tmp_path / "karaoke_pipeline.py").exists()
