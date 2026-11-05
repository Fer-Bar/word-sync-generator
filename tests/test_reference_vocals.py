"""Reference vocal roles survive the CTC and ASR fallback paths."""

import copy
from unittest.mock import Mock

import pytest

from colab import karaoke_job as job
from karaoke_app import lyric_references as refs
from karaoke_app.browser_lyrics import build_browser_scene
from karaoke_app.lyrics_file import lyrics_to_transcript, validate_lyrics_file


def document(text):
    return job._transcript_to_lyrics({
        "song": {"title": "Song", "duration": 60},
        "transcription": {"language": "en"},
        "segments": [{"words": [
            {"text": token, "start": i * 0.5, "end": i * 0.5 + 0.4}
            for i, token in enumerate(text.split())
        ]}],
    })


@pytest.mark.parametrize("source", ["Sing it oh yeah again", "Sing it (oh yeah) again"])
def test_fallback_marks_choruses_without_changing_word_times(source):
    original = document(source)
    before = copy.deepcopy(original)
    result, evidence = refs.apply_reference_text(original, refs.plain_lines("Sing it (oh yeah) again"))
    words = [w for line in result["lines"] for w in line["words"]]
    assert [bool(w.get("isBackground")) for w in words] == [False, False, True, True, False]
    assert [(w["start_ms"], w["end_ms"]) for w in words] == [
        (w["start_ms"], w["end_ms"]) for line in before["lines"] for w in line["words"]
    ]
    assert evidence["estimated_words"] == 0
    assert original == before
    validated = validate_lyrics_file(result)
    again, _ = refs.apply_reference_text(validated, refs.plain_lines("Sing it (oh yeah) again"))
    assert validate_lyrics_file(again) == validated
    for mode in ("lyrics", "karaoke"):
        scene = build_browser_scene(
            lyrics_to_transcript(validated), {"width": 640, "height": 360, "fps": 12}, {"font_size": 40}, mode,
        )
        background = [p for line in scene["lyrics"] for p in line["parts"] if p.get("isBackground")]
        assert len(background) == 2
        assert [p["startTimeMs"] for p in background] == [1000, 1500]


def test_fallback_background_span_can_cross_line_breaks():
    reference = refs.plain_lines("Lead (\nquiet echo\n)\nLead again")
    result, _ = refs.apply_reference_text(document("Lead quiet echo Lead again"), reference)
    words = [w for line in result["lines"] for w in line["words"] if refs.normalized_units(w["text"])]
    assert [bool(w.get("isBackground")) for w in words] == [False, True, True, False, False]
    validate_lyrics_file(result)


def test_unclosed_parenthesis_does_not_mark_rest_of_song_as_background():
    result, _ = refs.apply_reference_text(document("Lead echo next verse"), refs.plain_lines("Lead (echo\nnext verse"))
    assert not any(w.get("isBackground") for line in result["lines"] for w in line["words"])


def test_ctc_tokens_support_cross_line_background_and_section_performers():
    lines = refs.plain_lines("[Verse: Alice]\nLead (\necho here\n)\n[Verse: Bob]\nSing again")
    tokenized = job._alignment_document_tokens(lines, character_alignment=False)
    words = [token for _, tokens in tokenized for token in tokens]
    assert [w["text"] for w in words] == ["Lead", "echo", "here", "Sing", "again"]
    assert [bool(w.get("isBackground")) for w in words] == [False, True, True, False, False]
    assert [w["agent"] for w in words] == ["Alice", "Alice", "Alice", "Bob", "Bob"]


def test_ctc_still_rejects_unbalanced_parentheses():
    with pytest.raises(ValueError, match="Unbalanced"):
        job._alignment_line_tokens({"text": "Lead (echo"}, character_alignment=False)


def test_character_alignment_keeps_background_across_lines():
    tokenized = job._alignment_document_tokens(refs.plain_lines("歌(\n声)歌"), character_alignment=True)
    words = [token for _, tokens in tokenized for token in tokens]
    assert [w["text"] for w in words] == ["歌", "声", "歌"]
    assert [bool(w.get("isBackground")) for w in words] == [False, True, False]


def test_ctc_cross_line_background_produces_valid_lyrics():
    lines = job._alignment_document_tokens(refs.plain_lines("Lead (\necho here\n)\nAgain"), character_alignment=False)
    for _, tokens in lines:
        for token in tokens:
            token["alignment_units"] = [token["text"]]
    aligned = job._align_tokenized_lines(
        model=None, tokenizer=None, waveform=None, tokenized_lines=lines, language="eng", character_alignment=False,
        generate_emissions=Mock(return_value=(None, 0.02)), preprocess_text=Mock(return_value=(None, None)),
        get_alignments=Mock(return_value=(None, None, None)), get_spans=Mock(),
        postprocess_results=Mock(return_value=[{"start": i, "end": i + 0.4, "score": 0} for i in range(4)]),
    )
    result = validate_lyrics_file({"version": "1.0", "metadata": {"title": "Song"}, "lines": aligned})
    assert [line["text"] for line in result["lines"]] == ["Lead", "echo here", "Again"]
    assert all(w["isBackground"] for w in result["lines"][1]["words"])


def test_explicit_background_metadata_survives_reference_without_parentheses():
    original = document("soft echo")
    original["lines"][0]["isBackground"] = True
    result, _ = refs.apply_reference_text(original, refs.plain_lines("soft echo"))
    assert result["lines"][0]["isBackground"] is True


def test_existing_ctc_background_timings_are_not_reallocated():
    original = document("Sing echo")
    original["lines"][0]["text"] = "Sing (echo)"
    original["lines"][0]["words"][1].update(isBackground=True, start_ms=100, end_ms=300)
    original = validate_lyrics_file(original)
    result, evidence = refs.apply_reference_text(original, refs.plain_lines("Sing (echo)"))
    assert result == original
    assert evidence["method"] == "existing_reference_timings"
