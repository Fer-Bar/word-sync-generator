import re
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from colab.karaoke_job import (
    _align_known_lyrics,
    _artist_variants,
    _build_lyric_pages,
    _fetch_lrclib,
    _group_lines_into_macro_sections,
    _group_words,
    _is_alignment_healthy,
    _lrclib_candidate_is_safe,
    _lrclib_match_score,
    _lyrics_document_from_record,
    _parse_synced_lyrics,
    _title_edition_tokens,
    _title_variants,
    _write_ass,
)

KARAOKE_DURATION_PATTERN = re.compile(r"\\k(?:f)?(\d+)")


def _line(index: int, start: float, end: float, text: str | None = None) -> dict[str, Any]:
    value = text or f"line-{index}"
    return {
        "id": f"s{index}",
        "start": start,
        "end": end,
        "text": value,
        "words": [{"id": f"s{index}-w0", "start": start, "end": end, "text": value}],
    }


def _render_ass(segments: list[dict[str, Any]]) -> str:
    with tempfile.TemporaryDirectory() as temporary_directory:
        output = Path(temporary_directory) / "karaoke.ass"
        _write_ass({"segments": segments}, output, {"width": 1920, "height": 1080})
        return output.read_text(encoding="utf-8")


def _timestamp_centiseconds(value: str) -> int:
    hours, minutes, seconds = value.split(":")
    whole_seconds, centiseconds = seconds.split(".")
    return ((int(hours) * 60 + int(minutes)) * 60 + int(whole_seconds)) * 100 + int(centiseconds)


def _dialogues(content: str) -> list[tuple[int, int, str]]:
    dialogues = []
    for line in content.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        fields = line.split(",", maxsplit=9)
        dialogues.append((_timestamp_centiseconds(fields[1]), _timestamp_centiseconds(fields[2]), fields[9]))
    return dialogues


def _karaoke_duration(text: str) -> int:
    return sum(int(duration) for duration in KARAOKE_DURATION_PATTERN.findall(text))


class LyricPageTests(unittest.TestCase):
    def test_word_grouping_keeps_punctuation_character_and_gap_boundaries(self) -> None:
        words = [
            {"start": 0.0, "end": 0.2, "text": "Done.", "probability": 1.0},
            {"start": 0.3, "end": 0.5, "text": "Verylong", "probability": 1.0},
            {"start": 0.6, "end": 0.8, "text": "phrase", "probability": 1.0},
            {"start": 2.0, "end": 2.2, "text": "Later", "probability": 1.0},
        ]

        segments = _group_words(words, max_chars=12, max_gap=0.8)

        self.assertEqual([segment["text"] for segment in segments], ["Done.", "Verylong", "phrase", "Later"])

    def test_pages_contain_at_most_three_consecutive_lines(self) -> None:
        segments = [_line(index, index * 1.1, index * 1.1 + 1.0) for index in range(4)]

        pages = _build_lyric_pages(segments)

        self.assertEqual([[line["id"] for line in page["lines"]] for page in pages], [["s0", "s1", "s2"], ["s3"]])

    def test_pages_break_before_long_silence_and_maximum_duration(self) -> None:
        silence_pages = _build_lyric_pages([_line(0, 0.0, 1.0), _line(1, 2.5, 3.0)])
        duration_pages = _build_lyric_pages([_line(0, 0.0, 6.0), _line(1, 6.1, 12.0), _line(2, 12.1, 15.1)])

        self.assertEqual([len(page["lines"]) for page in silence_pages], [1, 1])
        self.assertEqual([len(page["lines"]) for page in duration_pages], [2, 1])

    def test_neighboring_page_display_times_do_not_overlap(self) -> None:
        segments = [_line(index, index * 1.1, index * 1.1 + 1.0) for index in range(4)]

        pages = _build_lyric_pages(segments)

        self.assertEqual(pages[0]["display_end_cs"], 325)
        self.assertEqual(pages[0]["display_end_cs"], pages[1]["display_start_cs"])


