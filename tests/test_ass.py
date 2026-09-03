import re
import unittest

from karaoke_app.ass import generate_ass


class AssLayoutTests(unittest.TestCase):
    def test_long_lines_wrap_within_horizontal_margins(self) -> None:
        transcript = {
            "segments": [
                {
                    "start": 0.0,
                    "end": 2.0,
                    "text": "This lyric line is intentionally long enough to require automatic wrapping",
                    "words": [
                        {
                            "start": 0.0,
                            "end": 2.0,
                            "text": "This lyric line is intentionally long enough to require automatic wrapping",
                        }
                    ],
                }
            ]
        }

        content = generate_ass(transcript, {"width": 1920, "height": 1080, "fps": 24})

        self.assertIn("WrapStyle: 1", content)
        self.assertIn("1,4,1,5,70,70,70,1", content)
        self.assertNotIn(r"\move(", content)

    def test_karaoke_scrolls_long_line_during_its_word_timing(self) -> None:
        transcript = {
            "segments": [
                {
                    "start": 1.0,
                    "end": 3.0,
                    "text": "This lyric line keeps moving horizontally because it is much wider than the video",
                    "words": [
                        {
                            "start": 1.0,
                            "end": 3.0,
                            "text": "This lyric line keeps moving horizontally because it is much wider than the video",
                        }
                    ],
                }
            ]
        }

        content = generate_ass(
            transcript,
            {"width": 1920, "height": 1080, "fps": 24},
            scroll_long_lines=True,
        )

        self.assertIn(r"{\an4\q2\clip(70,0,1850,1080)", content)
        self.assertRegex(content, re.compile(r"\\move\(70,540,-?\d+,540,350,2350\)"))

    def test_karaoke_keeps_short_line_centered(self) -> None:
        transcript = {
            "segments": [
                {
                    "start": 0.0,
                    "end": 1.0,
                    "text": "Short line",
                    "words": [{"start": 0.0, "end": 1.0, "text": "Short line"}],
                }
            ]
        }

        content = generate_ass(
            transcript,
            {"width": 1920, "height": 1080, "fps": 24},
            scroll_long_lines=True,
        )

        self.assertIn(r"{\an5\pos(960,540)}", content)
        self.assertNotIn(r"\move(", content)


if __name__ == "__main__":
    unittest.main()
