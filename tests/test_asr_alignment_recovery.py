"""Independent phrase anchors reject catastrophic CTC drift and bound partial recovery."""

import copy
from pathlib import Path
from unittest.mock import Mock

import pytest

from colab import karaoke_job as job
from karaoke_app import lyric_references as refs


@pytest.fixture
def sample():
    desired = refs.plain_lines("alpha beta gamma\nmissing whole verse\ndelta epsilon zeta")
    speech = {
        "song": {"title": "Song", "artist": "Artist", "duration": 60},
        "transcription": {"language": "en"},
        "segments": [{"words": [
            {"text": word, "start": i + 1, "end": i + 1.5, "probability": .99}
            for i, word in enumerate("alpha beta gamma wrong asr text delta epsilon zeta".split())
        ]}],
    }
    validation = refs.compare_reference(desired, speech)
    good, _ = refs.apply_reference_text(job._transcript_to_lyrics(speech), desired)
    bad = copy.deepcopy(good)
    for line in bad["lines"]:
        for item in [line, *line["words"]]:
            item["start_ms"] += 20000
            item["end_ms"] += 20000
    return desired, speech, validation, good, bad


def test_multi_phrase_drift_rejected_without_changing_timestamps(sample):
    desired, _, validation, good, bad = sample
    before = copy.deepcopy(bad)
    assert refs.alignment_anchor_check(good, desired, validation)["status"] == "checked"
    check = refs.alignment_anchor_check(bad, desired, validation)
    assert check["status"] == "drift"
    assert len(check["severe_deviations"]) == 2
    assert bad == before


def test_one_questionable_anchor_does_not_overrule_acoustic_alignment(sample):
    desired, _, validation, _, bad = sample
    validation["lines"][2].pop("anchor")
    validation["lines"][2]["anchor_spans"] = []
    for line in bad["lines"]:
        for item in [line, *line["words"]]:
            item["start_ms"] -= 14000
            item["end_ms"] -= 14000
    assert refs.alignment_anchor_check(bad, desired, validation)["status"] == "insufficient_anchors"


def test_catastrophic_drift_of_one_verified_phrase_is_rejected(sample):
    desired, _, validation, _, bad = sample
    validation["lines"][2]["anchor_spans"] = []
    assert refs.alignment_anchor_check(bad, desired, validation)["status"] == "drift"


def test_sustained_word_end_is_not_evidence_of_phrase_onset_drift(sample):
    desired, _, validation, good, _ = sample
    good["lines"][-1]["words"][-1]["end_ms"] += 15000
    assert refs.alignment_anchor_check(good, desired, validation)["status"] == "checked"


def test_partial_windows_cover_missing_text_without_word_times(sample):
    desired, _, validation, _, _ = sample
    before = copy.deepcopy(desired)
    tokens = job._alignment_document_tokens(desired, character_alignment=False)
    sections = job._asr_recovery_sections(tokens, desired, validation, 60000)
    assert [[line["text"] for line, _ in section] for section in sections] == [
        ["alpha beta gamma", "missing whole verse"], ["delta epsilon zeta"],
    ]
    assert sections[0][-1][0]["end_ms"] == sections[1][0][0]["start_ms"] == 7000
    assert sections[-1][-1][0]["end_ms"] == 60000
    assert desired == before
    assert refs.anchored_document({"lines": desired}, validation) is None


def test_out_of_order_asr_cannot_define_recovery_windows(sample):
    desired, _, validation, _, _ = sample
    validation["lines"][2]["anchor"]["start_ms"] = 500
    with pytest.raises(ValueError, match="ordered"):
        job._asr_recovery_sections(job._alignment_document_tokens(desired, character_alignment=False),
                                   desired, validation, 60000)


def test_partial_phrase_survives_transcription_error(sample):
    _, speech, _, _, _ = sample
    desired = refs.plain_lines("wrong alpha beta gamma\nmissing whole verse\ndelta epsilon zeta")
    validation = refs.compare_reference(desired, speech)
    assert "anchor" not in validation["lines"][0]
    assert validation["lines"][0]["anchor_spans"] == [
        {"start_unit": 1, "end_unit": 4, "start_ms": 1000, "end_ms": 3500},
    ]