class AssRenderingTests(unittest.TestCase):
    def assert_valid_dialogue_timing(self, dialogues: list[tuple[int, int, str]]) -> None:
        for start, end, text in dialogues:
            durations = [int(duration) for duration in KARAOKE_DURATION_PATTERN.findall(text)]
            self.assertTrue(durations)
            self.assertTrue(all(duration > 0 for duration in durations))
            self.assertLessEqual(start + sum(durations), end)
        for previous, following in zip(dialogues, dialogues[1:], strict=False):
            self.assertLessEqual(previous[1], following[0])

    def test_ass_renders_centered_page_with_fade_and_absolute_karaoke_timing(self) -> None:
        segments = [
            {
                "start": 1.0,
                "end": 1.8,
                "words": [
                    {"start": 1.0, "end": 1.2, "text": "Hello"},
                    {"start": 1.5, "end": 1.8, "text": "world"},
                ],
            },
            {
                "start": 2.1,
                "end": 2.5,
                "words": [{"start": 2.1, "end": 2.5, "text": "again"}],
            },
        ]

        content = _render_ass(segments)

        dialogue_lines = [line for line in content.splitlines() if line.startswith("Dialogue:")]
        self.assertEqual(len(dialogue_lines), 1)
        self.assertIn("1,4,1,5,70,70,70,1", content)
        self.assertIn("Dialogue: 0,0:00:00.65,0:00:02.85", dialogue_lines[0])
        self.assertIn(r"{\fad(150,150)}{\k35}{\kf50}Hello {\kf60}world\N{\kf40}again", dialogue_lines[0])
        self.assert_valid_dialogue_timing(_dialogues(content))

    def test_ass_page_dialogues_share_a_non_overlapping_boundary(self) -> None:
        content = _render_ass([_line(index, index * 1.1, index * 1.1 + 1.0) for index in range(4)])

        dialogue_lines = [line for line in content.splitlines() if line.startswith("Dialogue:")]
        self.assertEqual(len(dialogue_lines), 2)
        first_fields = dialogue_lines[0].split(",", maxsplit=9)
        second_fields = dialogue_lines[1].split(",", maxsplit=9)
        self.assertEqual(first_fields[2], second_fields[1])
        self.assertEqual(first_fields[2], "0:00:03.25")
        self.assertEqual(first_fields[9].count(r"\N"), 2)
        self.assertNotIn(r"\N", second_fields[9])
        self.assert_valid_dialogue_timing(_dialogues(content))

    def test_near_simultaneous_page_boundary_contains_complete_schedules(self) -> None:
        segments = [
            _line(0, 0.0, 0.01),
            _line(1, 0.02, 0.03),
            _line(2, 0.2, 0.2),
            _line(3, 0.208, 0.3),
        ]

        dialogues = _dialogues(_render_ass(segments))

        self.assertEqual(len(dialogues), 2)
        self.assertEqual(dialogues[0][1], 21)
        self.assertEqual(dialogues[1][0], 21)
        self.assertEqual(dialogues[0][0] + _karaoke_duration(dialogues[0][2]), dialogues[0][1])
        self.assert_valid_dialogue_timing(dialogues)

    def test_negative_page_gap_finishes_earlier_page_before_delaying_following_page(self) -> None:
        segments = [
            _line(0, 0.0, 1.0),
            _line(1, 1.1, 2.0),
            _line(2, 2.1, 3.0),
            _line(3, 2.9, 3.2),
        ]

        dialogues = _dialogues(_render_ass(segments))

        self.assertEqual(len(dialogues), 2)
        self.assertEqual(dialogues[0][1], 300)
        self.assertEqual(dialogues[1][0], 300)
        self.assertEqual(dialogues[0][0] + _karaoke_duration(dialogues[0][2]), dialogues[0][1])
        self.assert_valid_dialogue_timing(dialogues)

    def test_ass_uses_positive_centiseconds_without_exceeding_dialogue_end(self) -> None:
        segments = [
            {
                "start": 1.0,
                "end": 1.006,
                "words": [
                    {"start": 1.0, "end": 1.003, "text": "One"},
                    {"start": 1.004, "end": 1.006, "text": "two"},
                ],
            }
        ]

        dialogues = _dialogues(_render_ass(segments))

        self.assertEqual(KARAOKE_DURATION_PATTERN.findall(dialogues[0][2])[-2:], ["1", "1"])
        self.assert_valid_dialogue_timing(dialogues)

    def test_empty_word_segments_are_skipped(self) -> None:
        empty_segment = {"start": 0.0, "end": 1.0, "text": "", "words": []}

        mixed_dialogues = _dialogues(_render_ass([empty_segment, _line(1, 1.0, 2.0), empty_segment]))
        empty_dialogues = _dialogues(_render_ass([empty_segment]))

        self.assertEqual(len(mixed_dialogues), 1)
        self.assertIn("line-1", mixed_dialogues[0][2])
        self.assertNotIn(r"\N", mixed_dialogues[0][2])
        self.assertEqual(empty_dialogues, [])
        self.assert_valid_dialogue_timing(mixed_dialogues)


class ArtistVariantsTests(unittest.TestCase):
    def test_artist_variants_splits_comma_to_full_and_primary(self) -> None:
        self.assertEqual(_artist_variants("Lead Singer, Guest Singer"), ["Lead Singer, Guest Singer", "Lead Singer"])

    def test_artist_variants_splits_feat_to_full_and_primary(self) -> None:
        self.assertEqual(_artist_variants("Artist feat. Someone"), ["Artist feat. Someone", "Artist"])

    def test_artist_variants_preserves_single_artist(self) -> None:
        self.assertEqual(_artist_variants("Lead Singer"), ["Lead Singer"])

    def test_artist_variants_keeps_full_credit_before_primary_fallback(self) -> None:
        credit = "Lead Singer, Guest Singer & Third Singer"
        self.assertEqual(_artist_variants(credit), [credit, "Lead Singer"])

    def test_artist_variants_handles_empty_or_none(self) -> None:
        self.assertEqual(_artist_variants(""), [])
        self.assertEqual(_artist_variants(None), [])


