"""Language suggestions are conservative and never modify the source audio."""

import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from karaoke_app import notebook_runner


@pytest.fixture
def detector(tmp_path, monkeypatch):
    from karaoke_app import notebook_language

    source = tmp_path / "song.wav"
    source.write_bytes(b"unchanged source")
    monkeypatch.setattr(
        notebook_language,
        "validate_inputs",
        lambda paths: {
            "source": str(source),
            "media": {"duration_seconds": 240},
        },
    )
    monkeypatch.setattr(notebook_language, "_decode_excerpt", lambda *args: np.ones(16000, dtype=np.float32))
    monkeypatch.setattr(notebook_language, "_voiced_audio", lambda audio: audio)
    calls = []
    predictions = [("es", 0.95, [])] * 3

    def load(model, cache):
        calls.append((model, cache))
        return SimpleNamespace(detect_language=lambda **kwargs: predictions.pop(0))

    monkeypatch.setattr(notebook_language, "_load_model", load)
    return notebook_language, source, calls, predictions


def test_selected_model_detects_language_across_excerpts_without_changing_source(detector, tmp_path):
    module, source, calls, _ = detector
    cache = tmp_path / "models"
    result = module.detect_audio_language(source, whisper_model="large-v3", whisper_cache=cache)
    assert result["status"] == "detected"
    assert result["language"] == "es"
    assert result["probability"] == pytest.approx(0.95)
    assert len(result["samples"]) == 3
    assert calls == [("large-v3", cache)]
    assert source.read_bytes() == b"unchanged source"


@pytest.mark.parametrize(
    ("predictions", "reason"),
    [
        ([("es", 0.3, [])] * 3, "low_confidence"),
        ([("es", 0.99, []), ("en", 0.99, []), ("es", 0.99, [])], "conflicting_languages"),
        ([("ja", 0.99, [])] * 3, "unsupported_language"),
    ],
)
def test_uncertain_or_unsupported_detection_requires_manual_selection(detector, tmp_path, predictions, reason):
    module, source, _, responses = detector
    responses[:] = predictions
    result = module.detect_audio_language(source, whisper_model="medium", whisper_cache=tmp_path / "models")
    assert result["status"] == "manual_required"
    assert result["language"] is None
    assert result["reason"] == reason
    assert source.read_bytes() == b"unchanged source"


def test_instrumental_intro_does_not_prevent_agreeing_later_detection(detector, tmp_path, monkeypatch):
    module, source, calls, _ = detector
    excerpts = iter([np.zeros(16000, dtype=np.float32), np.ones(16000), np.ones(16000)])
    monkeypatch.setattr(module, "_decode_excerpt", lambda *args: next(excerpts))
    monkeypatch.setattr(module, "_voiced_audio", lambda audio: audio if audio.any() else audio[:0])
    result = module.detect_audio_language(source, whisper_model="small", whisper_cache=tmp_path / "models")
    assert result["language"] == "es"
    assert len(result["samples"]) == 2
    assert calls[0][0] == "small"


@pytest.mark.parametrize("kind", ["silence", "nonfinite", "one-window"])
def test_insufficient_voice_never_becomes_a_detected_language(detector, tmp_path, monkeypatch, kind):
    module, source, calls, _ = detector
    if kind == "nonfinite":
        monkeypatch.setattr(module, "_decode_excerpt", lambda *args: np.full(16000, np.nan))
    elif kind == "silence":
        monkeypatch.setattr(module, "_voiced_audio", lambda audio: audio[:0])
    else:
        excerpts = iter([np.ones(16000), np.zeros(16000), np.zeros(16000)])
        monkeypatch.setattr(module, "_decode_excerpt", lambda *args: next(excerpts))
    result = module.detect_audio_language(source, whisper_model="large-v3", whisper_cache=tmp_path / "models")
    assert result["language"] is None
    assert result["status"] == "manual_required"
    if kind != "one-window":
        assert calls == []


def test_model_failure_leaves_manual_selection_available(detector, tmp_path, monkeypatch):
    module, source, _, _ = detector

    def fail(*args):
        raise RuntimeError("model download unavailable")

    monkeypatch.setattr(module, "_load_model", fail)
    result = module.detect_audio_language(source, whisper_model="large-v3", whisper_cache=tmp_path / "models")
    assert result["status"] == "manual_required"
    assert result["language"] is None
    assert result["reason"] == "detection_unavailable"
    assert source.read_bytes() == b"unchanged source"


