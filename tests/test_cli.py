import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from karaoke_app import cli
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
                "title": "Song", "source": {"artist": "Artist"},
                "video": {"width": 640, "height": 360, "fps": 24},
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
                self.assertEqual(json.loads(archive.read(".karaoke/project.json"))["background"]["kind"], "solid")

    def test_packages_watermark_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            job_dir = Path(temporary_directory)
            (job_dir / "instrumental.flac").write_bytes(b"instrumental")
            (job_dir / "original.flac").write_bytes(b"original")
            Image.new("RGBA", (100, 30), "red").save(job_dir / "banner.png")
            destination = job_dir / "render.zip"
            document = {
                "title": "Song", "source": {"artist": "Artist"},
                "video": {"width": 640, "height": 360, "fps": 24},
                "media": {
                    "instrumental_audio": "instrumental.flac",
                    "original_audio": "original.flac",
                },
                "background": {"kind": "solid", "color": "#0B1020"},
                "watermark": {
                    "path": "banner.png",
                    "position": "top_left",
                    "scale": 0.18,
                    "margin": 0.05,
                    "opacity": 0.85,
                },
            }

            _create_render_bundle(
                job_dir,
                document,
                "both",
                {"karaoke": "karaoke-scroll", "lyrics": "lyrics-static"},
                destination,
            )

            with zipfile.ZipFile(destination) as archive:
                self.assertIn("watermark.png", archive.namelist())
                self.assertEqual(archive.read("watermark.png"), (job_dir / "banner.png").read_bytes())

    def test_regenerates_intro_card_instead_of_reusing_stale_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            job_dir = Path(temporary_directory)
            (job_dir / "instrumental.flac").write_bytes(b"instrumental")
            (job_dir / "original.flac").write_bytes(b"original")
            (job_dir / "intro_card.png").write_bytes(b"intro-png-data")
            destination = job_dir / "render.zip"
            document = {
                "title": "Song", "source": {"artist": "Artist"},
                "video": {"width": 640, "height": 360, "fps": 24},
                "media": {
                    "instrumental_audio": "instrumental.flac",
                    "original_audio": "original.flac",
                },
                "background": {"kind": "solid", "color": "#0B1020"},
                "intro": {"enabled": True, "duration": 4.0},
            }

            _create_render_bundle(
                job_dir,
                document,
                "both",
                {"karaoke": "karaoke-scroll", "lyrics": "lyrics-static"},
                destination,
                transcript={"segments": [{"words": [{"start": 10.0}]}]},
            )

            with zipfile.ZipFile(destination) as archive:
                self.assertIn("graphics/intro/intro_karaoke.png", archive.namelist())
                self.assertTrue(archive.read("graphics/intro/intro_karaoke.png").startswith(b"\x89PNG"))
                self.assertNotIn("intro_card.png", archive.namelist())
                bundle_job = json.loads(archive.read(".karaoke/project.json"))
                self.assertIn("intro", bundle_job)
                self.assertEqual(bundle_job["intro"]["duration"], 4.0)

    def test_packages_absolute_watermark_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            job_dir = Path(temporary_directory)
            (job_dir / "instrumental.flac").write_bytes(b"instrumental")
            (job_dir / "original.flac").write_bytes(b"original")
            destination = job_dir / "render.zip"
            document = {
                "title": "Song", "source": {"artist": "Artist"},
                "video": {"width": 640, "height": 360, "fps": 24},
                "media": {
                    "instrumental_audio": "instrumental.flac",
                    "original_audio": "original.flac",
                },
                "background": {"kind": "solid", "color": "#0B1020"},
                "watermark": {
                    "path": "logos/banner.png",
                    "position": "top_left",
                    "scale": 0.18,
                    "margin": 0.05,
                    "opacity": 0.85,
                },
            }

            _create_render_bundle(
                job_dir,
                document,
                "both",
                {"karaoke": "karaoke-scroll", "lyrics": "lyrics-static"},
                destination,
            )

            with zipfile.ZipFile(destination) as archive:
                self.assertIn("watermark.png", archive.namelist())
                bundled_doc = json.loads(archive.read(".karaoke/project.json"))
                self.assertEqual(bundled_doc["watermark"]["path"], "watermark.png")