class TitleVariantsTests(unittest.TestCase):
    def test_title_variants_with_parentheses(self) -> None:
        self.assertEqual(
            _title_variants("Example Track (Acoustic)"),
            ["Example Track (Acoustic)", "Example Track"],
        )

    def test_title_variants_with_brackets(self) -> None:
        self.assertEqual(
            _title_variants("Song [Official Video]"),
            ["Song [Official Video]", "Song"],
        )

    def test_title_variants_without_brackets_or_parentheses(self) -> None:
        self.assertEqual(_title_variants("Song"), ["Song"])

    def test_title_variants_eliminates_empty_and_handles_edge_cases(self) -> None:
        self.assertEqual(_title_variants("(Official Video)"), ["(Official Video)"])
        self.assertEqual(_title_variants(""), [])
        self.assertEqual(_title_variants(None), [])


class TitleEditionTokensTests(unittest.TestCase):
    def test_title_edition_tokens_extracts_acoustic(self) -> None:
        self.assertEqual(_title_edition_tokens("Example Track (Acoustic)"), {"acoustic"})

    def test_title_edition_tokens_extracts_live(self) -> None:
        self.assertEqual(_title_edition_tokens("Song - Live"), {"live"})

    def test_title_edition_tokens_empty_for_regular_song(self) -> None:
        self.assertEqual(_title_edition_tokens("Song"), set())

    def test_title_edition_tokens_normalizes_acapella(self) -> None:
        self.assertEqual(_title_edition_tokens("Song (A Cappella)"), {"acapella"})
        self.assertEqual(_title_edition_tokens("Song (Acapella)"), {"acapella"})

    def test_title_edition_tokens_handles_none_and_empty(self) -> None:
        self.assertEqual(_title_edition_tokens(None), set())
        self.assertEqual(_title_edition_tokens(""), set())


class LrclibCandidateSafetyTests(unittest.TestCase):
    def test_safe_candidate_accepts_matching_metadata(self) -> None:
        candidate = {
            "id": 100,
            "trackName": "Example Track (Acoustic)",
            "artistName": "Lead Singer",
            "duration": 296.0,
            "syncedLyrics": "[00:10.00] Line",
        }
        self.assertTrue(
            _lrclib_candidate_is_safe(candidate, track="Example Track (Acoustic)", artist="Lead Singer", duration=296)
        )

    def test_rejects_different_artist_even_with_matching_title_and_duration(self) -> None:
        candidate = {
            "id": 101,
            "trackName": "Example Track",
            "artistName": "Completely Different Artist",
            "duration": 296.0,
            "syncedLyrics": "[00:10.00] Line",
        }
        self.assertFalse(
            _lrclib_candidate_is_safe(candidate, track="Example Track", artist="Lead Singer", duration=296)
        )

    def test_rejects_incompatible_explicit_editions(self) -> None:
        candidate = {
            "id": 102,
            "trackName": "Example Track (Live)",
            "artistName": "Lead Singer",
            "duration": 296.0,
            "syncedLyrics": "[00:10.00] Line",
        }
        self.assertFalse(
            _lrclib_candidate_is_safe(candidate, track="Example Track (Acoustic)", artist="Lead Singer", duration=296)
        )

    def test_accepts_missing_edition_with_lower_score_than_matching_edition(self) -> None:
        generic_candidate = {
            "id": 103,
            "trackName": "Example Track",
            "artistName": "Lead Singer",
            "duration": 296.0,
            "syncedLyrics": "[00:10.00] Line",
        }
        acoustic_candidate = {
            "id": 104,
            "trackName": "Example Track (Acoustic)",
            "artistName": "Lead Singer",
            "duration": 296.0,
            "syncedLyrics": "[00:10.00] Line",
        }
        self.assertTrue(
            _lrclib_candidate_is_safe(
                generic_candidate, track="Example Track (Acoustic)", artist="Lead Singer", duration=296
            )
        )
        self.assertTrue(
            _lrclib_candidate_is_safe(
                acoustic_candidate, track="Example Track (Acoustic)", artist="Lead Singer", duration=296
            )
        )
        score_generic = _lrclib_match_score(
            generic_candidate, track="Example Track (Acoustic)", artist="Lead Singer", duration=296
        )
        score_acoustic = _lrclib_match_score(
            acoustic_candidate, track="Example Track (Acoustic)", artist="Lead Singer", duration=296
        )
        self.assertGreater(score_acoustic, score_generic)

    def test_rejects_duration_delta_greater_than_10s(self) -> None:
        candidate = {
            "id": 105,
            "trackName": "Example Track",
            "artistName": "Lead Singer",
            "duration": 315.0,
            "syncedLyrics": "[00:10.00] Line",
        }
        self.assertFalse(
            _lrclib_candidate_is_safe(candidate, track="Example Track", artist="Lead Singer", duration=296)
        )

    def test_accepts_primary_artist_when_source_has_multiple_artists(self) -> None:
        candidate = {
            "id": 106,
            "trackName": "Example Track (Acoustic)",
            "artistName": "Lead Singer",
            "duration": 296.0,
            "syncedLyrics": "[00:10.00] Line",
        }
        self.assertTrue(
            _lrclib_candidate_is_safe(
                candidate, track="Example Track (Acoustic)", artist="Lead Singer, Guest Singer", duration=296
            )
        )


