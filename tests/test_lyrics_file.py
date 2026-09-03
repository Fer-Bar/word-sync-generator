import unittest

from karaoke_app.lyrics_file import sanitize_lyrics_lines, validate_lyrics_file


class LyricsFileSanitizationTests(unittest.TestCase):
    def test_fixes_zero_duration_words(self) -> None:
        lines = [
            {
                "text": "give me your 9:30 (9:30)",
                "agent": "v1",
                "words": [
                    {"text": "give ", "start_ms": 1000, "end_ms": 1200, "agent": "v1"},
                    {"text": "me ", "start_ms": 1200, "end_ms": 1300, "agent": "v1"},
                    {"text": "your ", "start_ms": 1300, "end_ms": 1500, "agent": "v1"},
                    {"text": "9:30 ", "start_ms": 1500, "end_ms": 1500, "agent": "v1"},
                    {
                        "text": "9:30",
                        "start_ms": 1500,
                        "end_ms": 1500,
                        "agent": "v1",
                        "isBackground": True,
                    },
                ],
            }
        ]

        sanitized = sanitize_lyrics_lines(lines, min_word_duration_ms=20)
        doc = {"version": "1.0", "metadata": {"title": "Song"}, "lines": sanitized}
        validated = validate_lyrics_file(doc, require_words=True)

        self.assertEqual(len(validated["lines"]), 1)
        words = validated["lines"][0]["words"]
        self.assertEqual(len(words), 5)
        for word in words:
            self.assertGreater(word["end_ms"], word["start_ms"])
        self.assertEqual(validated["lines"][0]["agent"], "v1")
        self.assertTrue(words[-1]["isBackground"])
        self.assertEqual(words[-1]["start_ms"], words[-2]["start_ms"])

    def test_preserves_silence_between_words(self) -> None:
        lines = [
            {
                "text": "one two",
                "words": [
                    {"text": "one ", "start_ms": 1000, "end_ms": 1200},
                    {"text": "two", "start_ms": 1800, "end_ms": 2000},
                ],
            }
        ]

        sanitized = sanitize_lyrics_lines(lines)

        self.assertEqual(sanitized[0]["words"][0]["end_ms"], 1200)
        self.assertEqual(sanitized[0]["words"][1]["start_ms"], 1800)

    def test_accepts_interleaved_main_and_background_words(self) -> None:
        raw_doc = {
            "version": "1.0",
            "metadata": {"title": "Song"},
            "lines": [
                {
                    "text": "(I'm dancing) Dancing with you",
                    "start_ms": 1000,
                    "end_ms": 2600,
                    "agent": "v1",
                    "words": [
                        {
                            "text": "I'm ",
                            "start_ms": 1000,
                            "end_ms": 1500,
                            "agent": "v1",
                            "isBackground": True,
                        },
                        {"text": "Dancing ", "start_ms": 1300, "end_ms": 1900, "agent": "v1"},
                        {
                            "text": "dancing",
                            "start_ms": 1500,
                            "end_ms": 2100,
                            "agent": "v1",
                            "isBackground": True,
                        },
                        {"text": "with ", "start_ms": 1900, "end_ms": 2200, "agent": "v1"},
                        {"text": "you", "start_ms": 2200, "end_ms": 2600, "agent": "v1"},
                    ],
                }
            ],
        }

        validated = validate_lyrics_file(raw_doc)

        self.assertEqual(validated["lines"][0]["text"], "(I'm dancing) Dancing with you")
        self.assertTrue(validated["lines"][0]["words"][0]["isBackground"])

    def test_resolves_word_overlaps_within_line(self) -> None:
        lines = [
            {
                "text": "one two three",
                "words": [
                    {"text": "one ", "start_ms": 1000, "end_ms": 1500},
                    {"text": "two ", "start_ms": 1400, "end_ms": 1800},  # overlaps 'one'
                    {"text": "three", "start_ms": 1700, "end_ms": 2000},  # overlaps 'two'
                ],
            }
        ]

        sanitized = sanitize_lyrics_lines(lines, min_word_duration_ms=20)
        doc = {"version": "1.0", "metadata": {"title": "Song"}, "lines": sanitized}
        validated = validate_lyrics_file(doc, require_words=True)

        words = validated["lines"][0]["words"]
        self.assertEqual(words[0]["end_ms"], 1400)
        self.assertEqual(words[1]["start_ms"], 1400)
        self.assertEqual(words[1]["end_ms"], 1700)
        self.assertEqual(words[2]["start_ms"], 1700)
        self.assertEqual(words[2]["end_ms"], 2000)

    def test_resolves_adjacent_line_overlaps_by_trimming(self) -> None:
        lines = [
            {
                "text": "Line one",
                "words": [
                    {"text": "Line ", "start_ms": 1000, "end_ms": 1500},
                    {"text": "one", "start_ms": 1500, "end_ms": 2000},
                ],
            },
            {
                "text": "Line two",
                "words": [
                    {"text": "Line ", "start_ms": 1900, "end_ms": 2200},  # overlaps Line one
                    {"text": "two", "start_ms": 2200, "end_ms": 2500},
                ],
            },
        ]

        sanitized = sanitize_lyrics_lines(lines, min_word_duration_ms=20)
        doc = {"version": "1.0", "metadata": {"title": "Song"}, "lines": sanitized}
        validated = validate_lyrics_file(doc, require_words=True)

        self.assertEqual(validated["lines"][0]["end_ms"], 1900)
        self.assertEqual(validated["lines"][0]["words"][-1]["end_ms"], 1900)
        self.assertEqual(validated["lines"][1]["start_ms"], 1900)

    def test_resolves_adjacent_line_overlaps_by_shifting_when_cannot_trim(self) -> None:
        lines = [
            {
                "text": "Line one",
                "words": [
                    {"text": "Line ", "start_ms": 1000, "end_ms": 1020},
                    {"text": "one", "start_ms": 1020, "end_ms": 1040},
                ],
            },
            {
                "text": "Line two",
                "words": [
                    {"text": "Line ", "start_ms": 1010, "end_ms": 1200},  # overlaps and cannot trim
                    {"text": "two", "start_ms": 1200, "end_ms": 1400},
                ],
            },
        ]

        sanitized = sanitize_lyrics_lines(lines, min_word_duration_ms=20)
        doc = {"version": "1.0", "metadata": {"title": "Song"}, "lines": sanitized}
        validated = validate_lyrics_file(doc, require_words=True)

        self.assertEqual(validated["lines"][0]["end_ms"], 1040)
        self.assertEqual(validated["lines"][1]["start_ms"], 1040)
        self.assertEqual(validated["lines"][1]["words"][0]["start_ms"], 1040)

    def test_fixes_negative_duration_words(self) -> None:
        lines = [
            {
                "text": "inverted timestamps",
                "words": [
                    {"text": "inverted ", "start_ms": 1000, "end_ms": 800},
                    {"text": "timestamps", "start_ms": 800, "end_ms": 700},
                ],
            }
        ]

        sanitized = sanitize_lyrics_lines(lines, min_word_duration_ms=20)
        doc = {"version": "1.0", "metadata": {"title": "Song"}, "lines": sanitized}
        validated = validate_lyrics_file(doc, require_words=True)

        words = validated["lines"][0]["words"]
        self.assertGreater(words[0]["end_ms"], words[0]["start_ms"])
        self.assertGreater(words[1]["end_ms"], words[1]["start_ms"])
        self.assertGreaterEqual(words[1]["start_ms"], words[0]["end_ms"])

    def test_validation_reports_positive_duration_error(self) -> None:
        raw_doc = {
            "version": "1.0",
            "metadata": {"title": "Song"},
            "lines": [
                {
                    "text": "invalid",
                    "start_ms": 1000,
                    "end_ms": 2000,
                    "words": [{"text": "invalid", "start_ms": 1000, "end_ms": 1000}],
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "must have a positive duration"):
            validate_lyrics_file(raw_doc, require_words=True)


if __name__ == "__main__":
    unittest.main()
