"""Acoustic word-tail regression tests independent of alignment models."""

import copy
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import yaml

from colab import karaoke_job as job


def line(start=1000, end=6000):
    return {"text": "held", "start_ms": start, "end_ms": end,
            "words": [{"text": "held", "start_ms": start, "end_ms": end, "agent": "v1"}]}


@pytest.mark.parametrize("gain", [1, 0.001])
def test_word_stops_before_instrumental_even_if_voice_resumes(gain):
    levels = np.full(350, 1e-7) * gain
    levels[50:125] = 0.2 * gain
    levels[280:] = 0.2 * gain
    lines = [line()]
    report = job._trim_quiet_word_tails(lines, levels)
    assert lines[0]["words"][0]["end_ms"] == 2600
    assert lines[0]["end_ms"] == 2600
    assert lines[0]["start_ms"] == 1000
    assert report["corrections"][0]["original_end_ms"] == 6000


@pytest.mark.parametrize("quiet_frames", [0, 10, 29])
def test_sustained_notes_and_brief_pauses_are_preserved(quiet_frames):
    levels = np.full(1600, 0.2)
    levels[100:100 + quiet_frames] = 0
    lines = [line(end=30000)]
    original = copy.deepcopy(lines)
    report = job._trim_quiet_word_tails(lines, levels)
    assert lines == original
    assert not report["corrections"]


def test_quiet_sustained_vowel_is_not_silence():
    levels = np.full(350, 0.01)
    levels[50:60] = 0.2
    lines = [line()]
    assert not job._trim_quiet_word_tails(lines, levels)["corrections"]


def test_leading_silence_is_not_a_word_end():
    levels = np.zeros(350)
    levels[120:] = 0.2
    lines = [line()]
    assert not job._trim_quiet_word_tails(lines, levels)["corrections"]


@pytest.mark.parametrize("levels", [np.zeros(350), np.ones(60)])
def test_missing_acoustic_evidence_requires_review_without_guessing(levels):
    lines = [line()]
    original = copy.deepcopy(lines)
    report = job._trim_quiet_word_tails(lines, levels)
    assert report["status"] == "needs_review"
    assert lines == original


def test_overlapping_background_word_preserves_line_end():
    lines = [line()]
    lines[0]["words"].append({"text": "oh", "start_ms": 5600, "end_ms": 6200, "isBackground": True})
    levels = np.zeros(350)
    levels[50:125] = 0.2
    levels[280:] = 0.2
    job._trim_quiet_word_tails(lines, levels)
    assert lines[0]["words"][0]["end_ms"] == 2600
    assert lines[0]["end_ms"] == 6200
    assert lines[0]["words"][1]["isBackground"]


def test_decoding_failure_is_reported():
    with patch.object(job.subprocess, "run", side_effect=OSError("missing decoder")):
        report = job._check_vocal_boundaries(Path("vocals.flac"), [line()])
    assert report["status"] == "unavailable"


def test_pcm_decoding_and_energy_frames():
    samples = np.zeros(7 * 16000, dtype="<f4")
    samples[16000:40000] = 0.2
    with patch.object(job.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, samples.tobytes())):
        lines = [line()]
        report = job._check_vocal_boundaries(Path("vocals.flac"), lines)
    assert report["corrections"][0]["end_ms"] == 2600


@pytest.mark.parametrize("engine", ["ctc", "whisper", "native"])
def test_pipeline_exports_corrected_times_and_diagnostics(tmp_path, engine):
    transcript = {
        "song": {"title": "Song", "duration": 7}, "transcription": {"language": "en"},
        "segments": [{"words": [{"text": "held", "start": 1, "end": 6, "probability": 0.99}]}],
    }
    levels = np.zeros(350)
    levels[50:125] = 0.2
    document = job._transcript_to_lyrics(transcript)
    record = {"plainLyrics": "held"} if engine == "ctc" else None
    if engine == "native":
        record = {"lyricsfile": yaml.safe_dump(document), "trackName": "Song", "artistName": "Artist", "duration": 7}
    with (
        patch.object(job, "_transcribe", return_value=transcript),
        patch.object(job, "_align_known_lyrics", return_value=(document, [])),
        patch.object(
            job, "_check_vocal_boundaries", side_effect=lambda _, lines: job._trim_quiet_word_tails(lines, levels),
        ) as check,
    ):
        lyrics, alignment = job._prepare_lyrics(
            Path("vocals.flac"), {"title": "Song", "artist": "Artist", "duration": 7},
            {"lyrics": {"disable_lrclib": engine == "whisper"}, "whisper_model": "large-v3", "language": "en"},
            selected_record=record, artifacts_dir=tmp_path,
        )
    check.assert_called_once()
    assert lyrics["lines"][0]["end_ms"] == 2600
    assert alignment["words"][0]["end"] == 2.6
    saved = json.loads((tmp_path / "lyrics_validation.json").read_text())
    assert saved["vocal_boundaries"] == alignment["vocal_boundaries"]


def test_partial_final_frame_does_not_hide_a_long_silent_tail():
    # Decoded audio is slightly shorter than the aligner's rounded final timestamp.
    samples = np.zeros(6 * 16000 - 112, dtype="<f4")
    samples[16000:40000] = 0.2
    with patch.object(job.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, samples.tobytes())):
        lines = [line(end=6000)]
        report = job._check_vocal_boundaries(Path("vocals.flac"), lines)
    assert report["status"] == "checked"
    assert lines[0]["words"][0]["end_ms"] == 2600


def test_partial_final_frame_does_not_trim_a_sustained_final_note():
    samples = np.full(6 * 16000 - 112, 0.2, dtype="<f4")
    with patch.object(job.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, samples.tobytes())):
        lines = [line(end=6000)]
        report = job._check_vocal_boundaries(Path("vocals.flac"), lines)
    assert report["status"] == "checked"
    assert not report["corrections"]
    assert lines[0]["words"][0]["end_ms"] == 6000
