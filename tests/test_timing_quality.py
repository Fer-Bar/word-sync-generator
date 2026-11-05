"""Local conflicts, uncertain coverage and bounded repairs must not move healthy lyrics."""

import copy
from pathlib import Path
from unittest.mock import Mock

import pytest

from colab import karaoke_job as job
from karaoke_app.lyric_references import normalized_units
from karaoke_app.timing_quality import assess_timing, recovery_windows, require_timing_review


@pytest.fixture
def sample():
    lines = []
    for index in range(10):
        words = [{"text": f"token{index}word{word} ", "start_ms": index * 5000 + word * 600,
                  "end_ms": index * 5000 + word * 600 + 500, "confidence": .9}
                 for word in range(4)]
        lines.append({"text": "".join(w["text"] for w in words).strip(), "words": words,
                      "start_ms": words[0]["start_ms"], "end_ms": words[-1]["end_ms"]})
    document = {"version": "1.0", "metadata": {"title": "Test", "duration_ms": 50000}, "lines": lines}
    reference = [{"text": line["text"], "start_ms": line["start_ms"], "end_ms": (i + 1) * 5000}
                 for i, line in enumerate(lines)]
    bad = copy.deepcopy(document)
    for index in [3, 4]:
        for item in [bad["lines"][index], *bad["lines"][index]["words"]]:
            item["start_ms"] += 3000
            item["end_ms"] += 3000
        for word in bad["lines"][index]["words"]:
            word["confidence"] = .1
    return document, bad, reference


def assess(document, reference, validation=None):
    return assess_timing(document, reference, validation or {"lines": []}, normalize=normalized_units)


def test_local_drift_is_detected_even_without_asr_in_that_region(sample):
    _, bad, reference = sample
    before = copy.deepcopy(bad)
    quality = assess(bad, reference)
    assert quality["status"] == "conflict"
    assert quality["reference_offset_ms"] == 0
    assert [row["line_index"] for row in quality["lines"] if row["reasons"]] == [3, 4]
    assert bad == before


def test_missing_evidence_is_partial_and_does_not_block_render(sample):
    good, _, reference = sample
    quality = assess(good, reference)
    assert quality["status"] == "partial" and not quality["regions"]
    require_timing_review(good, quality)


def test_consistent_reference_offset_is_not_a_local_timing_failure(sample):
    good, _, reference = sample
    for line in reference:
        line["start_ms"] += 12000
        line["end_ms"] += 12000
    quality = assess(good, reference)
    assert quality["reference_offset_ms"] == -12000
    assert not quality["regions"]


def test_wrong_reference_without_consistent_calibration_cannot_force_times(sample):
    good, _, reference = sample
    for index, line in enumerate(reference):
        line["start_ms"] += index * 3000
    quality = assess(good, reference)
    assert quality["reference_offset_ms"] is None
    assert not quality["regions"]


def test_low_confidence_sustained_note_and_fast_words_alone_are_not_conflicts(sample):
    good, _, reference = sample
    good["lines"][3]["words"][-1]["end_ms"] += 10000
    good["lines"][3]["end_ms"] += 10000
    for word in good["lines"][3]["words"]:
        word["confidence"] = .1
    for word in good["lines"][5]["words"]:
        word["end_ms"] = word["start_ms"] + 40
    assert not assess(good, reference)["regions"]


def test_word_interior_drift_is_checked_even_when_phrase_onset_matches(sample):
    good, _, reference = sample
    for word in good["lines"][3]["words"][1:]:
        word["start_ms"] += 2000
        word["end_ms"] += 2000
    validation = {"lines": [{"line_index": 3, "anchor_spans": [{
        "start_unit": 0, "end_unit": 4, "start_ms": 15000, "end_ms": 17300,
        "word_starts": [{"unit": i, "start_ms": 15000 + i * 600} for i in range(4)],
    }]}]}
    assert "independent_word_disagreement" in assess(good, reference, validation)["lines"][3]["reasons"]


def test_stretched_phrase_is_included_with_following_conflict(sample):
    _, bad, reference = sample
    bad["lines"][2]["end_ms"] = 17500
    bad["lines"][2]["words"][-1]["end_ms"] = 17500
    for word in bad["lines"][2]["words"]:
        word["confidence"] = .3
    assert "stretched_before_conflict" in assess(bad, reference)["lines"][2]["reasons"]


def test_lrc_adjacent_ends_still_produce_bounded_macro_sections():
    raw = job._parse_synced_lyrics("\n".join(f"[00:{i * 5:02d}.00]verse {i}" for i in range(12)))
    sections = job._group_lines_into_macro_sections([(line, []) for line in raw])
    assert [len(section) for section in sections] == [6, 6]
    assert [line for section in sections for line, _ in section] == raw