class LrclibFetchTests(unittest.TestCase):
    def test_fetch_lrclib_preserves_forced_id(self) -> None:
        with patch("colab.karaoke_job._lrclib_request") as mock_request:
            mock_request.return_value = {
                "id": 12345,
                "trackName": "Custom Song",
                "plainLyrics": "Hello world",
            }
            result = _fetch_lrclib({}, {"lyrics": {"lrclib_id": 12345}})
            self.assertIsNotNone(result)
            self.assertEqual(result["id"], 12345)
            mock_request.assert_called_once_with("/get/12345")

    def test_fetch_lrclib_tier1_exact_match(self) -> None:
        with patch("colab.karaoke_job._lrclib_request") as mock_request:
            mock_request.return_value = {
                "id": 1,
                "trackName": "Song",
                "artistName": "Artist",
                "albumName": "Album",
                "duration": 200.0,
                "syncedLyrics": "[00:01.00] Line",
            }
            metadata = {"track": "Song", "artist": "Artist", "album": "Album", "duration": 200}
            result = _fetch_lrclib(metadata, {})
            self.assertIsNotNone(result)
            self.assertEqual(result["id"], 1)
            mock_request.assert_called_once()
            self.assertIn("/get?", mock_request.call_args[0][0])
            self.assertIn("album_name=Album", mock_request.call_args[0][0])

    def test_fetch_lrclib_tier2_without_album(self) -> None:
        def side_effect(path: str) -> Any:
            if "album_name" in path:
                raise OSError("HTTP 404")
            return {
                "id": 2,
                "trackName": "Song",
                "artistName": "Artist",
                "duration": 200.0,
                "syncedLyrics": "[00:01.00] Line",
            }

        with patch("colab.karaoke_job._lrclib_request", side_effect=side_effect) as mock_request:
            metadata = {"track": "Song", "artist": "Artist", "album": "Different Album", "duration": 200}
            result = _fetch_lrclib(metadata, {})
            self.assertIsNotNone(result)
            self.assertEqual(result["id"], 2)
            self.assertEqual(mock_request.call_count, 2)

    def test_fetch_lrclib_retries_with_primary_artist_after_full_credit_misses(self) -> None:
        def side_effect(path: str) -> Any:
            if parse_qs(urlsplit(path).query).get("artist_name") == ["Lead Singer, Guest Singer"]:
                raise OSError("HTTP 404")
            if parse_qs(urlsplit(path).query).get("artist_name") == ["Lead Singer"]:
                return {
                    "id": 1234,
                    "trackName": "Example Track (Acoustic)",
                    "artistName": "Lead Singer",
                    "duration": 296.0,
                    "syncedLyrics": "[00:10.00] Line",
                }
            raise OSError("HTTP 404")

        with patch("colab.karaoke_job._lrclib_request", side_effect=side_effect):
            metadata = {
                "track": "Example Track (Acoustic)",
                "artist": "Lead Singer, Guest Singer",
                "album": "Example Track",
                "duration": 296,
                "title": "Example Track (Acoustic)",
            }
            result = _fetch_lrclib(metadata, {})
            self.assertIsNotNone(result)
            self.assertEqual(result["id"], 1234)

    def test_fetch_lrclib_tier4_structured_search(self) -> None:
        def side_effect(path: str) -> Any:
            if path.startswith("/get?"):
                raise OSError("HTTP 404")
            if path.startswith("/search?"):
                return [
                    {
                        "id": 4321,
                        "trackName": "Example Track (Acoustic)",
                        "artistName": "Lead Singer",
                        "duration": 296.0,
                        "syncedLyrics": "[00:10.00] Line",
                    }
                ]
            raise OSError("HTTP 404")

        with patch("colab.karaoke_job._lrclib_request", side_effect=side_effect):
            metadata = {
                "track": "Example Track (Acoustic)",
                "artist": "Lead Singer, Guest Singer",
                "duration": 296,
                "title": "Example Track (Acoustic)",
            }
            result = _fetch_lrclib(metadata, {})
            self.assertIsNotNone(result)
            self.assertEqual(result["id"], 4321)

    def test_fetch_lrclib_tier4_continues_to_search_b_if_search_a_empty(self) -> None:
        def side_effect(path: str) -> Any:
            if path.startswith("/get?"):
                raise OSError("HTTP 404")
            if parse_qs(urlsplit(path).query).get("track_name") == ["Example Track (Acoustic)"]:
                return []
            if parse_qs(urlsplit(path).query).get("track_name") == ["Example Track"]:
                return [
                    {
                        "id": 999,
                        "trackName": "Example Track (Acoustic)",
                        "artistName": "Lead Singer",
                        "duration": 296.0,
                        "syncedLyrics": "[00:10.00] Line",
                    }
                ]
            return []

        with patch("colab.karaoke_job._lrclib_request", side_effect=side_effect):
            metadata = {
                "track": "Example Track (Acoustic)",
                "artist": "Lead Singer",
                "duration": 296,
                "title": "Example Track (Acoustic)",
            }
            result = _fetch_lrclib(metadata, {})
            self.assertIsNotNone(result)
            self.assertEqual(result["id"], 999)

    def test_fetch_lrclib_tier5_fallback_q_search(self) -> None:
        def side_effect(path: str) -> Any:
            if path.startswith("/get?") or "artist_name=" in path:
                return [] if path.startswith("/search?") else None
            if parse_qs(urlsplit(path).query).get("q", [""])[0].startswith("Lead Singer Example Track"):
                return [
                    {
                        "id": 888,
                        "trackName": "Example Track (Acoustic)",
                        "artistName": "Lead Singer",
                        "duration": 296.0,
                        "syncedLyrics": "[00:10.00] Line",
                    }
                ]
            return []

        with patch("colab.karaoke_job._lrclib_request", side_effect=side_effect):
            metadata = {
                "track": "Example Track (Acoustic)",
                "artist": "Lead Singer",
                "duration": 296,
                "title": "Example Track (Acoustic)",
            }
            result = _fetch_lrclib(metadata, {})
            self.assertIsNotNone(result)
            self.assertEqual(result["id"], 888)

    def test_fetch_lrclib_deduplicates_candidates_across_searches(self) -> None:
        def side_effect(path: str) -> Any:
            if path.startswith("/get?"):
                raise OSError("HTTP 404")
            return [
                {
                    "id": 111,
                    "trackName": "Example Track (Acoustic)",
                    "artistName": "Lead Singer",
                    "duration": 296.0,
                    "syncedLyrics": "[00:10.00] Line",
                }
            ]

        with patch("colab.karaoke_job._lrclib_request", side_effect=side_effect):
            metadata = {
                "track": "Example Track (Acoustic)",
                "artist": "Lead Singer",
                "duration": 296,
                "title": "Example Track (Acoustic)",
            }
            result = _fetch_lrclib(metadata, {})
            self.assertIsNotNone(result)
            self.assertEqual(result["id"], 111)

    def test_fetch_lrclib_returns_none_when_no_safe_match(self) -> None:
        def side_effect(path: str) -> Any:
            if path.startswith("/get?"):
                raise OSError("HTTP 404")
            return [
                {
                    "id": 500,
                    "trackName": "Example Track",
                    "artistName": "Completely Different Artist",
                    "duration": 296.0,
                    "syncedLyrics": "[00:10.00] Line",
                }
            ]

        with patch("colab.karaoke_job._lrclib_request", side_effect=side_effect):
            metadata = {
                "track": "Example Track",
                "artist": "Lead Singer",
                "duration": 296,
                "title": "Example Track",
            }
            result = _fetch_lrclib(metadata, {})
            self.assertIsNone(result)


