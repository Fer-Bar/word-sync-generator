import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from karaoke_app.cli import _create_render_bundle, _resolve_source


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


class RenderBundleTests(unittest.TestCase):
    def test_packages_mode_specific_ass_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            job_dir = Path(temporary_directory)
            (job_dir / "instrumental.flac").write_bytes(b"instrumental")
            (job_dir / "original.flac").write_bytes(b"original")
            destination = job_dir / "render.zip"
            document = {
                "media": {
                    "instrumental_audio": "instrumental.flac",
                    "original_audio": "original.flac",
                },
                "background": {"kind": "solid", "color": "#0B1020"},
            }

            _create_render_bundle(
                job_dir,
                document,
                "both",
                {"karaoke": "karaoke-scroll", "lyrics": "lyrics-static"},
                destination,
            )

            with zipfile.ZipFile(destination) as archive:
                self.assertEqual(archive.read("karaoke.ass"), b"karaoke-scroll")
                self.assertEqual(archive.read("lyrics.ass"), b"lyrics-static")
                self.assertEqual(json.loads(archive.read("job.json"))["background"]["kind"], "solid")


if __name__ == "__main__":
    unittest.main()