def test_detection_adapter_starts_worker_with_cuda_environment(tmp_path, monkeypatch):
    from karaoke_app import notebook_language

    request, result = tmp_path / "request.json", tmp_path / "result.json"
    request.write_text(json.dumps({"source": "song.wav", "whisper_model": "large-v3", "whisper_cache": "models"}))
    monkeypatch.setattr(sys, "argv", ["runner", "detect-language", "--request", str(request), "--result", str(result)])
    monkeypatch.setattr(notebook_language, "cuda_environment", lambda: {"LD_LIBRARY_PATH": "cuda-libraries"})

    def run(command, **kwargs):
        assert command[:4] == [sys.executable, "-u", "-m", "karaoke_app.notebook_language"]
        assert kwargs["env"]["LD_LIBRARY_PATH"] == "cuda-libraries"
        assert kwargs["check"] is True
        result.write_text('{"language":"es","status":"detected"}')

    monkeypatch.setattr(notebook_language.subprocess, "run", run)
    notebook_runner.main()
    assert json.loads(result.read_text())["language"] == "es"


def test_runtime_model_loader_uses_persistent_cache_and_preserves_legacy_default(tmp_path, monkeypatch):
    from colab import karaoke_job

    calls = []
    monkeypatch.delenv("KARAOKE_WHISPER_CACHE", raising=False)
    monkeypatch.delenv("KARAOKE_STREAM_OUTPUT", raising=False)
    monkeypatch.setattr(karaoke_job, "WORK_DIR", tmp_path / "scratch")
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)))
    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(
            WhisperModel=lambda model, **kwargs: calls.append((model, kwargs)),
        ),
    )
    karaoke_job._load_whisper_model("medium")
    monkeypatch.setenv("KARAOKE_WHISPER_CACHE", str(tmp_path / "persistent"))
    karaoke_job._load_whisper_model("medium")
    assert calls == [
        ("medium", {"device": "cpu", "compute_type": "int8", "download_root": str(path)})
        for path in (tmp_path / "scratch" / "models", tmp_path / "persistent")
    ]


def test_streamed_model_download_uses_same_cache_as_loader(tmp_path, monkeypatch):
    from colab import karaoke_job

    cache = tmp_path / "models"
    monkeypatch.setenv("KARAOKE_STREAM_OUTPUT", "1")
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True)))

    def snapshot(**kwargs):
        assert kwargs["repo_id"] == "Systran/faster-whisper-large-v3"
        assert kwargs["cache_dir"] == str(cache)
        return str(cache / "snapshot")

    def model(name, **kwargs):
        assert name == str(cache / "snapshot")
        assert kwargs == {"device": "cuda", "compute_type": "float16", "download_root": str(cache)}
        return "loaded"

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot))
    monkeypatch.setitem(sys.modules, "tqdm", SimpleNamespace(tqdm=object))
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=model))
    assert karaoke_job._load_whisper_model("large-v3", cache) == "loaded"


@pytest.mark.parametrize("language", ["fr", "auto"])
def test_transcription_preserves_existing_language_words_and_options(tmp_path, monkeypatch, language):
    from colab import karaoke_job

    monkeypatch.delenv("KARAOKE_STREAM_OUTPUT", raising=False)
    source = tmp_path / "vocals.flac"

    def transcribe(path, **kwargs):
        assert path == str(source)
        assert kwargs == {
            "language": None if language == "auto" else language,
            "beam_size": 5,
            "word_timestamps": True,
            "vad_filter": True,
            "vad_parameters": {"threshold": 0.25, "min_silence_duration_ms": 500, "speech_pad_ms": 250},
            "condition_on_previous_text": False,
        }
        return (
            [SimpleNamespace(words=[SimpleNamespace(word=" Bonjour", start=1, end=2, probability=0.9)])],
            SimpleNamespace(language="fr", language_probability=0.99),
        )

    monkeypatch.setattr(karaoke_job, "_load_whisper_model", lambda model: SimpleNamespace(transcribe=transcribe))
    result = karaoke_job._transcribe(
        source,
        {"title": "Song", "uploader": None, "duration": 120},
        {"whisper_model": "medium", "language": language},
    )
    assert result["transcription"] == {
        "engine": "faster-whisper",
        "model": "medium",
        "language": "fr",
        "language_probability": 0.99,
    }
    assert result["segments"][0]["words"] == [
        {"id": "s0-w0", "start": 1.0, "end": 2.0, "text": "Bonjour", "probability": 0.9},
    ]
