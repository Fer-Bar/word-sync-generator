"""Locally accessible Genius text reaches acoustic alignment when remote lookup fails."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from colab import karaoke_job as job
from karaoke_app import lyric_references as refs


@pytest.fixture
def cached(tmp_path):
    path = tmp_path / "genius.json"
    path.write_text(json.dumps({
        "source": "genius", "url": "https://genius.com/Artist-song-lyrics", "id": 123,
        "metadata": {"title": "Song", "artist": "Artist"}, "original_text": "First line\nSecond line",
        "lines": [{"text": "DO NOT USE", "start_ms": 1234, "words": [{"text": "leaked"}]}],
    }))
    return path


def resolve(path, **options):
    fetch = Mock(side_effect=AssertionError("Valid local fallback must avoid another Genius request"))
    return refs.resolve_reference(
        {"genius_reference_path": str(path), **options}, {"title": "Song", "artist": "Artist"}, None,
        record_to_document=Mock(), candidate_is_safe=job._lrclib_candidate_is_safe, fetch_genius=fetch,
    )


def test_local_provider_text_is_used_without_cached_timings(cached):
    document, evidence = resolve(cached)
    assert document["lines"] == [{"text": "First line"}, {"text": "Second line"}]
    assert evidence["source"] == "genius"
    assert evidence["acquisition"] == "local_before_alignment"
    assert not job._has_complete_word_timings(document)


@pytest.mark.parametrize("failure", ["wrong_title", "wrong_artist", "wrong_url", "corrupt", "empty"])
def test_invalid_local_reference_keeps_remote_recovery(cached, failure):
    data = json.loads(cached.read_text())
    options = {"genius_reference_path": str(cached)}
    if failure == "wrong_title":
        data["metadata"]["title"] = "Different song"
    elif failure == "wrong_artist":
        data["metadata"]["artist"] = "Stranger"
    elif failure == "wrong_url":
        options["genius_url"] = "https://genius.com/Artist-other-lyrics"
    elif failure == "empty":
        data["original_text"] = "[Verse]"
    cached.write_text("{" if failure == "corrupt" else json.dumps(data))
    fetch = Mock(return_value=None)
    document, evidence = refs.resolve_reference(
        options, {"title": "Song", "artist": "Artist"}, None, record_to_document=Mock(),
        candidate_is_safe=job._lrclib_candidate_is_safe, fetch_genius=fetch,
    )
    assert document is None
    fetch.assert_called_once()
    assert evidence["attempts"][0]["acquisition"] == "local"


def test_cached_genius_does_not_replace_lrclib(cached):
    document, evidence = refs.resolve_reference(
        {"genius_reference_path": str(cached)}, {"title": "Song", "artist": "Artist"}, {"id": 42},
        record_to_document=lambda: {"lines": [{"text": "LRCLIB text"}]},
        candidate_is_safe=job._lrclib_candidate_is_safe,
    )
    assert document["lines"][0]["text"] == "LRCLIB text"
    assert evidence["source"] == "lrclib"


def test_explicit_txt_and_forced_whisper_keep_priority(cached, tmp_path):
    text = tmp_path / "lyrics.txt"
    text.write_text("Explicit text")
    document, evidence = resolve(cached, text_path=str(text))
    assert document["lines"] == [{"text": "Explicit text"}]
    assert evidence["source"] == "txt"
    document, evidence = resolve(cached, disable_lrclib=True)
    assert document is None and evidence["source"] == "whisper"


@pytest.mark.parametrize("options,metadata", [
    ({"disable_lrclib": True}, {"title": "Song", "artist": "Artist"}),
    ({"text_path": "lyrics.txt"}, {"title": "Song", "artist": "Artist"}),
    ({"lrclib_id": 42}, {"title": "Song", "artist": "Artist"}),
    ({}, {"title": "Song"}),
])
def test_prefetch_skips_explicit_sources_or_missing_identity(options, metadata, monkeypatch):
    fetch = Mock()
    monkeypatch.setattr(refs, "genius_reference", fetch)
    assert refs.prefetch_genius_reference(options, metadata, Path("missing.py")) is None
    fetch.assert_not_called()


def test_prefetch_failure_is_nonfatal(monkeypatch):
    monkeypatch.setattr(refs, "genius_reference", Mock(side_effect=TimeoutError("offline")))
    assert refs.prefetch_genius_reference(
        {}, {"title": "Song", "artist": "Artist"}, Path(job.__file__),
    ) is None