class ParseSyncedLyricsTests(unittest.TestCase):
    def test_parse_synced_lyrics_extracts_timestamps_and_bounds(self) -> None:
        lrc = "[00:01.00] Line one\n[00:05.50] Line two\n[00:10.00] \n[00:20.00] Line three\n[00:25.00] Last line"
        lines = _parse_synced_lyrics(lrc, duration_ms=30000)
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[0], {"text": "Line one", "start_ms": 1000, "end_ms": 5500})
        self.assertEqual(lines[1], {"text": "Line two", "start_ms": 5500, "end_ms": 10000})
        self.assertEqual(lines[2], {"text": "Line three", "start_ms": 20000, "end_ms": 25000})
        self.assertEqual(lines[3], {"text": "Last line", "start_ms": 25000, "end_ms": 30000})

    def test_parse_synced_lyrics_handles_millisecond_timestamps(self) -> None:
        lrc = "[00:02.500] Precise line\n[00:08.125] Next precise line"
        lines = _parse_synced_lyrics(lrc, duration_ms=20000)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], {"text": "Precise line", "start_ms": 2500, "end_ms": 8125})
        self.assertEqual(lines[1], {"text": "Next precise line", "start_ms": 8125, "end_ms": 16125})

    def test_parse_synced_lyrics_ignores_header_metadata(self) -> None:
        lrc = "[ar:Artist]\n[ti:Title]\n[00:03.00] Actual lyrics"
        lines = _parse_synced_lyrics(lrc, duration_ms=10000)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0], {"text": "Actual lyrics", "start_ms": 3000, "end_ms": 10000})