def test_acoustic_refinement_only_replaces_bounded_estimated_words(sample):
    desired, speech, _, _, _ = sample
    original, grouping = refs.apply_reference_text(job._transcript_to_lyrics(speech), desired)
    before = copy.deepcopy(original)
    candidate = copy.deepcopy(original)
    for word, (start, end) in zip(candidate["lines"][1]["words"],
                                  [(4100, 4400), (4500, 4800), (5800, 6200)], strict=True):
        word.update(start_ms=start, end_ms=end, confidence=.8)
    result, report = refs.refine_estimated_timings(original, grouping, [candidate])
    assert original == before
    assert result["lines"][0] == original["lines"][0]
    assert result["lines"][2] == original["lines"][2]
    assert result["lines"][1]["words"] == candidate["lines"][1]["words"]
    assert report["acoustic_refined_words"] == 3
    assert report["estimated_words"] == 0
    assert grouping["estimated_words"] == 3


@pytest.mark.parametrize("failure", ["drift", "wrong_text", "overlap", "collapsed"])
def test_unsafe_acoustic_refinement_keeps_fallback(sample, failure):
    desired, speech, _, _, _ = sample
    original, grouping = refs.apply_reference_text(job._transcript_to_lyrics(speech), desired)
    candidate = copy.deepcopy(original)
    words = candidate["lines"][1]["words"]
    if failure == "drift":
        words[-1]["end_ms"] = 20000
    elif failure == "wrong_text":
        words[0]["text"] = "other "
    elif failure == "overlap":
        words[0]["end_ms"] = words[1]["end_ms"]
    else:
        for index, word in enumerate(words):
            word.update(start_ms=4000 + index * 20, end_ms=4020 + index * 20)
    result, report = refs.refine_estimated_timings(original, grouping, [candidate])
    assert result == original and report == grouping


@pytest.mark.parametrize("recovery_succeeds", [True, False])
def test_preparation_retries_partial_anchors_and_discards_failed_candidates(sample, tmp_path, monkeypatch,
                                                                          recovery_succeeds):
    desired, speech, _, good, bad = sample
    text = tmp_path / "reference.txt"
    text.write_text("\n".join(line["text"] for line in desired))
    config = {"language": "en", "lyrics": {"text_path": str(text)}, "whisper_model": "large-v3"}
    monkeypatch.setattr(job, "_transcribe", Mock(return_value=speech))
    monkeypatch.setattr(job, "_lyric_presence_inspector", lambda *args: lambda *_: [{
        "source": "vocals", "status": "checked", "words": [
            {"text": word, "start": 4 + i * 0.5, "end": 4.4 + i * 0.5, "probability": 0.99}
            for i, word in enumerate("missing whole verse".split())
        ],
    }])
    monkeypatch.setattr(job, "_check_vocal_boundaries", Mock(return_value={"status": "checked"}))
    align = Mock(side_effect=lambda *args, **kwargs: (
        copy.deepcopy(good if recovery_succeeds and kwargs.get("recovery_only") else bad), []
    ))
    monkeypatch.setattr(job, "_align_known_lyrics", align)
    lyrics, provenance = job._prepare_lyrics(
        Path("unused.flac"), speech["song"], config, selected_record=None, artifacts_dir=tmp_path,
    )
    assert align.call_count == (2 if recovery_succeeds else 3)
    assert align.call_args_list[1].kwargs["recovery_only"]
    assert "anchor_validation" in align.call_args_list[1].kwargs
    if not recovery_succeeds:
        assert align.call_args.kwargs["anchor_transcript"] == speech
    assert provenance["strategy"] == ("asr_window_ctc" if recovery_succeeds else "reference_text_asr_timing")
    assert lyrics["lines"][0]["start_ms"] == 1000