class CLIParserTests(unittest.TestCase):
    def test_logo_arguments(self) -> None:
        from karaoke_app.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "https://www.youtube.com/watch?v=-48t4C0W90w",
                "--logo",
                "logos/banner.png",
                "--logo-position",
                "top_left",
                "--logo-scale",
                "0.20",
                "--logo-opacity",
                "0.9",
            ]
        )

        self.assertEqual(args.logo, Path("logos/banner.png"))
        self.assertEqual(args.logo_position, "top_left")
        self.assertEqual(args.logo_scale, 0.20)
        self.assertEqual(args.logo_opacity, 0.9)


class SourceReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.args = cli.build_parser().parse_args(
            ["https://youtube.com/watch?v=test", "--no-logo", "--no-cookies", "--output-dir", str(self.root)]
        )
        audio = self.root / "download.webm"
        audio.write_bytes(b"audio")
        downloader = patch(
            "karaoke_app.youtube_source.download_youtube",
            return_value=(audio, {"title": "Song", "artist": "Artist", "webpage_url": self.args.source}),
        )
        self.downloader = downloader.start()
        self.addCleanup(downloader.stop)
        self.status = {"status": "completed"}
        self.commands = []
        self.exec_code = 0
        self.fail_downloads = 0
        self.stop_timeout = False
        self.payload = None
        installation = patch.object(cli, "_validate_installation")
        installation.start()
        self.addCleanup(installation.stop)
        runner = patch.object(cli, "_run", side_effect=self.run_command)
        runner.start()
        self.addCleanup(runner.stop)

    def test_download_failure_does_not_provision_colab(self):
        self.downloader.side_effect = RuntimeError("local download failed")
        with self.assertRaisesRegex(RuntimeError, "local download failed"):
            cli.run_job(self.args)
        self.assertEqual(self.commands, [])

    def test_youtube_is_uploaded_with_metadata(self):
        cli.run_job(self.args)
        self.assertEqual(self.payload["source"]["kind"], "file")
        self.assertEqual(self.payload["source"]["metadata"]["webpage_url"], self.args.source)
        self.assertIn("karaoke_source.webm", self.source_bundle_members)

    def run_command(self, command, *, check=True, timeout=None):
        self.commands.append((command, timeout))
        operation = command[2]
        if operation == "upload" and command[-1] == str(cli.REMOTE_JOB):
            self.payload = json.loads(Path(command[-2]).read_text())
        if operation == "upload" and command[-1] == str(cli.REMOTE_SOURCE_BUNDLE):
            with zipfile.ZipFile(command[-2]) as archive:
                self.source_bundle_members = archive.namelist()
        if operation == "exec":
            if self.exec_code == -1:
                raise subprocess.TimeoutExpired(command, timeout)
            return subprocess.CompletedProcess(command, self.exec_code)
        if operation == "stop" and self.stop_timeout:
            raise subprocess.TimeoutExpired(command, timeout)
        if operation == "download":
            destination = Path(command[-1])
            if self.fail_downloads:
                self.fail_downloads -= 1
                destination.write_bytes(b"partial")
                return subprocess.CompletedProcess(command, 1)
            if command[-2] == str(cli.REMOTE_STATUS):
                destination.write_text(json.dumps(self.status))
            else:
                with zipfile.ZipFile(destination, "w") as archive:
                    if "checkpoint" in command[-2]:
                        archive.writestr("checkpoint.json", '{"status": "lyrics_failed"}')
                        archive.writestr("vocals.flac", b"vocals")
                    else:
                        archive.writestr(".karaoke/project.json", "{}")
        return subprocess.CompletedProcess(command, 0)

    def manifest(self):
        return json.loads(next(self.root.glob("*.recovery/recovery.json")).read_text())

    def test_failed_exec_downloads_lyrics_checkpoint_and_stops(self) -> None:
        self.exec_code = 1
        self.status = {
            "status": "failed", "stage": "lyrics", "error": "alignment failed",
            "recovery_archive_path": "/content/result.checkpoint.zip",
        }
        with self.assertRaisesRegex(RuntimeError, "lyrics: alignment failed"):
            cli.run_job(self.args)
        manifest = self.manifest()
        self.assertTrue(manifest["session_stopped"])
        self.assertEqual(manifest["remote_recovery_archive_path"], self.status["recovery_archive_path"])
        checkpoint = next(self.root.glob("*.recovery/checkpoint.zip"))
        with zipfile.ZipFile(checkpoint) as archive:
            self.assertIn("vocals.flac", archive.namelist())
            self.assertNotIn(".karaoke/project.json", archive.namelist())
        self.assertFalse(list(self.root.glob("*/.karaoke/project.json")))

    def test_execution_timeout_still_downloads_status_and_result_without_false_success(self) -> None:
        self.exec_code = -1
        with self.assertRaises(RuntimeError):
            cli.run_job(self.args)
        self.assertTrue(self.manifest()["session_stopped"])
        self.assertTrue(list(self.root.glob("*.recovery/result.zip")))
        self.assertFalse(list(self.root.glob("*/.karaoke/project.json")))

    def test_status_download_retries_are_bounded_and_keep_metadata(self) -> None:
        self.fail_downloads = 10
        with self.assertRaisesRegex(RuntimeError, "after 3 attempts"):
            cli.run_job(self.args)
        downloads = [(command, timeout) for command, timeout in self.commands if command[2] == "download"]
        self.assertEqual(len(downloads), 3)
        self.assertTrue(all(timeout == 300 for _, timeout in downloads))
        self.assertIn("status.json.partial", self.manifest()["local_artifacts"])
        self.assertTrue(self.manifest()["session_stopped"])

    def test_transient_download_failure_recovers(self) -> None:
        self.fail_downloads = 1
        output = cli.run_job(self.args)
        self.assertTrue((output / ".karaoke/project.json").is_file())
        self.assertFalse(list(self.root.glob("*.recovery")))
        self.assertEqual(self.payload["watermark"], {"enabled": False})

    def test_lyric_reference_is_uploaded_with_service(self) -> None:
        text_path = self.root / "reference.txt"
        text_path.write_text("first verse\nsecond verse", encoding="utf-8")
        self.args.lyrics_text = text_path
        self.args.genius_url = "https://genius.com/Artist-song-lyrics"
        cli.run_job(self.args)
        self.assertEqual(self.payload["lyrics"]["text_path"], str(cli.REMOTE_LYRICS_TEXT))
        self.assertEqual(self.payload["lyrics"]["genius_url"], self.args.genius_url)
        uploads = [command[-1] for command, _ in self.commands if command[2] == "upload"]
        self.assertIn(str(cli.REMOTE_SOURCE_BUNDLE), uploads)
        self.assertIn(cli.REMOTE_LYRICS_TEXT.name, self.source_bundle_members)
        self.assertIn(cli.REMOTE_REFERENCES_MODULE.name, self.source_bundle_members)
        self.assertNotIn("karaoke_cookies.txt", self.source_bundle_members)
        self.assertNotIn(".hf_token", self.source_bundle_members)

    def test_force_whisper_rejects_reference_before_provisioning(self) -> None:
        self.args.no_lrclib = True
        self.args.genius_url = "https://genius.com/Artist-song-lyrics"
        with self.assertRaisesRegex(ValueError, "forces Whisper"):
            cli.run_job(self.args)
        self.assertFalse(self.commands)

    def test_local_genius_is_uploaded_before_remote_alignment(self) -> None:
        self.args.title = "Song"
        self.args.artist = "Artist"
        reference = {
            "source": "genius", "original_text": "first verse", "lines": [{"text": "first verse"}],
            "metadata": {"title": "Song", "artist": "Artist"}, "url": "https://genius.com/Artist-song-lyrics",
        }

        def fetch(options, metadata, pipeline_path):
            self.assertFalse(self.commands)
            self.assertEqual(metadata, {"title": "Song", "artist": "Artist"})
            return reference

        with patch("karaoke_app.lyric_references.prefetch_genius_reference", side_effect=fetch):
            cli.run_job(self.args)
        self.assertIn(cli.REMOTE_GENIUS_REFERENCE.name, self.source_bundle_members)
        self.assertEqual(self.payload["lyrics"]["genius_reference_path"], str(cli.REMOTE_GENIUS_REFERENCE))
        self.assertIsNone(self.payload["lyrics"]["text_path"])
        self.assertFalse(self.payload["lyrics"]["disable_lrclib"])

    def test_invalid_reference_url_does_not_provision_colab(self) -> None:
        self.args.genius_url = "https://example.com/song-lyrics"
        with self.assertRaisesRegex(ValueError, "Genius URL"):
            cli.run_job(self.args)
        self.assertFalse(self.commands)

    def test_archive_download_exhaustion_keeps_status_and_stops(self) -> None:
        def runner(command, **kwargs):
            if command[2] == "download" and command[-2] == str(cli.REMOTE_ARCHIVE):
                self.fail_downloads = 1
            return self.run_command(command, **kwargs)
        with patch.object(cli, "_run", side_effect=runner):
            with self.assertRaisesRegex(RuntimeError, "karaoke_result.zip after 3 attempts"):
                cli.run_job(self.args)
        self.assertTrue(self.manifest()["session_stopped"])
        self.assertEqual(self.manifest()["remote_status"], self.status)
        self.assertTrue(list(self.root.glob("*.recovery/status.json")))

    def test_checkpoint_download_failure_preserves_original_lyrics_error(self) -> None:
        self.status = {
            "status": "failed", "stage": "lyrics", "error": "alignment failed",
            "recovery_archive_path": "/content/result.checkpoint.zip",
        }
        def runner(command, **kwargs):
            if command[2] == "download" and "checkpoint" in command[-2]:
                self.fail_downloads = 1
            return self.run_command(command, **kwargs)
        with patch.object(cli, "_run", side_effect=runner):
            with self.assertRaisesRegex(RuntimeError, "lyrics: alignment failed"):
                cli.run_job(self.args)
        self.assertIn("after 3 attempts", self.manifest()["checkpoint_download_error"])
        self.assertTrue(self.manifest()["session_stopped"])

    def test_upload_failure_still_stops_session_and_writes_manifest(self) -> None:
        def runner(command, **kwargs):
            if command[2] == "upload":
                raise OSError("upload failed")
            return self.run_command(command, **kwargs)
        with patch.object(cli, "_run", side_effect=runner):
            with self.assertRaisesRegex(RuntimeError, "upload failed; recovery"):
                cli.run_job(self.args)
        self.assertTrue(self.manifest()["session_stopped"])

    def test_cancellation_stops_session_and_preserves_interrupt(self) -> None:
        for operation in ("new", "upload", "exec", "download"):
            with self.subTest(operation=operation):
                self.commands.clear()

                def cancel(command, cancelled_operation=operation, **kwargs):
                    if command[2] == cancelled_operation:
                        raise KeyboardInterrupt
                    return self.run_command(command, **kwargs)

                with patch.object(cli, "_run", side_effect=cancel), self.assertRaises(KeyboardInterrupt):
                    cli.run_job(self.args)
                operations = [command[2] for command, _ in self.commands]
                self.assertEqual(operations[-1], "stop")
                self.assertEqual(operations.count("stop"), 1)
                manifests = list(self.root.glob("*.recovery/recovery.json"))
                self.assertTrue(manifests)
                self.assertTrue(all(json.loads(path.read_text())["session_stopped"] for path in manifests))

    def test_extraction_failure_keeps_completed_download(self) -> None:
        with patch.object(cli, "_extract_archive", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(RuntimeError, "disk full; recovery"):
                cli.run_job(self.args)
        archive = next(self.root.glob("*.recovery/result.zip"))
        self.assertTrue(zipfile.is_zipfile(archive))
        self.assertTrue(self.manifest()["session_stopped"])

    def test_stop_timeout_retains_archive_and_does_not_claim_success(self) -> None:
        self.stop_timeout = True
        with self.assertRaisesRegex(RuntimeError, "stop was not confirmed"):
            cli.run_job(self.args)
        self.assertFalse(self.manifest()["session_stopped"])
        self.assertTrue(list(self.root.glob("*.recovery/result.zip")))
        self.assertEqual(self.commands[-1][1], 60)

    def test_image_background_ignores_unused_color_and_has_zero_overlay(self) -> None:
        image = self.root / "background.png"
        Image.new("RGB", (2, 2)).save(image)
        self.args.background_image = image
        self.args.background_color = "not a color"
        cli.run_job(self.args)
        self.assertEqual(self.payload["background"]["overlay_opacity"], 0)
        self.assertEqual(self.payload["background"]["kind"], "image")

    def test_invalid_inputs_fail_before_provisioning(self) -> None:
        invalid = self.root / "invalid.png"
        invalid.write_bytes(b"not an image")
        for attribute, value in (
            ("timeout", 0), ("lrclib_id", -1), ("logo_scale", float("nan")),
            ("logo_scale", 0.9), ("logo_opacity", float("inf")), ("logo_opacity", -0.1),
            ("background_image", invalid),
        ):
            with self.subTest(attribute=attribute, value=value):
                previous = getattr(self.args, attribute)
                setattr(self.args, attribute, value)
                with self.assertRaises(ValueError):
                    cli.run_job(self.args)
                setattr(self.args, attribute, previous)
                self.assertEqual(self.commands, [])
        self.args.no_lrclib = True
        self.args.lrclib_id = 1
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            cli.run_job(self.args)
        self.assertEqual(self.commands, [])


class AtomicArchiveTests(unittest.TestCase):
    def test_render_does_not_inject_default_watermark(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for watermark in (None, {"enabled": False}):
                with self.subTest(watermark=watermark):
                    document = {
                        "schema_version": 2,
                        "title": "Song",
                        "media": {"lyrics": "lyrics.yaml", "vocals_audio": "vocals.wav",
                                  "original_audio": "audio.wav", "instrumental_audio": "instrumental.wav"},
                        "background": {"kind": "solid", "color": "#000000"},
                        "video": {"width": 1920, "height": 1080, "fps": 24},
                    }
                    if watermark is not None:
                        document["watermark"] = watermark
                    args = cli.build_render_parser().parse_args([str(root)])
                    with (
                        patch.object(cli, "_validate_installation"),
                        patch("karaoke_app.job_document.load_job_document", return_value=document),
                        patch("karaoke_app.job_document.resolve_job_asset", return_value=root / "lyrics.yaml"),
                        patch("karaoke_app.lyrics_file.load_lyrics_file", return_value={}),
                        patch("karaoke_app.lyrics_file.lyrics_to_transcript", return_value={"segments": []}),
                        patch("karaoke_app.ass.generate_ass", return_value="ass"),
                        patch("karaoke_app.srt.generate_srt", return_value="srt"),
                        patch.object(cli, "_create_render_bundle", side_effect=ValueError("bundle boundary")),
                    ):
                        with self.assertRaisesRegex(ValueError, "bundle boundary"):
                            cli.render_colab(args)
                    self.assertEqual(document.get("watermark"), watermark)

    def test_unsafe_archive_does_not_publish_partial_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "result.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("valid.txt", "valid")
                archive.writestr("../escape.txt", "invalid")
            with self.assertRaisesRegex(ValueError, "Unsafe archive"):
                cli._extract_archive(archive_path, root / "result")
            self.assertFalse((root / "result").exists())
            self.assertFalse((root / "escape.txt").exists())
            self.assertFalse(list(root.glob(".karaoke-extract-*")))

    def test_extraction_failure_does_not_publish_partial_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "result.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("valid.txt", "valid")
            def fail_extract(archive, destination):
                (destination / "partial.txt").write_text("partial")
                raise OSError("disk full")
            with patch.object(zipfile.ZipFile, "extractall", fail_extract):
                with self.assertRaisesRegex(OSError, "disk full"):
                    cli._extract_archive(archive_path, root / "result")
            self.assertFalse((root / "result").exists())
            self.assertFalse(list(root.glob(".karaoke-extract-*")))

    def test_disabled_watermark_does_not_resolve_or_bundle_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "audio.flac").write_bytes(b"audio")
            document = {
                "title": "Song", "source": {"artist": "Artist"},
                "video": {"width": 640, "height": 360, "fps": 24},
                "media": {"instrumental_audio": "audio.flac"},
                "background": {"kind": "solid", "color": "#000000"},
                "watermark": {"enabled": False, "path": "missing.png"},
            }
            destination = root / "bundle.zip"
            cli._create_render_bundle(root, document, "karaoke", {"karaoke": "ass"}, destination)
            with zipfile.ZipFile(destination) as archive:
                self.assertFalse(json.loads(archive.read(".karaoke/project.json"))["watermark"]["enabled"])
                self.assertNotIn("watermark.png", archive.namelist())


class JobDocumentWatermarkTests(unittest.TestCase):
    def _base_valid_doc(self) -> dict:
        return {
            "schema_version": 2,
            "title": "Test Song",
            "media": {
                "original_audio": "audio.flac",
                "vocals_audio": "vocals.flac",
                "instrumental_audio": "instrumental.flac",
                "lyrics": "lyrics.lyricsfile.yaml",
            },
            "video": {"width": 1920, "height": 1080, "fps": 24},
            "background": {"kind": "solid", "color": "#0B1020"},
        }

    def test_validates_document_without_watermark(self) -> None:
        from karaoke_app.job_document import validate_job_document

        doc = self._base_valid_doc()
        doc["schema_version"] = 2
        validated = validate_job_document(doc)
        self.assertEqual(validated["watermark"], {"enabled": False})

    def test_validates_document_with_valid_watermark(self) -> None:
        from karaoke_app.job_document import validate_job_document

        doc = self._base_valid_doc()
        doc["watermark"] = {
            "path": "banner.png",
            "position": "top_left",
            "scale": 0.18,
            "margin": 0.05,
            "opacity": 0.85,
        }
        validated = validate_job_document(doc)
        self.assertIn("watermark", validated)
        self.assertEqual(validated["watermark"]["path"], "banner.png")
        self.assertEqual(validated["watermark"]["position"], "top_left")
        self.assertEqual(validated["watermark"]["scale"], 0.18)
        self.assertEqual(validated["watermark"]["margin"], 0.05)
        self.assertEqual(validated["watermark"]["opacity"], 0.85)

    def test_accepts_absolute_or_project_watermark_path(self) -> None:
        from karaoke_app.job_document import validate_job_document

        doc = self._base_valid_doc()
        doc["watermark"] = {"path": "/absolute/path/to/logo.png"}
        validated = validate_job_document(doc)
        self.assertEqual(validated["watermark"]["path"], "/absolute/path/to/logo.png")

    def test_resolve_watermark_path(self) -> None:
        from karaoke_app.job_document import resolve_watermark_path

        with tempfile.TemporaryDirectory() as temp_dir:
            job_dir = Path(temp_dir)
            project_dir = job_dir / "project"
            logo = project_dir / "logos" / "banner.png"
            logo.parent.mkdir(parents=True)
            Image.new("RGBA", (100, 30), "red").save(logo)
            with patch("karaoke_app.job_document.PROJECT_ROOT", project_dir):
                resolved = resolve_watermark_path(job_dir, "logos/banner.png")
            self.assertEqual(resolved, logo)
            self.assertTrue(resolved.is_file())
            self.assertEqual(resolved.name, "banner.png")

    def test_rejects_invalid_watermark_position(self) -> None:
        from karaoke_app.job_document import validate_job_document

        doc = self._base_valid_doc()
        doc["watermark"] = {"path": "banner.png", "position": "center"}
        with self.assertRaisesRegex(ValueError, "watermark.position must be"):
            validate_job_document(doc)

    def test_rejects_invalid_watermark_scale(self) -> None:
        from karaoke_app.job_document import validate_job_document

        doc = self._base_valid_doc()
        doc["watermark"] = {"path": "banner.png", "scale": 0.9}
        with self.assertRaisesRegex(ValueError, "watermark.scale must be"):
            validate_job_document(doc)


if __name__ == "__main__":
    unittest.main()