class LyricsDocumentFromRecordTests(unittest.TestCase):
    def test_lyricsfile_empty_lines_falls_back_to_synced_lyrics(self) -> None:
        record = {
            "trackName": "Song",
            "artistName": "Artist",
            "lyricsfile": "version: '1.0'\nlines: []\n",
            "syncedLyrics": "[00:01.00] Synced line 1\n[00:05.00] Synced line 2",
        }
        metadata = {"title": "Song", "duration": 100}
        config = {"language": "en"}
        document = _lyrics_document_from_record(record, metadata, config)
        self.assertEqual(len(document["lines"]), 2)
        self.assertEqual(document["lines"][0]["text"], "Synced line 1")
        self.assertEqual(document["lines"][0]["start_ms"], 1000)
        self.assertEqual(document["lines"][0]["end_ms"], 5000)
        self.assertEqual(document["lines"][1]["text"], "Synced line 2")
        self.assertEqual(document["lines"][1]["start_ms"], 5000)
        self.assertEqual(document["lines"][1]["end_ms"], 13000)

    def test_lyricsfile_empty_lines_falls_back_to_plain_lyrics(self) -> None:
        record = {
            "trackName": "Song",
            "artistName": "Artist",
            "lyricsfile": "version: '1.0'\nlines: []\n",
            "plainLyrics": "Plain line 1\nPlain line 2",
        }
        metadata = {"title": "Song", "duration": 100}
        config = {"language": "en"}
        document = _lyrics_document_from_record(record, metadata, config)
        self.assertEqual(len(document["lines"]), 2)
        self.assertEqual(document["lines"][0]["text"], "Plain line 1")

    def test_no_usable_lyrics_raises_value_error(self) -> None:
        record = {
            "trackName": "Song",
            "artistName": "Artist",
            "lyricsfile": "version: '1.0'\nlines: []\n",
            "syncedLyrics": "",
            "plainLyrics": "",
        }
        metadata = {"title": "Song", "duration": 100}
        config = {"language": "en"}
        with self.assertRaises(ValueError):
            _lyrics_document_from_record(record, metadata, config)

    def test_valid_lyricsfile_with_lines_is_used(self) -> None:
        record = {
            "trackName": "Song",
            "artistName": "Artist",
            "lyricsfile": "version: '1.0'\nlines:\n  - text: Valid line\n    start_ms: 1000\n    end_ms: 2000\n",
            "syncedLyrics": "[00:01.00] Other synced",
        }
        metadata = {"title": "Song", "duration": 100}
        config = {"language": "en"}
        document = _lyrics_document_from_record(record, metadata, config)
        self.assertEqual(len(document["lines"]), 1)
        self.assertEqual(document["lines"][0]["text"], "Valid line")


