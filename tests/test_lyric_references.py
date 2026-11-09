"""Reference retrieval, ordered validation and verse-boundary regressions."""

import copy
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
import yaml

from colab import karaoke_job as job
from karaoke_app import lyric_references as refs
from karaoke_app.lyrics_file import validate_lyrics_file


def transcript(text="all I do is win and not forgive.", *, probability=0.95):
    words = [
        {"text": word, "start": 1 + i * 0.5, "end": 1.3 + i * 0.5, "probability": probability}
        for i, word in enumerate(text.split())
    ]
    return {
        "song": {"title": "Song", "artist": "Artist", "duration": 60},
        "transcription": {"language": "en"},
        "segments": [{"words": words}],
    }


def timed_document(text="all I do is win and not forgive."):
    return job._transcript_to_lyrics(transcript(text))


def resolver(record=None, options=None, fetch=None):
    return refs.resolve_reference(
        options or {},
        {"title": "Song", "artist": "Artist"},
        record,
        record_to_document=lambda: {
            "version": "1.0",
            "metadata": {"title": "Song"},
            "lines": [{"text": "all I do is win and not forgive."}],
        },
        candidate_is_safe=job._lrclib_candidate_is_safe,
        fetch_genius=fetch or Mock(return_value=None),
    )


def test_txt_precedes_lrclib_and_preserves_original(tmp_path):
    path = tmp_path / "verses.txt"
    original = "[Verse 1]\nall I do is\n\nwin and not forgive.\n(oh yeah)\n"
    path.write_text(original, encoding="utf-8-sig")
    fetch = Mock()
    document, evidence = resolver({"id": 1}, {"text_path": str(path)}, fetch)
    assert [line["text"] for line in document["lines"]] == ["all I do is", "win and not forgive.", "(oh yeah)"]
    assert evidence["original_text"] == original
    assert evidence["source"] == "txt"
    fetch.assert_not_called()


def test_disable_skips_every_reference():
    fetch = Mock()
    document, evidence = resolver({"id": 1}, {"disable_lrclib": True, "text_path": "missing"}, fetch)
    assert document is None
    assert evidence["source"] == "whisper"
    fetch.assert_not_called()