def test_recovery_windows_are_local_and_keep_context(sample):
    _, bad, reference = sample
    windows = recovery_windows(assess(bad, reference), duration_ms=50000)
    assert len(windows) == 1
    assert windows[0]["first_line"] == 2 and windows[0]["last_line"] == 5
    assert windows[0]["end_ms"] - windows[0]["start_ms"] <= 30000


def test_unchanged_and_edited_conflicted_lyrics_require_explicit_review(sample):
    _, bad, reference = sample
    quality = assess(bad, reference)
    with pytest.raises(ValueError, match="Timing conflicts remain"):
        require_timing_review(bad, quality)
    bad["lines"][3]["words"][0]["start_ms"] -= 1000
    with pytest.raises(ValueError, match="Lyrics changed"):
        require_timing_review(bad, quality)
    require_timing_review(bad, quality, reviewed=True)


def test_regional_repair_preserves_every_unflagged_line(sample, monkeypatch):
    good, bad, reference = sample
    original = copy.deepcopy(bad)
    monkeypatch.setattr(job, "_recover_region_transcript", lambda *args: None)
    monkeypatch.setattr(job, "_align_timing_window", lambda ref, cfg, ctx, win, quality, **kw:
                        copy.deepcopy(good["lines"][win["first_line"]:win["last_line"] + 1]))
    result, _, report = job._recover_local_timing(
        bad, {"lines": reference}, None, Path("unused.wav"), {"duration": 50}, {}, context=None,
    )
    assert report["attempts"][0]["accepted"]
    assert result["lines"][3]["start_ms"] == good["lines"][3]["start_ms"]
    for index in set(range(10)) - {3, 4}:
        assert result["lines"][index] == original["lines"][index]
    assert bad == original


def test_healthy_song_does_not_load_models_or_retry_asr(sample, monkeypatch):
    good, _, reference = sample
    transcribe, align = Mock(), Mock()
    monkeypatch.setattr(job, "_recover_region_transcript", transcribe)
    monkeypatch.setattr(job, "_align_timing_window", align)
    result, _, report = job._recover_local_timing(
        good, {"lines": reference}, None, Path("unused.wav"), {"duration": 50}, {}, context=None,
    )
    assert result == good and not report["attempts"]
    transcribe.assert_not_called()
    align.assert_not_called()


def test_regional_asr_keeps_absolute_times_and_untouched_outer_words(sample, monkeypatch):
    good, _, reference = sample
    def speech_words(index):
        return [{"text": word["text"].strip(), "start": word["start_ms"] / 1000,
                 "end": word["end_ms"] / 1000, "probability": .99}
                for word in good["lines"][index]["words"]]
    outer = speech_words(0) + speech_words(9)
    original = {"segments": [{"words": outer}], "song": {"title": "Test"}}
    local = [dict(word, start=word["start"] - 14.5, end=word["end"] - 14.5)
             for index in [3, 4] for word in speech_words(index)]
    transcribe = Mock(return_value={"segments": [{"words": local}]})
    monkeypatch.setattr(job, "_transcribe", transcribe)
    monkeypatch.setattr(job.subprocess, "run", Mock())
    result = job._recover_region_transcript(
        original, {"lines": reference},
        {"first_line": 3, "last_line": 4, "start_ms": 14500, "end_ms": 25500},
        Path("unused.wav"), None, {"duration": 50}, {},
    )
    observed = [{key: value for key, value in word.items() if key != "id"}
                for segment in result["segments"] for word in segment["words"]]
    assert observed == speech_words(0) + speech_words(3) + speech_words(4) + speech_words(9)
    assert original["segments"][0]["words"] == outer
    assert transcribe.call_args.kwargs["vad_filter"] is False


def test_render_rejects_conflicts_before_starting_colab(sample, tmp_path, monkeypatch):
    from karaoke_app import cli

    _, bad, reference = sample
    document = {
        "schema_version": 2, "title": "Test", "alignment": {"timing_quality": assess(bad, reference)},
        "media": {"lyrics": "lyrics.yaml", "vocals_audio": "vocals.wav",
                  "original_audio": "audio.wav", "instrumental_audio": "instrumental.wav"},
        "background": {"kind": "solid", "color": "#000000"},
        "video": {"width": 640, "height": 360, "fps": 24},
    }
    monkeypatch.setattr(cli, "_validate_installation", lambda: None)
    monkeypatch.setattr("karaoke_app.job_document.load_job_document", lambda _: document)
    monkeypatch.setattr("karaoke_app.job_document.resolve_job_asset", lambda *args: tmp_path / "lyrics.yaml")
    monkeypatch.setattr("karaoke_app.lyrics_file.load_lyrics_file", lambda *args, **kwargs: bad)
    remote = Mock()
    monkeypatch.setattr(cli, "_run", remote)
    with pytest.raises(ValueError, match="Timing conflicts remain"):
        cli.render_colab(cli.build_render_parser().parse_args([str(tmp_path)]))
    remote.assert_not_called()
