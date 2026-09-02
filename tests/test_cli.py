import unittest

from karaoke_app.cli import _resolve_source


class ResolveSourceTests(unittest.TestCase):
    def test_normalizes_windows_escaped_youtube_url(self) -> None:
        source = r"https://www.youtube.com/watch\?v\=-48t4C0W90w\&list\=example"

        self.assertEqual(
            _resolve_source(source),
            ("url", "https://www.youtube.com/watch?v=-48t4C0W90w&list=example"),
        )

    def test_preserves_canonical_youtube_url(self) -> None:
        source = "https://www.youtube.com/watch?v=-48t4C0W90w"

        self.assertEqual(_resolve_source(source), ("url", source))

    def test_rejects_unexpected_backslash_in_youtube_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "unexpected backslash"):
            _resolve_source(r"https://www.youtube.com/watch\invalid?v=-48t4C0W90w")

    def test_rejects_watch_url_without_video_parameter(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing the 'v=' parameter"):
            _resolve_source("https://www.youtube.com/watch?list=example")


if __name__ == "__main__":
    unittest.main()
