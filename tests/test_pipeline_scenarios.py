"""Offline route integration: real orchestration, controlled providers and model outputs."""

import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from colab import karaoke_job as job
from karaoke_app import lyric_references as refs


@pytest.mark.parametrize("scenario,expected_source,expected_strategy", [
    ("lrclib_plain", "lrclib", "test_ctc"),
    ("lrclib_synced", "lrclib", "test_ctc"),
    ("lrclib_missing_genius_available", "genius", "test_ctc"),
    ("lrclib_wrong_artist", "genius", "test_ctc"),
    ("all_missing", "whisper", "transcription"),
    ("genius_blocked", "whisper", "transcription"),
    ("genius_blocked_local_available", "genius", "test_ctc"),
    ("txt_overrides_providers", "txt", "test_ctc"),
    ("forced_whisper", "whisper", "transcription"),
    ("ctc_failure", "txt", "reference_text_asr_timing"),
    ("partial_txt", "txt", "test_ctc"),
])
def test_full_preparation_routes(tmp_path, monkeypatch, scenario, expected_source, expected_strategy):
    metadata = {"title": "Test Song", "artist": "Test Artist", "duration": 60, "uploader": "Test Artist"}
    config = {"language": "en", "lyrics": {}, "whisper_model": "large-v3"}
    text = "alpha beta\ngamma delta"
    speech = {"song": metadata, "transcription": {"language": "en"}, "segments": [{"words": [
        {"text": word, "start": 1 + i, "end": 1.5 + i, "probability": .95}
        for i, word in enumerate(text.split())
    ]}]}
    record = {"id": 7, "trackName": "Test Song", "artistName": "Test Artist", "duration": 60, "plainLyrics": text}
    if scenario == "lrclib_synced":
        record["syncedLyrics"] = "[00:01.00]alpha beta\n[00:03.00]gamma delta"
    if scenario == "lrclib_wrong_artist":
        record["artistName"] = "Unrelated Artist"
    available = scenario in {"lrclib_plain", "lrclib_synced", "lrclib_wrong_artist"}
    request = Mock(side_effect=lambda path: ([record] if available else []) if path.startswith("/search")
                   else record if available else None)
    genius = Mock(return_value={"source": "genius", "lines": refs.plain_lines(text), "original_text": text})
    if scenario in {"all_missing", "forced_whisper"}:
        genius.return_value = None
    elif scenario in {"genius_blocked", "genius_blocked_local_available"}:
        genius.side_effect = PermissionError("403")
    if scenario == "genius_blocked_local_available":
        path = tmp_path / "genius.json"
        path.write_text(json.dumps({
            "source": "genius", "url": "https://genius.com/Test-artist-test-song-lyrics",
            "metadata": {"title": "Test Song", "artist": "Test Artist"}, "original_text": text,
        }))
        config["lyrics"]["genius_reference_path"] = str(path)
    if scenario in {"txt_overrides_providers", "ctc_failure", "partial_txt"}:
        path = tmp_path / "reference.txt"
        path.write_text("alpha beta" if scenario == "partial_txt" else text)
        config["lyrics"]["text_path"] = str(path)
    if scenario == "forced_whisper":
        config["lyrics"]["disable_lrclib"] = True
    monkeypatch.setattr(job, "_lrclib_request", request)
    monkeypatch.setattr(job, "_load_references_module", lambda: refs)
    monkeypatch.setattr(refs, "genius_reference", genius)
    monkeypatch.setattr(job, "_transcribe", lambda *args: copy.deepcopy(speech))
    monkeypatch.setattr(job, "_check_vocal_boundaries", lambda *args: {"status": "checked"})

    def align(vocals, document, config, *, provenance, **kwargs):
        if scenario == "ctc_failure":
            raise RuntimeError("model failed")
        provenance["strategy"] = "test_ctc"
        return job._transcript_to_lyrics(copy.deepcopy(speech)), {}

    monkeypatch.setattr(job, "_align_known_lyrics", align)
    selected, reference = job._prepare_reference(metadata, config, None)
    lyrics, alignment = job._prepare_lyrics(
        Path("unused.wav"), metadata, config, selected_record=selected,
        resolved_reference=reference, artifacts_dir=tmp_path,
    )
    assert alignment["text_source"] == expected_source
    assert alignment["strategy"] == expected_strategy
    assert (tmp_path / "transcription.json").is_file()
    assert (tmp_path / "lyrics_validation.json").is_file()
    assert lyrics["lines"]
    if scenario in {"forced_whisper", "txt_overrides_providers"}:
        request.assert_not_called()
        genius.assert_not_called()
    if scenario == "partial_txt":
        assert alignment["needs_review"]
        assert len(lyrics["lines"]) == 1
    if scenario == "genius_blocked":
        assert "403" in reference[1]["attempts"][-1]["error"]
    if scenario == "genius_blocked_local_available":
        genius.assert_not_called()
        assert alignment["word_timing"] == "generated"
        assert reference[1]["acquisition"] == "local_before_alignment"
