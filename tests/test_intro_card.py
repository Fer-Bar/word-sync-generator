import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from karaoke_app.intro_card import create_intro_card, generate_intro_card_for_job


class IntroCardTests(unittest.TestCase):
    def test_create_intro_card_basic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            logo_path = temp_path / "logo.png"
            logo_img = Image.new("RGBA", (300, 100), (255, 0, 0, 255))
            logo_img.save(logo_path)

            output_path = temp_path / "intro_card.png"
            result = create_intro_card(
                title="Song Title",
                artist="Artist Name",
                width=1920,
                height=1080,
                output_path=output_path,
            )

            self.assertTrue(result.is_file())
            img = Image.open(result)
            self.assertEqual(img.size, (1920, 1080))
            self.assertEqual(img.mode, "RGBA")
            self.assertIsNone(img.getchannel("A").crop((0, 850, 500, 1080)).getbbox())
            self.assertIsNotNone(img.getbbox())

    def test_create_intro_card_without_artist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            output_path = temp_path / "intro_card.png"
            result = create_intro_card(
                title="Solo Title",
                artist=None,
                width=1280,
                height=720,
                output_path=output_path,
            )
            self.assertTrue(result.is_file())
            img = Image.open(result)
            self.assertEqual(img.size, (1280, 720))
            self.assertIsNotNone(img.getbbox())

    def test_generate_intro_card_for_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            job_dir = Path(temp_dir)
            logo_path = job_dir / "banner.png"
            Image.new("RGBA", (200, 80), (0, 255, 0, 255)).save(logo_path)

            job_doc = {
                "schema_version": 2,
                "job_id": "test-job",
                "title": "Test Song",
                "source": {"artist": "Test Artist"},
                "media": {
                    "original_audio": "audio.flac",
                    "vocals_audio": "vocals.flac",
                    "instrumental_audio": "instrumental.flac",
                    "lyrics": "lyrics.yaml",
                },
                "video": {"width": 1920, "height": 1080, "fps": 24},
                "background": {"kind": "solid", "color": "#000000"},
                "intro": {"enabled": True, "duration": 5.0, "logo": "banner.png"},
            }
            (job_dir / ".karaoke").mkdir(exist_ok=True)
            (job_dir / ".karaoke/project.json").write_text(json.dumps(job_doc), encoding="utf-8")
            (job_dir / "audio.flac").write_bytes(b"data")
            (job_dir / "vocals.flac").write_bytes(b"data")
            (job_dir / "instrumental.flac").write_bytes(b"data")
            (job_dir / "lyrics.yaml").write_bytes(b"data")

            result = generate_intro_card_for_job(job_dir)
            self.assertIsNotNone(result)
            self.assertTrue(result.is_file())
            self.assertEqual(result.name, "intro_card.png")

    def test_generate_intro_card_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            job_dir = Path(temp_dir)
            job_doc = {
                "schema_version": 2,
                "job_id": "test-job",
                "title": "Test Song",
                "source": {"artist": "Test Artist"},
                "media": {
                    "original_audio": "audio.flac",
                    "vocals_audio": "vocals.flac",
                    "instrumental_audio": "instrumental.flac",
                    "lyrics": "lyrics.yaml",
                },
                "video": {"width": 1920, "height": 1080, "fps": 24},
                "background": {"kind": "solid", "color": "#000000"},
                "intro": {"enabled": False},
            }
            (job_dir / ".karaoke").mkdir(exist_ok=True)
            (job_dir / ".karaoke/project.json").write_text(json.dumps(job_doc), encoding="utf-8")
            (job_dir / "audio.flac").write_bytes(b"data")
            (job_dir / "vocals.flac").write_bytes(b"data")
            (job_dir / "instrumental.flac").write_bytes(b"data")
            (job_dir / "lyrics.yaml").write_bytes(b"data")

            result = generate_intro_card_for_job(job_dir)
            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
