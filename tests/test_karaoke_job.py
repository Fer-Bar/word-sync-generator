import re
import tempfile
import unittest
from pathlib import Path
from typing import Any

from colab.karaoke_job import _build_lyric_pages, _group_words, _write_ass

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
        duration_pages = _build_lyric_pages(
            [_line(0, 0.0, 6.0), _line(1, 6.1, 12.0), _line(2, 12.1, 15.1)]
        )

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


if __name__ == "__main__":
    unittest.main()
