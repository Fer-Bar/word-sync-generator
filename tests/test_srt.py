import tempfile
import unittest
import zipfile
from pathlib import Path

from media_samples import write_audio

from karaoke_app.cli import _create_render_bundle
from karaoke_app.srt import format_srt_timestamp, generate_srt


class SrtGenerationTests(unittest.TestCase):
    def test_format_srt_timestamp(self) -> None:
        self.assertEqual(format_srt_timestamp(0.0), "00:00:00,000")
        self.assertEqual(format_srt_timestamp(11.32), "00:00:11,320")
        self.assertEqual(format_srt_timestamp(65.5), "00:01:05,500")
        self.assertEqual(format_srt_timestamp(3661.123), "01:01:01,123")

    def test_generate_srt_from_transcript(self) -> None:
        transcript = {
            "segments": [
                {
                    "start": 1.0,
                    "end": 3.5,
                    "text": "First line of the song",
                },
                {
                    "start": 4.0,
                    "end": 6.25,
                    "text": "Second line of the song",
                },
            ]
        }
        srt = generate_srt(transcript)
        expected = (
            "1\n"
            "00:00:01,000 --> 00:00:03,500\n"
            "First line of the song\n\n"
            "2\n"
            "00:00:04,000 --> 00:00:06,250\n"
            "Second line of the song\n"
        )
        self.assertEqual(srt, expected)

    def test_generate_srt_from_lyrics_dict(self) -> None:
        lyrics = {
            "lines": [
                {"text": "Hello world", "start_ms": 1000, "end_ms": 2500},
                {"text": "Chorus line", "start_ms": 3000, "end_ms": 4500, "isBackground": True},
            ]
        }
        srt = generate_srt(lyrics)
        self.assertIn("1\n00:00:01,000 --> 00:00:02,500\nHello world", srt)
        self.assertIn("2\n00:00:03,000 --> 00:00:04,500\n(Chorus line)", srt)

    def test_generate_srt_background_vocals_wrapping(self) -> None:
        transcript = {
            "segments": [
                {"start": 1.0, "end": 2.0, "text": "Already parenthesized", "isBackground": True},
                {"start": 3.0, "end": 4.0, "text": "(Pre-wrapped)", "isBackground": True},
            ]
        }
        srt = generate_srt(transcript)
        self.assertIn("(Already parenthesized)", srt)
        self.assertIn("(Pre-wrapped)", srt)
        self.assertNotIn("((Pre-wrapped))", srt)

    def test_generate_srt_skips_empty_and_clamps_end_time(self) -> None:
        transcript = {
            "segments": [
                {"start": 1.0, "end": 2.0, "text": ""},
                {"start": 2.0, "end": 1.5, "text": "Inverted time"},
                {"start": 5.0, "end": 6.0, "text": "   "},
            ]
        }
        srt = generate_srt(transcript)
        self.assertTrue(srt.startswith("1\n"))
        self.assertIn("Inverted time", srt)
        self.assertIn("00:00:02,000 --> 00:00:02,500", srt)

    def test_render_bundle_contains_srt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            write_audio(job_dir / "instrumental.flac")
            write_audio(job_dir / "original.flac")
            document = {
                "title": "Test Song",
                "video": {"width": 1280, "height": 720, "fps": 24},
                "media": {
                    "instrumental_audio": "instrumental.flac",
                    "original_audio": "original.flac",
                },
                "background": {"kind": "solid", "color": "#000000"},
            }
            destination = job_dir / "bundle.zip"
            _create_render_bundle(
                job_dir,
                document,
                mode="lyrics",
                ass_by_mode={"lyrics": "[Script Info]"},
                destination=destination,
                srt_content="1\n00:00:01,000 --> 00:00:02,000\nTest",
            )
            with zipfile.ZipFile(destination, "r") as archive:
                namelist = archive.namelist()
                self.assertIn("lyrics.srt", namelist)
                self.assertEqual(archive.read("lyrics.srt").decode("utf-8"), "1\n00:00:01,000 --> 00:00:02,000\nTest")
