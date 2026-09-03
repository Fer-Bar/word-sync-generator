import json
import tempfile
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from threading import Thread

from karaoke_app.editor import KaraokeEditorHandler, find_free_port
from karaoke_app.lyrics_file import dump_lyrics_file


class EditorServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.job_dir = Path(self.temp_dir.name)

        # Create dummy assets
        (self.job_dir / "instrumental.flac").write_bytes(b"dummy-audio")
        (self.job_dir / "background.jpg").write_bytes(b"dummy-image")

        lyrics_data = {
            "version": "1.0",
            "metadata": {"title": "Test Song"},
            "lines": [
                {
                    "text": "Hello world",
                    "start_ms": 0,
                    "end_ms": 2000,
                    "words": [
                        {"text": "Hello ", "start_ms": 0, "end_ms": 1000},
                        {"text": "world", "start_ms": 1000, "end_ms": 2000},
                    ],
                }
            ],
        }
        (self.job_dir / "lyrics.lyricsfile.yaml").write_text(
            dump_lyrics_file(lyrics_data), encoding="utf-8"
        )

        self.document = {
            "schema_version": 1,
            "job_id": "test-job-123",
            "title": "Test Song",
            "media": {
                "original_audio": "instrumental.flac",
                "vocals_audio": "instrumental.flac",
                "instrumental_audio": "instrumental.flac",
                "lyrics": "lyrics.lyricsfile.yaml",
            },
            "video": {"width": 1920, "height": 1080, "fps": 24},
            "background": {"kind": "image", "path": "background.jpg", "color": "#0B1020"},
        }
        (self.job_dir / "job.json").write_text(json.dumps(self.document), encoding="utf-8")

        transcript = {
            "segments": [
                {
                    "start": 0.0,
                    "end": 2.0,
                    "text": "Hello world",
                    "words": [
                        {"start": 0.0, "end": 1.0, "text": "Hello"},
                        {"start": 1.0, "end": 2.0, "text": "world"},
                    ],
                }
            ]
        }

        class TestHandler(KaraokeEditorHandler):
            pass

        TestHandler.job_dir = self.job_dir
        TestHandler.document = self.document
        TestHandler.transcript = transcript

        self.port = find_free_port(8990)
        self.server = HTTPServer(("127.0.0.1", self.port), TestHandler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.temp_dir.cleanup()

    def test_get_index_html(self) -> None:
        url = f"http://127.0.0.1:{self.port}/"
        with urllib.request.urlopen(url) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "text/html")
            body = response.read().decode("utf-8")
            self.assertIn("Karaoke Style Studio", body)

    def test_get_api_state(self) -> None:
        url = f"http://127.0.0.1:{self.port}/api/state"
        with urllib.request.urlopen(url) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode("utf-8"))
            self.assertEqual(data["title"], "Test Song")
            self.assertIn("job", data)
            self.assertIn("transcript", data)
            self.assertIn("available_fonts", data)

    def test_serve_media_asset(self) -> None:
        url = f"http://127.0.0.1:{self.port}/media/instrumental.flac"
        with urllib.request.urlopen(url) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b"dummy-audio")

    def test_prevent_media_path_traversal(self) -> None:
        url = f"http://127.0.0.1:{self.port}/media/../etc/passwd"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(url)
        self.assertEqual(ctx.exception.code, 404)

    def test_post_api_save_updates_job_and_ass(self) -> None:
        url = f"http://127.0.0.1:{self.port}/api/save"
        payload = {
            "style": {
                "font_family": "Montserrat",
                "font_size": 75,
                "primary_color": "#00FFCC",
                "highlight_color": "#FF00AA",
            },
            "background": {
                "overlay_opacity": 0.55,
                "color": "#112233",
            },
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 200)
            res_data = json.loads(response.read().decode("utf-8"))
            self.assertEqual(res_data["status"], "ok")

        # Verify job.json updated
        saved_job = json.loads((self.job_dir / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(saved_job["style"]["font_family"], "Montserrat")
        self.assertEqual(saved_job["style"]["font_size"], 75)
        self.assertEqual(saved_job["style"]["primary_color"], "#00FFCC")
        self.assertEqual(saved_job["background"]["overlay_opacity"], 0.55)

        # Verify .ass files regenerated
        self.assertTrue((self.job_dir / "karaoke.ass").is_file())
        self.assertTrue((self.job_dir / "lyrics.ass").is_file())
        ass_text = (self.job_dir / "karaoke.ass").read_text(encoding="utf-8")
        self.assertIn("Style: Default,Montserrat,75,", ass_text)


if __name__ == "__main__":
    unittest.main()