class AlignKnownLyricsTests(unittest.TestCase):
    def test_global_alignment_preserves_continuous_word_timestamps(self) -> None:
        import sys
        from unittest.mock import MagicMock

        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.float32 = "float32"
        mock_torch.float16 = "float16"

        mock_hf = MagicMock()
        mock_hf.snapshot_download.return_value = "/tmp/model"

        mock_aligner = MagicMock()
        mock_model = MagicMock()
        mock_model.dtype = "float32"
        mock_model.device = "cpu"
        mock_tokenizer = MagicMock()
        mock_aligner.load_alignment_model.return_value = (mock_model, mock_tokenizer)

        # Mock 1D waveform: 160,000 samples (10s at 16kHz)
        mock_waveform = MagicMock()
        mock_waveform.shape = (160000,)
        mock_waveform.__getitem__.return_value = mock_waveform
        mock_aligner.load_audio.return_value = mock_waveform

        mock_aligner.generate_emissions.return_value = (MagicMock(), 0.02)
        mock_aligner.preprocess_text.return_value = (MagicMock(), MagicMock())
        mock_aligner.get_alignments.return_value = (MagicMock(), MagicMock(), MagicMock())
        mock_aligner.get_spans.return_value = MagicMock()

        # Global continuous alignment results: words at 0.5s and 1.0s
        mock_aligner.postprocess_results.return_value = [
            {"start": 0.5, "end": 0.9, "score": 0.0},
            {"start": 1.0, "end": 1.4, "score": 0.0},
        ]

        document = {
            "metadata": {"title": "Test", "duration_ms": 10000},
            "lines": [
                {
                    "text": "Hello world",
                    "start_ms": 500,
                    "end_ms": 2000,
                }
            ],
        }
        config = {"language": "en"}

        with patch.dict(
            sys.modules,
            {
                "torch": mock_torch,
                "huggingface_hub": mock_hf,
                "ctc_forced_aligner": mock_aligner,
            },
        ):
            lyrics, words = _align_known_lyrics(Path("/tmp/vocals.wav"), document, config)

        self.assertEqual(len(lyrics["lines"]), 1)
        line = lyrics["lines"][0]
        self.assertEqual(len(line["words"]), 2)
        self.assertEqual(line["words"][0]["text"], "Hello ")
        self.assertEqual(line["words"][0]["start_ms"], 500)
        self.assertEqual(line["words"][0]["end_ms"], 900)
        self.assertEqual(line["words"][1]["text"], "world")
        self.assertEqual(line["words"][1]["start_ms"], 1000)
        self.assertEqual(line["words"][1]["end_ms"], 1400)

    def test_macro_section_alignment_activates_on_global_anomaly(self) -> None:
        import sys
        from unittest.mock import MagicMock

        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.float32 = "float32"
        mock_torch.float16 = "float16"

        mock_hf = MagicMock()
        mock_hf.snapshot_download.return_value = "/tmp/model"

        mock_aligner = MagicMock()
        mock_model = MagicMock()
        mock_model.dtype = "float32"
        mock_model.device = "cpu"
        mock_tokenizer = MagicMock()
        mock_aligner.load_alignment_model.return_value = (mock_model, mock_tokenizer)

        mock_waveform = MagicMock()
        mock_waveform.shape = (480000,)  # 30s audio
        mock_waveform.__getitem__.return_value = mock_waveform
        mock_aligner.load_audio.return_value = mock_waveform

        mock_aligner.generate_emissions.return_value = (MagicMock(), 0.02)
        mock_aligner.preprocess_text.return_value = (MagicMock(), MagicMock())
        mock_aligner.get_alignments.return_value = (MagicMock(), MagicMock(), MagicMock())
        mock_aligner.get_spans.return_value = MagicMock()

        # Call 1 (Global): returns severely collapsed result (drift > 12s with near-zero confidence)
        # Call 2 (Tier 2 Macro section 1): returns healthy result
        # Call 3 (Tier 2 Macro section 2): returns healthy result
        mock_aligner.postprocess_results.side_effect = [
            # Call 1: Global fails because line 2 drifts by 17 seconds (placed at 35s instead of 18s) with score -10
            [
                {"start": 1.0, "end": 1.4, "score": 0.0},
                {"start": 1.5, "end": 1.9, "score": 0.0},
                {"start": 35.0, "end": 35.4, "score": -10.0},
                {"start": 35.5, "end": 35.9, "score": -10.0},
            ],
            # Call 2: Macro section 1 (offset: max(0, 1.0 - 1.5) = 0.0s)
            [
                {"start": 1.0, "end": 1.4, "score": 0.0},
                {"start": 1.5, "end": 1.9, "score": 0.0},
            ],
            # Call 3: Macro section 2 (offset: 18.0 - 1.5 = 16.5s)
            [
                {"start": 1.5, "end": 1.9, "score": 0.0},
                {"start": 2.0, "end": 2.4, "score": 0.0},
            ],
        ]

        document = {
            "metadata": {"title": "Test", "duration_ms": 30000},
            "lines": [
                {"text": "Verse line", "start_ms": 1000, "end_ms": 3000},
                # 15s instrumental gap between 3s and 18s
                {"text": "Chorus line", "start_ms": 18000, "end_ms": 20000},
            ],
        }
        config = {"language": "en"}

        with patch.dict(
            sys.modules,
            {
                "torch": mock_torch,
                "huggingface_hub": mock_hf,
                "ctc_forced_aligner": mock_aligner,
            },
        ):
            lyrics, words = _align_known_lyrics(Path("/tmp/vocals.wav"), document, config)

        self.assertEqual(len(lyrics["lines"]), 2)
        # Macro section 1: offset is 0.0s -> word 0 at 1000ms
        self.assertEqual(lyrics["lines"][0]["words"][0]["start_ms"], 1000)
        # Macro section 2: offset is 16.5s -> word 0 at 1.5 + 16.5 = 18.0s = 18000ms
        self.assertEqual(lyrics["lines"][1]["words"][0]["start_ms"], 18000)

    def test_segmented_alignment_supports_2d_waveform(self) -> None:
        import sys
        from unittest.mock import MagicMock

        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.float32 = "float32"
        mock_torch.float16 = "float16"

        mock_hf = MagicMock()
        mock_hf.snapshot_download.return_value = "/tmp/model"

        mock_aligner = MagicMock()
        mock_model = MagicMock()
        mock_model.dtype = "float32"
        mock_model.device = "cpu"
        mock_tokenizer = MagicMock()
        mock_aligner.load_alignment_model.return_value = (mock_model, mock_tokenizer)

        # Mock 2D waveform: (1, 160000)
        mock_waveform = MagicMock()
        mock_waveform.shape = (1, 160000)
        mock_waveform.__getitem__.return_value = mock_waveform
        mock_aligner.load_audio.return_value = mock_waveform

        mock_aligner.generate_emissions.return_value = (MagicMock(), 0.02)
        mock_aligner.preprocess_text.return_value = (MagicMock(), MagicMock())
        mock_aligner.get_alignments.return_value = (MagicMock(), MagicMock(), MagicMock())
        mock_aligner.get_spans.return_value = MagicMock()
        mock_aligner.postprocess_results.return_value = [
            {"start": 0.5, "end": 0.9, "score": 0.0},
        ]

        document = {
            "metadata": {"title": "Test", "duration_ms": 10000},
            "lines": [{"text": "Hello", "start_ms": 500, "end_ms": 2000}],
        }
        config = {"language": "en"}

        with patch.dict(
            sys.modules,
            {
                "torch": mock_torch,
                "huggingface_hub": mock_hf,
                "ctc_forced_aligner": mock_aligner,
            },
        ):
            lyrics, words = _align_known_lyrics(Path("/tmp/vocals.wav"), document, config)

        self.assertEqual(len(lyrics["lines"]), 1)
        self.assertEqual(lyrics["lines"][0]["words"][0]["text"], "Hello")

    def test_is_alignment_healthy_validation(self) -> None:
        # Empty lines
        self.assertFalse(_is_alignment_healthy([]))

        # Invalid line without words
        self.assertFalse(_is_alignment_healthy([{"text": "hi", "start_ms": 100, "end_ms": 200, "words": []}]))

        # Invalid timing: end <= start
        bad_timing_line = {
            "text": "hi",
            "start_ms": 500,
            "end_ms": 400,
            "words": [{"text": "hi", "start_ms": 500, "end_ms": 400, "confidence": 0.9}],
        }
        self.assertFalse(_is_alignment_healthy([bad_timing_line]))

        # Normal healthy line
        healthy_line = {
            "text": "Hello world",
            "start_ms": 1000,
            "end_ms": 2500,
            "words": [
                {"text": "Hello ", "start_ms": 1000, "end_ms": 1700, "confidence": 0.85},
                {"text": "world", "start_ms": 1750, "end_ms": 2500, "confidence": 0.90},
            ],
        }
        self.assertTrue(_is_alignment_healthy([healthy_line]))

        # Squashed line anomaly: 3 words in 100ms with low confidence
        squashed_line = {
            "text": "one two three",
            "start_ms": 1000,
            "end_ms": 1100,
            "words": [
                {"text": "one ", "start_ms": 1000, "end_ms": 1030, "confidence": 0.01},
                {"text": "two ", "start_ms": 1030, "end_ms": 1060, "confidence": 0.01},
                {"text": "three", "start_ms": 1060, "end_ms": 1100, "confidence": 0.01},
            ],
        }
        self.assertFalse(_is_alignment_healthy([squashed_line]))

        # Reference drift anomaly: drifting by > 30s
        raw_ref = [{"text": "Verse", "start_ms": 1000, "end_ms": 3000}]
        drifting_line = {
            "text": "Verse",
            "start_ms": 35000,
            "end_ms": 37000,
            "words": [
                {"text": "Verse", "start_ms": 35000, "end_ms": 37000, "confidence": 0.8},
            ],
        }
        self.assertFalse(_is_alignment_healthy([drifting_line], raw_ref))

    def test_group_lines_into_macro_sections(self) -> None:
        self.assertEqual(_group_lines_into_macro_sections([]), [])

        lines = [
            ({"start_ms": 1000, "end_ms": 3000, "text": "Line 1"}, [{"text": "Line"}, {"text": "1"}]),
            ({"start_ms": 3500, "end_ms": 5500, "text": "Line 2"}, [{"text": "Line"}, {"text": "2"}]),
            # Gap of 14.5s (20000 - 5500)
            ({"start_ms": 20000, "end_ms": 23000, "text": "Line 3"}, [{"text": "Line"}, {"text": "3"}]),
        ]
        sections = _group_lines_into_macro_sections(lines, gap_threshold_sec=6.0)
        self.assertEqual(len(sections), 2)
        self.assertEqual(len(sections[0]), 2)
        self.assertEqual(sections[0][0][0]["text"], "Line 1")
        self.assertEqual(sections[0][1][0]["text"], "Line 2")
        self.assertEqual(len(sections[1]), 1)
        self.assertEqual(sections[1][0][0]["text"], "Line 3")


