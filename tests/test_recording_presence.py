"""Recording-specific omissions must not be forced back into the rendered lyrics."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from colab import karaoke_job as job
from karaoke_app import lyric_references as refs
from karaoke_app.lyric_repair import repair_prepared_lyrics


def words(text, start=4, probability=0.95):
    return [{"text": token, "start": start + i * 0.3, "end": start + i * 0.3 + 0.25,
             "probability": probability} for i, token in enumerate(text.split())]


def transcript():
    return {"song": {"title": "Song", "duration": 20}, "transcription": {"language": "en"},
            "segments": [{"words": words("opening verse here", 1) + words("closing verse now", 12)}]}


def observation(text="", source="vocals", probability=0.95):
    return {"source": source, "status": "checked", "words": words(text, probability=probability),
            "active_ratio": 0.9 if text else 0.0}


@pytest.mark.parametrize("position", [0, 1, 2])
def test_missing_intro_middle_and_outro_are_removed_without_mutating_reference(position):
    lines = refs.plain_lines("opening verse here\nclosing verse now")
    lines.insert(position, {"text": "absent whole stanza", "start_ms": 99999})
    original = copy.deepcopy(lines)
    probe = Mock(return_value=[observation(), observation(source="original_audio")])
    selected, report = refs.resolve_recording_reference(lines, transcript(), 20000, inspect_window=probe)
    assert [line["text"] for line in selected] == ["opening verse here", "closing verse now"]
    assert report["decisions"][0]["reason"] == "no_vocal_evidence"
    assert report["original_lines"] == lines == original
    assert report["omitted_lines"] == 1
    lo, hi = probe.call_args.args
    assert 0 <= lo < hi <= 20000  # Provider timestamps cannot determine the probe window.


def test_original_audio_recovers_a_real_phrase_missed_in_separated_vocals():
    lines = refs.plain_lines("opening verse here\nquiet genuine singing\nclosing verse now")
    probe = Mock(return_value=[observation(), observation("quiet genuine singing", "original_audio")])
    selected, report = refs.resolve_recording_reference(lines, transcript(), 20000, inspect_window=probe)
    assert selected == lines
    assert report["decisions"][0]["reason"] == "recognized_on_retry"
    assert report["windows"][0]["observations"][1]["words"]


def test_small_recognition_errors_do_not_erase_a_sung_phrase():
    lines = refs.plain_lines("opening verse here\nMientras ella se pasa en su BM al lado mío\nclosing verse now")
    selected, report = refs.resolve_recording_reference(
        lines, transcript(), 20000,
        inspect_window=lambda *_: [observation("Mientras ellos se pasan su bebé a los niños", "original_audio")])
    assert selected == lines
    assert report["decisions"][0]["action"] == "keep"


@pytest.mark.parametrize("sources,kept", [(["vocals", "original_audio"], True), (["vocals", "vocals"], False)])
def test_partial_evidence_requires_two_distinct_audio_views(sources, kept):
    lines = refs.plain_lines("opening verse here\none two three four five six seven eight nine ten\nclosing verse now")
    selected, report = refs.resolve_recording_reference(
        lines, transcript(), 20000,
        inspect_window=lambda *_: [observation("one two three four", source) for source in sources])
    assert (len(selected) == 3) is kept
    if kept:
        assert report["decisions"][0]["reason"] == "corroborated_partial_phrase"


def test_uncertain_vocals_are_omitted_without_claiming_proven_silence():
    lines = refs.plain_lines("opening verse here\nabsent whole stanza\nclosing verse now")
    selected, report = refs.resolve_recording_reference(
        lines, transcript(), 20000, inspect_window=lambda *_: [observation("different recorded phrase")])
    assert len(selected) == 2
    assert report["decisions"][0]["reason"] == "unconfirmed"


def test_low_confidence_retry_cannot_confirm_expected_lyrics():
    lines = refs.plain_lines("opening verse here\nabsent whole stanza\nclosing verse now")
    selected, _ = refs.resolve_recording_reference(
        lines, transcript(), 20000,
        inspect_window=lambda *_: [observation("absent whole stanza", probability=0.1)])
    assert len(selected) == 2


def test_repeated_chorus_elsewhere_cannot_confirm_an_omitted_occurrence():
    lines = refs.plain_lines("opening verse here\nrepeat this chorus\nclosing verse now\nrepeat this chorus")
    speech = transcript()
    speech["segments"][0]["words"] += words("repeat this chorus", 16)
    probe = Mock(return_value=[{**observation(), "words": words("repeat this chorus", 16)}])
    selected, report = refs.resolve_recording_reference(lines, speech, 20000, inspect_window=probe)
    assert [line["text"] for line in selected] == [
        "opening verse here", "closing verse now", "repeat this chorus"]
    assert report["decisions"][0]["line_index"] == 1


def test_short_interjections_and_supported_lyrics_need_no_retry():
    lines = refs.plain_lines("opening verse here\nhey\nclosing verse now")
    probe = Mock(side_effect=AssertionError("unnecessary retry"))
    assert refs.resolve_recording_reference(lines, transcript(), 20000, inspect_window=probe)[0] == lines


def test_retry_cannot_reuse_one_chorus_to_confirm_two_occurrences_in_the_same_window():
    lines = refs.plain_lines("opening verse here\nrepeat this chorus\nrepeat this chorus")
    speech = transcript()
    speech["segments"][0]["words"] = words("opening verse here", 1) + words("repeat this chorus", 5)
    selected, report = refs.resolve_recording_reference(
        lines, speech, 20000, inspect_window=lambda *_: [observation("repeat this chorus")])
    assert len(selected) == 2
    assert report["omitted_lines"] == 1


def test_failed_verification_is_not_evidence_of_absence():
    lines = refs.plain_lines("opening verse here\nabsent whole stanza\nclosing verse now")
    with pytest.raises(RuntimeError, match="verification unavailable"):
        refs.resolve_recording_reference(
            lines, transcript(), 20000, inspect_window=lambda *_: [{"source": "vocals", "status": "failed"}])


def test_removed_lines_cannot_leave_unbalanced_background_roles():
    lines = refs.plain_lines("opening verse here (\nabsent whole stanza\nclosing verse now)")
    selected, _ = refs.resolve_recording_reference(
        lines, transcript(), 20000, inspect_window=lambda *_: [observation()])
    roles = refs.reference_vocal_tokens(selected)
    assert any(token["isBackground"] for token in roles[-1])


@pytest.mark.parametrize("ctc_succeeds", [True, False])
def test_preparation_and_local_repair_cannot_restore_omitted_stanzas(tmp_path, monkeypatch, ctc_succeeds):
    speech = transcript()
    reference = "opening verse here\nabsent whole stanza\nclosing verse now"
    reference_path = tmp_path / "input.txt"
    reference_path.write_text(reference)
    monkeypatch.setattr(job, "_transcribe", Mock(return_value=speech))
    monkeypatch.setattr(job, "_lyric_presence_inspector", lambda *args: lambda *_: [observation()])
    monkeypatch.setattr(job, "_check_vocal_boundaries", lambda *args: {"status": "checked"})

    def align(_, document, *args, **kwargs):
        assert "absent whole stanza" not in [line["text"] for line in document["lines"]]
        if not ctc_succeeds:
            raise RuntimeError("test CTC failure")
        return job._transcript_to_lyrics(speech), []

    monkeypatch.setattr(job, "_align_known_lyrics", align)
    lyrics, alignment = job._prepare_lyrics(
        Path("test.flac"), speech["song"],
        {"language": "en", "lyrics": {"text_path": str(reference_path)}, "whisper_model": "large-v3"},
        selected_record=None, artifacts_dir=tmp_path)
    assert "absent" not in " ".join(line["text"] for line in lyrics["lines"])
    assert alignment["recording_presence"]["omitted_lines"] == 1
    evidence = json.loads((tmp_path / "lyrics_reference.json").read_text())
    assert evidence["recording_presence"]["original_lines"][1]["text"] == "absent whole stanza"
    (tmp_path / "alignment.json").write_text(json.dumps(alignment))
    (tmp_path / ".karaoke").mkdir()
    (tmp_path / ".karaoke/project.json").write_text(json.dumps({"preparation": {}}))
    assert repair_prepared_lyrics(tmp_path, Path(job.__file__))["reason"] == "recording_reference_preserved"


def test_local_retry_is_bounded_cached_and_does_not_prompt_with_reference(monkeypatch):
    samples = np.ones(40 * 16000, dtype="<f4") * 0.1
    decode = Mock(return_value=SimpleNamespace(stdout=samples.tobytes()))
    model = Mock()
    model.transcribe.return_value = ([SimpleNamespace(words=[
        SimpleNamespace(word="hello", start=1, end=1.3, probability=0.9)])], None)
    load = Mock(return_value=model)
    monkeypatch.setattr(job.subprocess, "run", decode)
    monkeypatch.setattr(job, "_load_whisper_model", load)
    inspect = job._lyric_presence_inspector(Path("vocals"), Path("original"),
                                          {"language": "en", "whisper_model": "large-v3"})
    result = inspect(0, 35000)
    assert inspect(0, 35000) is result
    assert model.transcribe.call_count == 6
    assert decode.call_count == 2
    load.assert_called_once()
    assert [word["start"] for word in result[0]["words"]] == [1, 15, 29]
    for call in model.transcribe.call_args_list:
        assert len(call.args[0]) <= 16 * 16000
        assert "initial_prompt" not in call.kwargs
        assert call.kwargs["vad_filter"] is False


def test_decoding_failure_does_not_become_silence(monkeypatch):
    monkeypatch.setattr(job.subprocess, "run", Mock(side_effect=OSError("decoder unavailable")))
    inspect = job._lyric_presence_inspector(Path("vocals"), None, {"language": "en", "whisper_model": "large-v3"})
    with pytest.raises(OSError, match="decoder unavailable"):
        inspect(0, 20000)


def test_asr_failure_cannot_bypass_presence_verification(tmp_path, monkeypatch):
    text = tmp_path / "reference.txt"
    text.write_text("possibly absent lyrics")
    monkeypatch.setattr(job, "_transcribe", Mock(side_effect=RuntimeError("ASR unavailable")))
    align = Mock()
    monkeypatch.setattr(job, "_align_known_lyrics", align)
    with pytest.raises(RuntimeError, match="cannot verify"):
        job._prepare_lyrics(Path("vocals"), {"title": "Song", "duration": 20},
                            {"language": "en", "lyrics": {"text_path": str(text)}, "whisper_model": "large-v3"},
                            selected_record=None, artifacts_dir=tmp_path)
    align.assert_not_called()
    report = json.loads((tmp_path / "lyrics_validation.json").read_text())
    assert report["status"] == "presence_verification_unavailable"


def test_fully_recognized_native_reference_keeps_word_annotations():
    speech = transcript()
    document = job._transcript_to_lyrics(speech)
    document["lines"][0]["words"][0]["agent"] = "guest"
    evidence = {"structure_lines": refs.plain_lines("opening verse here\nclosing verse now")}
    original = copy.deepcopy(document)
    adapted, report = job._adapt_recording_reference(
        document, evidence, speech, speech["song"], Mock(side_effect=AssertionError("unnecessary retry")))
    assert adapted == original
    assert report["recording_presence"]["omitted_lines"] == 0
