"""Suggest a supported song language without replacing manual user choices."""

import argparse
import importlib.util
import json
import logging
import subprocess
import sys
from pathlib import Path

import numpy as np

from karaoke_app.notebook_inputs import validate_inputs
from karaoke_app.resources import runtime_resource

LOGGER = logging.getLogger(__name__)
LANGUAGE_OPTIONS = (
    ("Español", "es"),
    ("English", "en"),
    ("Português", "pt"),
    ("Français", "fr"),
    ("Italiano", "it"),
    ("Deutsch", "de"),
)
SUPPORTED_LANGUAGES = frozenset(code for _, code in LANGUAGE_OPTIONS)
WHISPER_MODELS = frozenset({"small", "medium", "large-v3"})
SAMPLE_RATE = 16000


def _runtime_module(name):
    spec = importlib.util.spec_from_file_location(f"language_{name}", runtime_resource(name))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load runtime module: {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cuda_environment() -> dict[str, str]:
    """Use the preparation launcher's CUDA paths before importing inference libraries."""
    return _runtime_module("karaoke_launch.py").cuda_environment()


def _load_model(model, cache):
    return _runtime_module("karaoke_job.py")._load_whisper_model(model, cache)


def _decode_excerpt(source, start, length):
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            str(start),
            "-i",
            str(source),
            "-t",
            str(length),
            "-vn",
            "-f",
            "f32le",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return np.frombuffer(result.stdout, dtype="<f4")


def _voiced_audio(audio):
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    # Speech VAD is only a conservative filter: singing it misses requires manual selection.
    spans = get_speech_timestamps(audio, VadOptions(threshold=0.25, min_silence_duration_ms=500))
    return np.concatenate([audio[span["start"] : span["end"]] for span in spans]) if spans else audio[:0]


def _manual(reason, samples=None):
    return {
        "status": "manual_required",
        "language": None,
        "probability": None,
        "reason": reason,
        "samples": samples or [],
    }


def detect_audio_language(source: Path, *, whisper_model: str, whisper_cache: Path) -> dict:
    """Suggest a language only when independent voiced excerpts confidently agree."""
    if whisper_model not in WHISPER_MODELS:
        raise ValueError("Choose small, medium, or large-v3 before starting the notebook.")
    selection = validate_inputs([Path(source)])
    source = Path(selection["source"])
    duration = selection["media"]["duration_seconds"]
    # Nonoverlapping excerpts avoid counting the same voice twice in short songs.
    length = min(30.0, duration / 3)
    starts = (0.0, (duration - length) / 2, duration - length)
    samples = []
    model = None
    try:
        for start in starts:
            audio = _decode_excerpt(source, start, length)
            if not audio.size or not np.isfinite(audio).all() or not np.any(audio):
                continue
            voiced = _voiced_audio(audio)
            if voiced.size < SAMPLE_RATE:
                continue
            if model is None:
                model = _load_model(whisper_model, Path(whisper_cache).expanduser().resolve())
            language, probability, _ = model.detect_language(audio=voiced)
            probability = float(probability)
            if not np.isfinite(probability) or not 0 <= probability <= 1:
                return _manual("detection_unavailable", samples)
            samples.append({"start_seconds": start, "language": language, "probability": probability})
    except (OSError, RuntimeError, ValueError, ImportError, subprocess.SubprocessError) as error:
        LOGGER.warning("Language detection unavailable; select manually: %s", error)
        return _manual("detection_unavailable", samples)
    if len(samples) < 2:
        return _manual("insufficient_voice", samples)
    confident = [sample for sample in samples if sample["probability"] >= 0.8]
    if len({sample["language"] for sample in confident}) > 1:
        return _manual("conflicting_languages", samples)
    if len(confident) < 2:
        return _manual("low_confidence", samples)
    language = confident[0]["language"]
    if language not in SUPPORTED_LANGUAGES:
        return _manual("unsupported_language", samples)
    return {
        "status": "detected",
        "language": language,
        "probability": min(sample["probability"] for sample in confident),
        "samples": samples,
    }


def launch_detection(request: Path, result: Path) -> dict:
    """Start inference with CUDA library paths, preserving the caller's process group."""
    try:
        environment = cuda_environment()
    except (ImportError, RuntimeError) as error:
        LOGGER.warning("Language detection unavailable; select manually: %s", error)
        return _manual("detection_unavailable")
    environment["KARAOKE_STREAM_OUTPUT"] = "1"
    subprocess.run(
        [
            sys.executable,
            "-u",
            "-m",
            "karaoke_app.notebook_language",
            "--request",
            str(request),
            "--result",
            str(result),
        ],
        env=environment,
        check=True,
    )
    return json.loads(result.read_text(encoding="utf-8"))


def main() -> None:
    """Run the isolated language worker without creating a preparation project."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = detect_audio_language(
        Path(request["source"]),
        whisper_model=request["whisper_model"],
        whisper_cache=Path(request["whisper_cache"]),
    )
    args.result.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