class RuntimeBootstrapTests(unittest.TestCase):


    def test_ensure_playwright_uses_uv_when_available(self) -> None:
        import sys

        from colab.karaoke_job import PLAYWRIGHT_PACKAGE, _ensure_playwright

        with (
            patch("importlib.util.find_spec", return_value=None),
            patch("shutil.which", side_effect=lambda cmd: "/usr/bin/uv" if cmd == "uv" else None),
            patch("colab.karaoke_job._run_installer") as mock_installer,
        ):
            _ensure_playwright()
            self.assertEqual(mock_installer.call_count, 2)
            self.assertEqual(
                mock_installer.call_args_list[0].args[0],
                ["uv", "pip", "install", "--system", PLAYWRIGHT_PACKAGE],
            )
            self.assertEqual(
                mock_installer.call_args_list[1].args[0],
                [sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"],
            )

    def test_ensure_playwright_falls_back_to_pip_when_no_uv(self) -> None:
        import sys

        from colab.karaoke_job import PLAYWRIGHT_PACKAGE, _ensure_playwright

        with (
            patch("importlib.util.find_spec", return_value=None),
            patch("shutil.which", return_value=None),
            patch("colab.karaoke_job._run_installer") as mock_installer,
        ):
            _ensure_playwright()
            self.assertEqual(mock_installer.call_count, 2)
            self.assertEqual(
                mock_installer.call_args_list[0].args[0],
                [sys.executable, "-m", "pip", "install", PLAYWRIGHT_PACKAGE],
            )
            self.assertEqual(
                mock_installer.call_args_list[1].args[0],
                [sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"],
            )

    def test_ensure_playwright_skips_package_install_when_already_present(self) -> None:
        import sys
        from unittest.mock import MagicMock

        from colab.karaoke_job import _ensure_playwright

        with (
            patch("importlib.util.find_spec", return_value=MagicMock()),
            patch("colab.karaoke_job._run_installer") as mock_installer,
        ):
            _ensure_playwright()
            self.assertEqual(mock_installer.call_count, 1)
            self.assertEqual(
                mock_installer.call_args_list[0].args[0],
                [sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"],
            )


if __name__ == "__main__":
    unittest.main()
