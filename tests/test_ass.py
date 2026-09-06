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
        self.assertIn(r"{\an5\pos(960,540)", content)

    def test_teleprompter_vertical_scrolling_across_lines(self) -> None:
        transcript = {
            "segments": [
                {
                    "start": 1.0,
                    "end": 3.0,
                    "text": "First line of the song",
                    "words": [{"start": 1.0, "end": 3.0, "text": "First line of the song"}],
                },
                {
                    "start": 3.2,
                    "end": 5.0,
                    "text": "Second line of the song",
                    "words": [{"start": 3.2, "end": 5.0, "text": "Second line of the song"}],
                },
            ]
        }

        content = generate_ass(transcript, {"width": 1920, "height": 1080, "fps": 24})

        # Line 1 active at center
        self.assertIn(r"{\an5\pos(960,540)\fad(150,0)}{\k35}{\kf200}First line of the song", content)
        # Line 2 upcoming preview at bottom slot (Y=691) with unsung color override (\1c&HFFFFFF&)
        self.assertIn(r"{\an5\pos(960,691)\alpha&H80&\1c&HFFFFFF&\fad(150,0)}Second line of the song", content)
        # Synchronized transition during the 20cs (200ms) gap from 3.00 to 3.20:
        # Line 1 glides up to top slot (Y=389) over 200ms
        self.assertIn(r"\move(960,540,960,389,0,200)\t(0,200,\alpha&H80&)", content)
        # Line 2 glides up to center slot (Y=540) over the exact same 200ms
        self.assertIn(r"\move(960,691,960,540,0,200)\t(0,200,\alpha&H00&)", content)

    def test_teleprompter_large_gap_glide_synchrony(self) -> None:
        """Verify lines with ample gap (>0.35s) glide smoothly over nominal slide duration (350ms)."""
        transcript = {
            "segments": [
                {
                    "start": 1.0,
                    "end": 3.0,
                    "text": "First line",
                    "words": [{"start": 1.0, "end": 3.0, "text": "First line"}],
                },
                {
                    "start": 4.0,
                    "end": 6.0,
                    "text": "Second line",
                    "words": [{"start": 4.0, "end": 6.0, "text": "Second line"}],
                },
            ]
        }

        content = generate_ass(transcript, {"width": 1920, "height": 1080, "fps": 24})

        # Gap is 1.0s (> 0.35s nominal slide). Transition happens at [3.65, 4.00] (duration 350ms):
        self.assertIn(
            r"Dialogue: 0,0:00:03.65,0:00:04.85,Default,,0,0,0,,"
            r"{\an5\move(960,540,960,389,0,350)\t(0,350,\alpha&H80&)\fad(0,150)}First line",
            content,
        )
        self.assertIn(
            r"Dialogue: 1,0:00:03.65,0:00:06.00,Default,,0,0,0,,"
            r"{\an5\move(960,691,960,540,0,350)\t(0,350,\alpha&H00&)}{\k35}{\kf200}Second line",
            content,
        )

    def test_consecutive_singers_receive_distinct_styles(self) -> None:
        """Verify verse 1 (Singer 1) and verse 2 (Singer 2) receive separate ASS styles with respective colors."""
        from karaoke_app.style import StyleConfig

        transcript = {
            "segments": [
                {
                    "start": 10.0,
                    "end": 30.0,
                    "text": "First singer line from 10 to 30",
                    "agent": "v1",
                    "words": [
                        {"start": 10.0, "end": 20.0, "text": "First singer ", "agent": "v1"},
                        {"start": 20.0, "end": 30.0, "text": "line", "agent": "v1"},
                    ],
                },
                {
                    "start": 40.0,
                    "end": 60.0,
                    "text": "Second singer line from 40 to 60",
                    "agent": "v2",
                    "words": [
                        {"start": 40.0, "end": 50.0, "text": "Second singer ", "agent": "v2"},
                        {"start": 50.0, "end": 60.0, "text": "line", "agent": "v2"},
                    ],
                },
            ]
        }
        style = StyleConfig.from_dict(
            {
                "agent_colors": {
                    "v1": {"primary_color": "#FFD700", "highlight_color": "#FFFFFF"},
                    "v2": {"primary_color": "#00D7FF", "highlight_color": "#FFFFFF"},
                }
            },
            height=1080,
        )

        content = generate_ass(transcript, {"width": 1920, "height": 1080, "fps": 24}, style=style)

        self.assertIn("Style: Agent_v1,DejaVu Sans,64,&H0000D7FF,&H00FFFFFF,", content)
        self.assertIn("Style: Agent_v2,DejaVu Sans,64,&H00FFD700,&H00FFFFFF,", content)
        self.assertIn("Dialogue: 1,0:00:09.65,0:00:30.00,Agent_v1,v1,", content)
        self.assertIn("Dialogue: 1,0:00:39.65,0:01:00.00,Agent_v2,v2,", content)

    def test_simultaneous_main_and_background_vocals(self) -> None:
        """Verify simultaneous main and background vocal lines produce distinct dialogue lanes and styling."""
        transcript = {
            "segments": [
                {
                    "start": 70.0,
                    "end": 75.0,
                    "text": "There is noooo",
                    "agent": "v1",
                    "words": [
                        {"start": 70.0, "end": 75.0, "text": "There is noooo", "agent": "v1"},
                    ],
                },
                {
                    "start": 71.0,
                    "end": 75.0,
                    "text": "no no no",
                    "agent": "v2",
                    "isBackground": True,
                    "words": [
                        {"start": 71.0, "end": 73.0, "text": "no ", "agent": "v2", "isBackground": True},
                        {"start": 73.0, "end": 75.0, "text": "no no", "agent": "v2", "isBackground": True},
                    ],
                },
            ]
        }

        content = generate_ass(transcript, {"width": 1920, "height": 1080, "fps": 24})

        self.assertIn("Style: Agent_v1,", content)
        self.assertIn("Style: Agent_v2_bg,DejaVu Sans,54,", content)
        self.assertIn("(no ", content)
        self.assertIn("no no)", content)
        self.assertIn("Agent_v2_bg", content)

    def test_lyrics_mode_static_pages_with_coros_at_bottom(self) -> None:
        """Verify lyrics mode creates static pages without move, with coros at the bottom and distinct color."""
        from karaoke_app.style import StyleConfig

        transcript = {
            "segments": [
                {
                    "start": 10.0,
                    "end": 14.0,
                    "text": "Main lead vocal line",
                    "agent": "v1",
                    "words": [
                        {"start": 10.0, "end": 14.0, "text": "Main lead vocal line", "agent": "v1"},
                    ],
                },
                {
                    "start": 10.5,
                    "end": 14.0,
                    "text": "Backing chorus vocal",
                    "agent": "v2",
                    "isBackground": True,
                    "words": [
                        {
                            "start": 10.5,
                            "end": 14.0,
                            "text": "Backing chorus vocal",
                            "agent": "v2",
                            "isBackground": True,
                        },
                    ],
                },
            ]
        }
        style = StyleConfig.from_dict(
            {
                "primary_color": "#FFD700",
                "coros_color": "#00E5FF",
            },
            height=1080,
        )

        content = generate_ass(transcript, {"width": 1920, "height": 1080, "fps": 24}, style=style, mode="lyrics")

        # No teleprompter \move tags in lyrics mode
        self.assertNotIn(r"\move(", content)
        # Both lines have fade
        self.assertIn(r"\fad(150,150)", content)
        # Lead vocal is positioned higher (y=497) than coro vocal (y=583)
        self.assertIn(r"{\an5\pos(960,497)\fad(150,150)}", content)
        self.assertIn(r"{\an5\pos(960,583)\fad(150,150)}", content)
        # Coro text is parenthesized
        self.assertIn("(Backing chorus vocal)", content)
        # Coro style has coros_color (&H00FFE500 in BGR)
        self.assertIn("Style: Agent_v2_bg,DejaVu Sans,54,&H00FFE500,&H00FFFFFF,", content)
        # Lead style has primary_color (&H0000D7FF in BGR)
        self.assertIn("Style: Agent_v1,DejaVu Sans,64,&H0000D7FF,&H00FFFFFF,", content)

    def test_teleprompter_zero_gap_collision_avoidance(self) -> None:
        """Verify back-to-back lines with 0s gap execute synchronized moves without overlapping."""
        transcript = {
            "segments": [
                {
                    "start": 1.0,
                    "end": 2.0,
                    "text": "Fast line one",
                    "words": [{"start": 1.0, "end": 2.0, "text": "Fast line one"}],
                },
                {
                    "start": 2.0,
                    "end": 3.0,
                    "text": "Fast line two",
                    "words": [{"start": 2.0, "end": 3.0, "text": "Fast line two"}],
                },
            ]
        }

        content = generate_ass(transcript, {"width": 1920, "height": 1080, "fps": 24})

        # Transition happens at 2.00 - 0.25 = 1.75 with 250ms duration (dur=25):
        # Line 1 moves Center->Top from 1.75 to 2.00
        self.assertIn(
            r"Dialogue: 0,0:00:01.75,0:00:02.95,Default,,0,0,0,,"
            r"{\an5\move(960,540,960,389,0,250)\t(0,250,\alpha&H80&)\fad(0,150)}Fast line one",
            content,
        )
        # Line 2 moves Bottom->Center from 1.75 to 2.00
        self.assertIn(
            r"Dialogue: 1,0:00:01.75,0:00:03.00,Default,,0,0,0,,"
            r"{\an5\move(960,691,960,540,0,250)\t(0,250,\alpha&H00&)}{\k25}{\kf100}Fast line two",
            content,
        )

    def test_teleprompter_preview_uses_agent_unsung_color(self) -> None:
        """Verify that preview lines inherit the custom unsung (highlight) color of the upcoming agent."""
        from karaoke_app.style import StyleConfig

        transcript = {
            "segments": [
                {
                    "start": 1.0,
                    "end": 3.0,
                    "text": "Singer one starts",
                    "agent": "v1",
                    "words": [{"start": 1.0, "end": 3.0, "text": "Singer one starts", "agent": "v1"}],
                },
                {
                    "start": 3.2,
                    "end": 5.0,
                    "text": "Singer two upcoming",
                    "agent": "v2",
                    "words": [{"start": 3.2, "end": 5.0, "text": "Singer two upcoming", "agent": "v2"}],
                },
            ]
        }
        # v2 has custom unsung color (highlight_color) = #00E5FF (Cyan: R=00, G=E5, B=FF -> ASS BGR: FFE500)
        style = StyleConfig.from_dict(
            {
                "agent_colors": {
                    "v1": {"primary_color": "#FFD700", "highlight_color": "#FFFFFF"},
                    "v2": {"primary_color": "#FF00AA", "highlight_color": "#00E5FF"},
                }
            },
            height=1080,
        )

        content = generate_ass(transcript, {"width": 1920, "height": 1080, "fps": 24}, style=style)

        # Singer 2 preview line should use \1c&HFFE500& (the unsung color of v2)
        self.assertIn(r"{\an5\pos(960,691)\alpha&H80&\1c&HFFE500&\fad(150,0)}Singer two upcoming", content)


if __name__ == "__main__":
    unittest.main()
