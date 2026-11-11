"""Preserve conservative language suggestions and shared model-cache behavior."""

import hashlib
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from karaoke_app import notebook_language as lang


@pytest.mark.parametrize("duration", [2.9, 90, 241])
@pytest.mark.parametrize(
    "case,expected",
    [
        ("agreement", "detected"),
        ("conflict", "conflicting_languages"),
        ("unsupported", "unsupported_language"),
        ("nan", "detection_unavailable"),
        ("negative", "detection_unavailable"),
        ("above-one", "detection_unavailable"),
        ("download", "detection_unavailable"),
        ("empty", "insufficient_voice"),
    ],
)
def test_detection_edges(tmp_path, monkeypatch, duration, case, expected):
    source = tmp_path / "song.wav"
    source.write_bytes(b"unchanged audio input")
    before = hashlib.sha256(source.read_bytes()).digest()
    monkeypatch.setattr(
        lang, "validate_inputs", lambda paths: {"source": str(source), "media": {"duration_seconds": duration}}
    )
    windows = []

    def decode(path, start, length):
        windows.append((start, length))
        return np.ones(round(length * 16000), dtype=np.float32)

    monkeypatch.setattr(lang, "_decode_excerpt", decode)
    monkeypatch.setattr(lang, "_voiced_audio", lambda audio: audio[:0] if case == "empty" else audio)
    predictions = iter(
        {
            "conflict": [("fr", 0.95, []), ("en", 0.95, []), ("fr", 0.95, [])],
            "unsupported": [("ja", 0.99, [])] * 3,
            "nan": [("fr", float("nan"), [])] * 3,
            "negative": [("fr", -0.1, [])] * 3,
            "above-one": [("fr", 1.1, [])] * 3,
        }.get(case, [("fr", 0.8, [])] * 3)
    )
    loads = []

    def load(model, cache):
        loads.append((model, cache))
        if case == "download":
            raise OSError("download unavailable")
        return SimpleNamespace(detect_language=lambda **kwargs: next(predictions))

    monkeypatch.setattr(lang, "_load_model", load)
    cache = tmp_path / "weights"
    result = lang.detect_audio_language(source, whisper_model="large-v3", whisper_cache=cache)
    short = duration < 3
    assert result.get("reason", result["status"]) == ("insufficient_voice" if short else expected)
    assert result["language"] == ("fr" if not short and expected == "detected" else None)
    assert loads == ([] if short or case == "empty" else [("large-v3", cache)])
    assert all(0 <= start and 0 < length <= 30 and start + length <= duration for start, length in windows)
    assert sum(length for _, length in windows) <= 90
    assert all(a + size <= b + 1e-8 for (a, size), (b, _) in zip(windows, windows[1:], strict=False))
    assert hashlib.sha256(source.read_bytes()).digest() == before


@pytest.mark.parametrize("model", ["small", "medium", "large-v3"])
@pytest.mark.parametrize("streamed", [False, True])
def test_shared_cache_is_used_on_both_loading_paths(tmp_path, monkeypatch, model, streamed):
    from colab import karaoke_job

    cache = tmp_path / "persistent-weights"
    snapshots, loads = [], []
    monkeypatch.setenv("KARAOKE_WHISPER_CACHE", str(cache))
    monkeypatch.setenv("KARAOKE_STREAM_OUTPUT", "1" if streamed else "0")
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True)))

    def snapshot(**kwargs):
        snapshots.append((kwargs["repo_id"], kwargs["cache_dir"]))
        return str(cache / "snapshot")

    def load(name, **kwargs):
        loads.append((name, kwargs))
        return "loaded"

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot))
    monkeypatch.setitem(sys.modules, "tqdm", SimpleNamespace(tqdm=object))
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=load))
    assert lang._load_model(model, cache) == "loaded"
    assert karaoke_job._load_whisper_model(model) == "loaded"
    assert snapshots == ([(f"Systran/faster-whisper-{model}", str(cache))] * 2 if streamed else [])
    assert (
        loads
        == [
            (
                str(cache / "snapshot") if streamed else model,
                {"device": "cuda", "compute_type": "float16", "download_root": str(cache)},
            )
        ]
        * 2
    )