def test_empty_txt_is_actionable_error(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("[Verse]\n\n")
    with pytest.raises(ValueError, match="no lyric lines"):
        resolver(options={"text_path": str(path)})


def test_lrclib_keeps_both_structures_and_original_record():
    record = {"id": 42, "plainLyrics": "all I do is\nwin and not forgive."}
    document, evidence = resolver(record)
    assert len(document["lines"]) == 1
    assert len(evidence["structure_lines"]) == 2
    assert evidence["lrclib_record"] == record


def test_conflicting_plain_is_not_silently_combined():
    document, evidence = resolver({"plainLyrics": "something entirely different"})
    assert evidence["text_conflict"]
    assert "structure_lines" not in evidence
    assert document["lines"][0]["text"] == "something entirely different"
    assert evidence["selected_variant"] == "plain_authoritative"


def test_provider_failure_is_recorded():
    document, evidence = resolver(fetch=Mock(side_effect=TimeoutError("offline")))
    assert document is None
    assert "TimeoutError" in evidence["attempts"][0]["error"]


def song(song_id=1, title="Song", artist="Artist"):
    return {
        "id": song_id,
        "title": title,
        "primary_artist": {"name": artist},
        "url": f"https://genius.com/Artist-{song_id}-lyrics",
    }


@pytest.mark.parametrize(
    "candidates,expected",
    [
        ([song()], True),
        ([song(artist="Other")], False),
        ([song(title="Other Song Live")], False),
        ([song(1), song(2)], False),
        ([song(), song()], True),
    ],
)
def test_genius_checks_metadata_and_ambiguity(candidates, expected):
    client = Mock()
    client.authorization_header = {}
    client.lyrics.return_value = "[Verse]\nline one\nline two"
    response = {"sections": [{"hits": [{"result": item} for item in candidates]}]}
    with patch("lyricsgenius.PublicAPI.search_songs", return_value=response):
        result = refs.genius_reference(
            {"title": "Song", "artist": "Artist"},
            url=None,
            candidate_is_safe=job._lrclib_candidate_is_safe,
            client_factory=lambda: client,
        )
    assert bool(result) is expected
    assert client.lyrics.call_count == int(expected)


def test_explicit_genius_url_selects_metadata_checked_candidate():
    client = Mock()
    client.authorization_header = {}
    client.lyrics.return_value = "one\ntwo"
    response = {"sections": [{"hits": [{"result": song(1)}, {"result": song(2)}]}]}
    with patch("lyricsgenius.PublicAPI.search_songs", return_value=response):
        result = refs.genius_reference(
            {"title": "Song", "artist": "Artist"},
            url=song(2)["url"],
            candidate_is_safe=job._lrclib_candidate_is_safe,
            client_factory=lambda: client,
        )
    assert result["id"] == 2


def test_real_lyricsgenius_parser_needs_no_token_and_preserves_breaks(monkeypatch):
    monkeypatch.delenv("GENIUS_ACCESS_TOKEN", raising=False)
    client = refs._genius_client()
    html = '<div data-lyrics-container="true">[Verse]<br>all I do is<br>win and not forgive.</div>'
    with patch.object(client, "_make_request", return_value={"html": html}):
        text = client.lyrics(song_url="https://genius.com/Artist-song-lyrics")
    assert text == "[Verse]\nall I do is\nwin and not forgive."


@pytest.mark.parametrize(
    "url",
    [
        "http://genius.com/a-lyrics",
        "https://evil.com/a-lyrics",
        "https://genius.com.evil.com/a-lyrics",
        "https://genius.com/a",
        "https://user@genius.com/a-lyrics",
        "https://genius.com/a-lyrics?x=1",
    ],
)
def test_genius_url_rejects_non_song_urls(url):
    with pytest.raises(ValueError):
        refs.validate_genius_url(url)


def test_regroup_splits_example_without_changing_word_timings():
    original = timed_document()
    result = refs.restore_structure(original, refs.plain_lines("all I do is\nwin and not forgive."))
    result = validate_lyrics_file(result, require_words=True)
    assert len(original["lines"]) == 1
    assert result["plain"] == "all I do is\nwin and not forgive."
    assert [(line["start_ms"], line["end_ms"]) for line in result["lines"]] == [(1000, 2800), (3000, 4800)]
    assert [word for line in result["lines"] for word in line["words"]] == original["lines"][0]["words"]


def test_structure_preserves_background_channels():
    original = timed_document()
    original["lines"][0].update(agent="v2", isBackground=True)
    result = refs.restore_structure(original, refs.plain_lines("all I do is\nwin and not forgive."))
    assert all(word["agent"] == "v2" and word["isBackground"] for line in result["lines"] for word in line["words"])
    validate_lyrics_file(result)


def test_structure_can_merge_existing_lines_without_joining_words():
    original = timed_document()
    split = refs.restore_structure(original, refs.plain_lines("all I do is\nwin and not forgive."))
    split["lines"][0]["words"][-1]["text"] = "is"
    merged = refs.restore_structure(split, refs.plain_lines("all I do is win and not forgive."))
    assert validate_lyrics_file(merged)["plain"] == "all I do is win and not forgive."


def test_structure_never_interpolates_inside_word():
    original = timed_document("one-two three")
    with pytest.raises(ValueError, match="inside a timed word"):
        refs.restore_structure(original, refs.plain_lines("one\ntwo three"))


def test_structure_rejects_missing_words():
    with pytest.raises(ValueError, match="differ"):
        refs.restore_structure(timed_document(), refs.plain_lines("all I do"))


def test_comparison_preserves_order_and_reports_substitution():
    result = refs.compare_reference(
        refs.plain_lines("all I do is\nwin and not forgive."), transcript("all I do is lose and not forgive.")
    )
    assert result["needs_review"]
    assert result["lines"][1]["missing_or_different"] == ["win"]
    assert result["lines"][1]["differences"][0]["asr"] == ["lose"]
    assert refs.anchored_document({"lines": refs.plain_lines("all I do is\nwin and not forgive.")}, result) is None


def test_missing_repeated_chorus_cannot_anchor_wrong_occurrence():
    result = refs.compare_reference(refs.plain_lines("sing it again\nsing it again"), transcript("sing it again"))
    assert result["needs_review"]
    assert not any("anchor" in line for line in result["lines"])


def test_complete_repeated_chorus_keeps_occurrences_ordered():
    result = refs.compare_reference(
        refs.plain_lines("sing it again\nsing it again"), transcript("sing it again sing it again")
    )
    assert not result["needs_review"]
    assert result["lines"][0]["anchor"]["end_ms"] < result["lines"][1]["anchor"]["start_ms"]


def test_unique_surrounding_verse_does_not_disambiguate_missing_chorus():
    result = refs.compare_reference(
        refs.plain_lines("opening verse\nsing it again\nsing it again\nclosing verse"),
        transcript("opening verse sing it again closing verse"),
    )
    assert result["needs_review"]
    assert "anchor" in result["lines"][0]
    assert all("anchor" not in line for line in result["lines"][1:3])


def test_low_confidence_is_not_a_recovery_anchor():
    result = refs.compare_reference(refs.plain_lines("all I do is"), transcript("all I do is", probability=0.1))
    assert result["needs_review"]
    assert "anchor" not in result["lines"][0]


def test_partial_text_detects_asr_only_content():
    result = refs.compare_reference(refs.plain_lines("all I do"), transcript())
    assert refs.likely_incomplete(result)


def test_instrumental_gap_is_preserved_in_anchors():
    speech = transcript("first verse here second verse here")
    for word in speech["segments"][0]["words"][3:]:
        word["start"] += 30
        word["end"] += 30
    lines = refs.plain_lines("first verse here\nsecond verse here")
    result = refs.compare_reference(lines, speech)
    anchored = refs.anchored_document({"lines": lines}, result)
    assert anchored["lines"][1]["start_ms"] - anchored["lines"][0]["end_ms"] > 30000
    assert "start_ms" not in lines[0]


@pytest.fixture
def preparation(tmp_path):
    metadata = {"title": "Song", "artist": "Artist", "duration": 60, "uploader": "Artist"}
    config = {"language": "en", "lyrics": {}, "whisper_model": "large-v3"}

    def run(record=None):
        return job._prepare_lyrics(Path("vocals.wav"), metadata, config, selected_record=record, artifacts_dir=tmp_path)

    return run, config, tmp_path


def test_pipeline_validates_provided_timings_and_restructures(preparation):
    run, _, directory = preparation
    record = {"lyricsfile": yaml.safe_dump(timed_document()), "plainLyrics": "all I do is\nwin and not forgive."}
    with patch.object(job, "_transcribe", return_value=transcript()) as transcribe_mock:
        with patch.object(job, "_align_known_lyrics") as align:
            lyrics, alignment = run(record)
    assert len(lyrics["lines"]) == 2
    assert alignment["word_timing"] == "provided"
    assert not alignment["needs_review"]
    transcribe_mock.assert_called_once()
    align.assert_not_called()
    assert json.loads((directory / "lyrics_reference.json").read_text())["structure_restored"]
    assert (directory / "transcription.json").is_file()
    assert len(json.loads((directory / "lyrics_validation.json").read_text())["lines"]) == 2


def test_pipeline_recovers_with_whisper_anchors_without_retranscribing(preparation):
    run, _, _ = preparation
    record = {"plainLyrics": "all I do is win and not forgive."}
    with patch.object(job, "_transcribe", return_value=transcript()) as transcribe_mock:
        results = [RuntimeError("collapse"), (timed_document(), [])]
        with patch.object(job, "_align_known_lyrics", side_effect=results) as align:
            _, alignment = run(record)
    assert alignment["strategy"] == "whisper_anchored_ctc"
    transcribe_mock.assert_called_once()
    assert align.call_args.kwargs["recovery_only"]
    assert align.call_args.args[1]["lines"][0]["start_ms"] == 1000


def test_pipeline_ctc_failure_still_preserves_known_verses(preparation):
    run, _, _ = preparation
    with patch.object(job, "_transcribe", return_value=transcript()) as transcribe_mock:
        with patch.object(job, "_align_known_lyrics", side_effect=RuntimeError("collapse")):
            lyrics, alignment = run({"plainLyrics": "all I do is\nwin and not forgive."})
    assert lyrics["plain"] == "all I do is\nwin and not forgive."
    assert alignment["strategy"] == "reference_text_asr_timing"
    assert alignment["needs_review"]
    transcribe_mock.assert_called_once()


def test_pipeline_disagreement_keeps_reference_text(preparation):
    run, _, directory = preparation
    with patch.object(job, "_transcribe", return_value=transcript("all I do is lose and not forgive.")):
        with patch.object(job, "_align_known_lyrics", return_value=(timed_document(), [])):
            lyrics, alignment = run({"plainLyrics": "all I do is win and not forgive."})
    assert "win" in lyrics["plain"]
    assert alignment["needs_review"]
    assert json.loads((directory / "lyrics_validation.json").read_text())["unmatched_asr"] == ["lose"]


def test_pipeline_no_reference_has_explicit_heuristic_status(preparation):
    run, config, _ = preparation
    config["lyrics"]["disable_lrclib"] = True
    with patch.object(job, "_transcribe", return_value=transcript()) as transcribe_mock:
        lyrics, alignment = run()
    assert len(lyrics["lines"]) == 1
    assert alignment["segmentation"] == "heuristic"
    assert alignment["needs_review"]
    transcribe_mock.assert_called_once()


def test_pipeline_missing_asr_does_not_discard_provided_timings(preparation):
    run, _, directory = preparation
    with patch.object(job, "_transcribe", side_effect=RuntimeError("no speech")):
        lyrics, alignment = run({"lyricsfile": yaml.safe_dump(timed_document())})
    assert lyrics["lines"]
    assert alignment["needs_review"]
    assert json.loads((directory / "lyrics_validation.json").read_text())["status"] == "unavailable"


def test_pipeline_auto_language_uses_independent_asr(preparation):
    run, config, _ = preparation
    config["language"] = "auto"
    with patch.object(job, "_transcribe", return_value=transcript()):
        with patch.object(job, "_align_known_lyrics", return_value=(timed_document(), [])) as align:
            run({"plainLyrics": "all I do is win and not forgive."})
    assert align.call_args.args[1]["metadata"]["language"] == "en"


def test_pipeline_partial_reference_is_authoritative_and_only_diagnosed(preparation):
    run, _, directory = preparation
    with patch.object(job, "_transcribe", return_value=transcript()):
        with patch.object(refs, "_genius_client") as genius:
            with patch.object(job, "_align_known_lyrics", side_effect=RuntimeError("collapse")):
                lyrics, alignment = run({"plainLyrics": "all I do"})
    genius.assert_not_called()
    assert lyrics["plain"] == "all I do"
    assert alignment["text_source"] == "lrclib"
    assert json.loads((directory / "lyrics_reference.json").read_text())["possibly_incomplete"]
    assert (directory / "reference.txt").read_text() == "all I do\n"


def test_pipeline_marks_timing_disagreement(preparation):
    run, _, directory = preparation
    shifted = copy.deepcopy(timed_document())
    for line in shifted["lines"]:
        line["start_ms"] += 3000
        line["end_ms"] += 3000
        for word in line["words"]:
            word["start_ms"] += 3000
            word["end_ms"] += 3000
    with patch.object(job, "_transcribe", return_value=transcript()):
        with patch.object(job, "_align_known_lyrics", return_value=(shifted, [])):
            _, alignment = run({"plainLyrics": "all I do is win and not forgive."})
    assert alignment["needs_review"]
    assert json.loads((directory / "lyrics_validation.json").read_text())["lines"][0]["start_deviation_ms"] == 3000


def test_colab_can_load_uploaded_service_without_package(tmp_path):
    uploaded = tmp_path / "karaoke_lyric_references.py"
    uploaded.write_text(Path(refs.__file__).read_text())
    with patch.object(job, "REFERENCES_MODULE_PATH", uploaded):
        service = job._load_references_module()
    assert service.plain_lines("first\nsecond") == [{"text": "first"}, {"text": "second"}]


def test_ctc_recovery_uses_line_crops_and_accepts_zero_start():
    document = refs.restore_structure(timed_document(), refs.plain_lines("all I do is\nwin and not forgive."))
    for line in document["lines"]:
        line["start_ms"] -= 1000
        line["end_ms"] -= 1000
        for word in line["words"]:
            word["start_ms"] -= 1000
            word["end_ms"] -= 1000
    torch = MagicMock()
    torch.cuda.is_available.return_value = False
    aligner = MagicMock()
    aligner.load_alignment_model.return_value = (MagicMock(), MagicMock())
    waveform = MagicMock()
    waveform.shape = (1, 960000)
    aligner.load_audio.return_value = waveform
    hf = MagicMock()
    hf.snapshot_download.return_value = "/tmp/model"

    def align_crop(**kwargs):
        return [copy.deepcopy(line) for line, _ in kwargs["tokenized_lines"]]

    with patch.dict(sys.modules, {"torch": torch, "ctc_forced_aligner": aligner, "huggingface_hub": hf}):
        with patch.object(job, "_align_tokenized_lines", side_effect=align_crop) as align:
            lyrics, _ = job._align_known_lyrics(Path("vocals.wav"), document, {"language": "en"}, recovery_only=True)
    assert align.call_count == 2
    assert all(call.kwargs["batch_size"] == 1 for call in align.call_args_list)
    assert [call.kwargs["time_offset_sec"] for call in align.call_args_list] == [0.0, 0.5]
    assert lyrics["lines"][0]["start_ms"] == 0
    assert waveform.__getitem__.call_count == 2


def test_merge_copies_typography_without_changing_timing_or_input():
    original = timed_document("ONLY Saturdays on late nights")
    snapshot = copy.deepcopy(original)
    result, _ = refs.merge_reference_lines(original, refs.plain_lines("Only Saturdays, on late nights"))
    assert validate_lyrics_file(result)["plain"] == "Only Saturdays, on late nights"
    assert original == snapshot
    assert [(w["start_ms"], w["end_ms"]) for line in result["lines"] for w in line["words"]] == [
        (w["start_ms"], w["end_ms"]) for line in original["lines"] for w in line["words"]
    ]


def test_merge_does_not_replace_substitutions_or_split_timed_words():
    for observed, desired in [
        ("hitting corners and clerks", "hitting corners and curbs"),
        ("one-two three", "one two three"),
    ]:
        original = timed_document(observed)
        result, _ = refs.merge_reference_lines(original, refs.plain_lines(desired))
        assert result["lines"] == original["lines"]


def test_pipeline_fallback_copies_reference_case_and_punctuation(preparation):
    run, _, _ = preparation
    with patch.object(job, "_transcribe", return_value=transcript("ALL I do is win and not forgive")):
        with patch.object(job, "_align_known_lyrics", side_effect=RuntimeError("collapse")):
            lyrics, _ = run({"plainLyrics": "all I do is win and not forgive."})
    assert lyrics["plain"] == "all I do is win and not forgive."


@pytest.mark.parametrize(
    "observed,reference",
    [
        ("I see a bird today", "I see a bear today"),
        ("I see today", "I see a bear today"),
        ("I see a small bird today", "I see a bear today"),
        ("one two", "first one two last"),
        ("one-two three", "one two three"),
        ("one two three", "one-two three"),
        ("sing it again", "sing it again\nsing it again"),
        ("something completely different", "Bear, bear!"),
    ],
)
def test_authoritative_fallback_reconstructs_reference_with_valid_times(observed, reference):
    original = timed_document(observed)
    snapshot = copy.deepcopy(original)
    result, report = refs.apply_reference_text(original, refs.plain_lines(reference))
    result = validate_lyrics_file(result, require_words=True)
    assert result["plain"] == reference
    assert "\n".join("".join(w["text"] for w in line["words"]).strip() for line in result["lines"]) == reference
    assert original == snapshot
    assert result["lines"][0]["start_ms"] >= original["lines"][0]["start_ms"]
    assert result["lines"][-1]["end_ms"] <= original["lines"][-1]["end_ms"]
    words = [word for line in result["lines"] for word in line["words"]]
    assert all("confidence" not in words[index] for index in report["estimated_word_indexes"])


def test_insertion_without_silence_borrows_time_without_overlap():
    original = timed_document("one two")
    original["lines"][0]["words"][1]["start_ms"] = original["lines"][0]["words"][0]["end_ms"]
    result, report = refs.apply_reference_text(original, refs.plain_lines("one extra two"))
    assert validate_lyrics_file(result, require_words=True)["plain"] == "one extra two"
    assert report["estimated_words"] >= 2


def test_omitted_verse_uses_available_gap_instead_of_collapsing_at_chorus():
    observed = transcript("intro noise chorus")
    for word, (start, end) in zip(
        observed["segments"][0]["words"], [(4.45, 6.43), (36.33, 36.65), (36.65, 37.0)], strict=True
    ):
        word.update(start=start, end=end)
    original = job._transcript_to_lyrics(observed)
    missing = "\n".join(" ".join(f"verse{i}word{j}" for j in range(10)) for i in range(12))
    result, report = refs.apply_reference_text(original, refs.plain_lines(f"intro\n{missing}\nchorus"))
    result = validate_lyrics_file(result, require_words=True)

    assert result["lines"][1]["start_ms"] == 6430
    assert result["lines"][-2]["end_ms"] == 36650
    assert all(line["end_ms"] - line["start_ms"] > 2000 for line in result["lines"][1:-1])
    for key in ("start_ms", "end_ms", "confidence"):
        assert result["lines"][0]["words"][0][key] == original["lines"][0]["words"][0][key]
    assert result["lines"][-1]["start_ms"] == 36650
    assert report["estimated_words"] == 120
    assert all("confidence" not in word for line in result["lines"][1:-1] for word in line["words"])


@pytest.mark.parametrize("source", ["txt", "lrclib", "genius"])
def test_bear_overrides_whisper_bird_even_when_ctc_fails(preparation, source):
    run, config, directory = preparation
    record = {"plainLyrics": "I see a bear today"} if source == "lrclib" else None
    if source == "txt":
        path = directory / "input.txt"
        path.write_text("I see a bear today")
        config["lyrics"]["text_path"] = str(path)
    reference = {"source": "genius", "lines": refs.plain_lines("I see a bear today")}
    with patch.object(refs, "genius_reference", return_value=reference):
        with patch.object(job, "_transcribe", return_value=transcript("I see a bird today")):
            with patch.object(job, "_align_known_lyrics", side_effect=RuntimeError("collapse")):
                lyrics, alignment = run(record)
    assert lyrics["plain"] == "I see a bear today"
    assert lyrics["lines"][0]["words"][3]["text"].strip() == "bear"
    assert alignment["words"][3]["text"] == "bear"
    assert alignment["text_source"] == source
    assert alignment["grouping"]["estimated_words"] == 1
    assert json.loads((directory / "transcription.json").read_text())["segments"][0]["words"][3]["text"] == "bird"


def test_conflicting_lrclib_plain_overrides_word_timed_variant(preparation):
    run, _, _ = preparation
    record = {"plainLyrics": "I see a bear today", "lyricsfile": yaml.safe_dump(timed_document("I see a bird today"))}
    with patch.object(job, "_transcribe", return_value=transcript("I see a bird today")):
        with patch.object(job, "_align_known_lyrics", side_effect=RuntimeError("collapse")) as align:
            lyrics, _ = run(record)
    assert align.call_args.args[1]["lines"][0]["text"] == "I see a bear today"
    assert lyrics["plain"] == "I see a bear today"


def test_sanitize_text_homoglyphs_and_invisibles():
    # Cyrillic homoglyphs in English text
    line = "Don't take him serious, can't tak\u0435 him anywhere"
    assert refs.sanitize_text(line) == "Don't take him serious, can't take him anywhere"

    line2 = "He is a fun-time, one-tim\u0435 kind of guy, oh yeah"
    assert refs.sanitize_text(line2) == "He is a fun-time, one-time kind of guy, oh yeah"

    # Invisible characters and non-standard spaces
    dirty = "Hello\u200b\ufeff\u00ad \u00a0world"
    assert refs.sanitize_text(dirty) == "Hello  world"

    # Preserves genuine Russian text
    russian = "Привет, мир! Как дела?"
    assert refs.sanitize_text(russian) == russian

    # Cleans mixed token inside Russian text
    mixed = "Привет, это r\u0435mix трека"
    assert refs.sanitize_text(mixed) == "Привет, это remix трека"


def test_plain_lines_sanitizes_homoglyphs():
    raw = "Don't take him serious, can't tak\u0435 him anywhere\n[Chorus]\none-tim\u0435\n"
    lines = refs.plain_lines(raw)
    assert lines == [
        {"text": "Don't take him serious, can't take him anywhere"},
        {"text": "one-time"},
    ]


def test_validate_lyrics_file_sanitizes_lines_and_words():
    document = {
        "version": "1.0",
        "metadata": {"title": "Test Song"},
        "lines": [
            {
                "text": "can't tak\u0435 him",
                "start_ms": 1000,
                "end_ms": 3000,
                "words": [
                    {"text": "can't ", "start_ms": 1000, "end_ms": 1500},
                    {"text": "tak\u0435 ", "start_ms": 1500, "end_ms": 2000},
                    {"text": "him", "start_ms": 2000, "end_ms": 3000},
                ],
            }
        ],
    }
    validated = validate_lyrics_file(document, require_words=True)
    assert validated["lines"][0]["text"] == "can't take him"
    assert validated["lines"][0]["words"][1]["text"] == "take "
    assert validated["plain"] == "can't take him"


def test_wrapped_section_header_becomes_shared_agent():
    lines = refs.plain_lines("Yeah\n[Verse 1: Lead Singer,\nGuest Singer\n]\nSing this\n[Chorus]\n(oh yeah)")
    assert lines == [
        {"text": "Yeah"},
        {"text": "Sing this", "agent": "Lead Singer, Guest Singer"},
        {"text": "(oh yeah)"},
    ]


@pytest.mark.parametrize("apply", [refs.apply_reference_text, refs.merge_reference_lines, refs.restore_structure])
def test_reference_agents_reach_timed_words(apply):
    original = timed_document()
    desired = refs.plain_lines("[Verse 1: Lead Singer]\nall I do is\n[Verse 2: Guest Singer]\nwin and not forgive.")
    output = apply(original, desired)
    result = output[0] if isinstance(output, tuple) else output
    assert [line["agent"] for line in result["lines"]] == ["Lead Singer", "Guest Singer"]
    assert all(word["agent"] == line["agent"] for line in result["lines"] for word in line["words"])
    assert [(w["start_ms"], w["end_ms"]) for line in result["lines"] for w in line["words"]] == [
        (w["start_ms"], w["end_ms"]) for line in original["lines"] for w in line["words"]
    ]
    validate_lyrics_file(result)


def test_reference_agent_applies_when_text_already_matches():
    original = timed_document()
    desired = [{"text": line["text"], "agent": "Lead Singer"} for line in original["lines"]]
    result, _ = refs.apply_reference_text(original, desired)
    assert all(w["agent"] == "Lead Singer" for line in result["lines"] for w in line["words"])


def test_saved_reference_keeps_section_headers(tmp_path):
    text = "[Verse 1: Lead Singer,\nGuest Singer\n]\nSing this"
    job._save_lyrics_evidence(tmp_path, "lyrics_reference.json", {
        "original_text": text, "lines": refs.plain_lines(text),
    })
    assert refs.plain_lines((tmp_path / "reference.txt").read_text()) == refs.plain_lines(text)
