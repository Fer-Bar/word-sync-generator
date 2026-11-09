"""Real FFmpeg and filesystem integration for media transfer and run ownership."""

import json
import subprocess
import zipfile
from pathlib import Path

import imageio_ffmpeg
import pytest

from colab import karaoke_job
from karaoke_app.cli import _create_render_bundle
from karaoke_app.job_document import STATE_FILENAME
from karaoke_app.media_transfer import prepare_audio_transfer


def ffmpeg(*arguments):
    return subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-v", "error", "-y", *map(str, arguments)],
                          check=True, capture_output=True)


@pytest.fixture
def wave_source(tmp_path):
    path = tmp_path / "user-recording.wav"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=0.4", "-c:a", "pcm_s24le", path)
    return path


def pcm(path):
    return ffmpeg("-i", path, "-map", "0:a:0", "-f", "s32le", "-").stdout


def test_integer_wave_is_lossless_compressed_and_reused(wave_source, tmp_path):
    original = wave_source.read_bytes()
    scratch = tmp_path / "scratch"
    prepared = prepare_audio_transfer(wave_source, scratch)
    assert prepared.suffix == ".flac"
    assert prepared.stat().st_size < len(original)
    assert pcm(prepared) == pcm(wave_source)
    assert prepare_audio_transfer(wave_source, scratch) == prepared
    assert list(scratch.iterdir()) == [prepared]
    assert wave_source.read_bytes() == original


def test_float_wave_preserves_float_samples(tmp_path):
    source = tmp_path / "float.wav"
    ffmpeg("-f", "lavfi", "-i", "sine=duration=0.2", "-c:a", "pcm_f32le", source)
    prepared = prepare_audio_transfer(source, tmp_path / "scratch")
    arguments = ("-map", "0:a:0", "-f", "f32le", "-")
    assert ffmpeg("-i", prepared, *arguments).stdout == ffmpeg("-i", source, *arguments).stdout


def test_video_upload_keeps_audio_packets_only(tmp_path):
    source = tmp_path / "user-video.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=0.5", "-f", "lavfi", "-i",
           "sine=frequency=700:duration=0.5", "-c:v", "libx264", "-c:a", "aac", "-shortest", source)
    original = source.read_bytes()
    prepared = prepare_audio_transfer(source, tmp_path / "scratch")
    assert prepared.stat().st_size < len(original)
    arguments = ("-map", "0:a:0", "-c:a", "copy", "-f", "hash", "-hash", "sha256", "-")
    assert ffmpeg("-i", prepared, *arguments).stdout == ffmpeg("-i", source, *arguments).stdout
    result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(prepared),
                             "-map", "0:v:0", "-f", "null", "-"], capture_output=True)
    assert result.returncode != 0 and b"matches no streams" in result.stderr
    assert pcm(prepared) == pcm(source)
    assert source.read_bytes() == original


@pytest.mark.parametrize("extension,codec", [("mp3", "libmp3lame"), ("webm", "libopus")])
def test_compressed_audio_preserves_gapless_samples(tmp_path, extension, codec):
    source = tmp_path / f"recording.{extension}"
    ffmpeg("-f", "lavfi", "-i", "sine=duration=0.5", "-c:a", codec, source)
    prepared = prepare_audio_transfer(source, tmp_path / "scratch")
    assert pcm(prepared) == pcm(source)


def test_missing_audio_never_leaves_partial_transfer(tmp_path):
    source = tmp_path / "silent.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=size=32x32:duration=0.1", "-c:v", "libx264", source)
    scratch = tmp_path / "scratch"
    with pytest.raises(ValueError, match="Cannot prepare audio"):
        prepare_audio_transfer(source, scratch)
    assert list(scratch.iterdir()) == []
    assert source.is_file()


def test_bundle_deduplicates_selected_audio_without_changing_project(wave_source, tmp_path):
    document = {
        "title": "Synthetic", "source": {}, "video": {"width": 320, "height": 180, "fps": 24},
        "media": {"original_audio": wave_source.name, "instrumental_audio": "same.wav",
                  "vocals_audio": "not-used.wav"},
        "background": {"kind": "solid", "color": "#000000"},
        "intro": {"enabled": False}, "thumbnail": {"enabled": False},
    }
    (tmp_path / "same.wav").write_bytes(wave_source.read_bytes())
    before = json.dumps(document, sort_keys=True)
    destination = tmp_path / "render.zip"
    _create_render_bundle(tmp_path, document, "both", {"karaoke": "test", "lyrics": "test"}, destination)
    with zipfile.ZipFile(destination) as archive:
        files = [name for name in archive.namelist() if name.startswith("media/")]
        assert len(files) == 1
        bundle = json.loads(archive.read(STATE_FILENAME))
        assert bundle["media"]["original_audio"] == bundle["media"]["instrumental_audio"] == files[0]
        decoded = tmp_path / "bundled.flac"
        decoded.write_bytes(archive.read(files[0]))
    assert pcm(decoded) == pcm(wave_source)
    assert json.dumps(document, sort_keys=True) == before
    assert not (tmp_path / "audio-transfer").exists()


def test_success_reclaims_only_owned_workspace(monkeypatch, tmp_path):
    root = tmp_path / "runtime"
    root.mkdir()
    original = root / "user-output.mp4"
    original.write_bytes(b"keep")
    monkeypatch.setattr(karaoke_job, "WORK_DIR", root)
    archive = tmp_path / "result.zip"
    for _ in range(2):
        with karaoke_job._managed_workdir(archive) as owned:
            output = owned / "result"
            output.mkdir()
            (output / "song.mp4").write_bytes(b"rendered-output")
            (owned / "mixture.wav").write_bytes(b"discard")
            karaoke_job._create_archive(output, archive)
        assert not owned.exists()
        with zipfile.ZipFile(archive) as result:
            assert result.read("song.mp4") == b"rendered-output"
    assert list(root.iterdir()) == [original]
    assert original.read_bytes() == b"keep"
    assert karaoke_job.WORK_DIR == root


def test_failure_retains_work_without_touching_previous_export(monkeypatch, tmp_path):
    root = tmp_path / "runtime"
    monkeypatch.setattr(karaoke_job, "WORK_DIR", root)
    archive = tmp_path / "last-success.zip"
    archive.write_bytes(b"previous-export")
    with pytest.raises(RuntimeError, match="interrupted"):
        with karaoke_job._managed_workdir(archive) as owned:
            (owned / "completed-first-mode.mp4").write_bytes(b"recover")
            raise RuntimeError("interrupted")
    assert archive.read_bytes() == b"previous-export"
    assert (owned / "completed-first-mode.mp4").read_bytes() == b"recover"
    assert karaoke_job.WORK_DIR == root


def test_stale_archive_does_not_authorize_cleanup(monkeypatch, tmp_path):
    monkeypatch.setattr(karaoke_job, "WORK_DIR", tmp_path / "runtime")
    archive = tmp_path / "old.zip"
    archive.write_bytes(b"old")
    with pytest.raises(RuntimeError, match="No new result"):
        with karaoke_job._managed_workdir(archive) as owned:
            (owned / "partial.flac").write_bytes(b"recover")
    assert owned.is_dir()


def test_pcm_cleanup_excludes_inputs_exports_and_symlink_targets(monkeypatch, tmp_path):
    monkeypatch.setattr(karaoke_job, "WORK_DIR", tmp_path)
    source = tmp_path / "user.wav"
    source.write_bytes(b"source")
    mixture = tmp_path / "mixture.wav"
    mixture.write_bytes(b"pcm")
    separated = tmp_path / "separated"
    separated.mkdir()
    stem = separated / "stem.wav"
    stem.write_bytes(b"pcm")
    link = separated / "link.wav"
    link.symlink_to(source)
    karaoke_job._discard_scratch_audio(source, mixture, stem, link)
    assert not mixture.exists() and not stem.exists()
    assert source.read_bytes() == b"source" and link.is_symlink()


def test_unpack_remaps_into_owned_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(karaoke_job, "WORK_DIR", tmp_path / "run")
    monkeypatch.setattr(karaoke_job, "LYRICS_MODULE_PATH", Path("/content/karaoke_lyrics_file.py"))
    monkeypatch.setattr(karaoke_job, "REFERENCES_MODULE_PATH", Path("/content/karaoke_lyric_references.py"))
    bundle = tmp_path / "source.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("karaoke_source.flac", b"audio")
        archive.writestr("karaoke_lyrics_file.py", "# module")
        archive.writestr("karaoke_lyric_references.py", "# module")
    config = {"source_bundle": str(bundle), "source": {"kind": "file", "value": "/content/karaoke_source.flac"},
              "background": {"kind": "solid", "value": "#000000"}}
    original = bundle.read_bytes()
    karaoke_job._unpack_source(config)
    assert Path(config["source"]["value"]).read_bytes() == b"audio"
    assert Path(config["source"]["value"]).is_relative_to(karaoke_job.WORK_DIR)
    assert karaoke_job.LYRICS_MODULE_PATH.is_file()
    assert config["background"]["value"] == "#000000"
    assert bundle.read_bytes() == original


def test_invalid_archive_does_not_authorize_cleanup(monkeypatch, tmp_path):
    monkeypatch.setattr(karaoke_job, "WORK_DIR", tmp_path / "runtime")
    archive = tmp_path / "result.zip"
    with pytest.raises(RuntimeError, match="not a valid ZIP"):
        with karaoke_job._managed_workdir(archive) as owned:
            (owned / "completed.mp4").write_bytes(b"recover")
            archive.write_bytes(b"incomplete zip")
    assert (owned / "completed.mp4").read_bytes() == b"recover"


def test_packaging_rejects_archive_inside_outputs(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"keep")
    with pytest.raises(ValueError, match="outside"):
        karaoke_job._create_archive(tmp_path, tmp_path / "result.zip")
    assert list(tmp_path.iterdir()) == [video]


def test_pcm_cleanup_does_not_follow_parent_symlink(monkeypatch, tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    outside = tmp_path / "user-files"
    outside.mkdir()
    source = outside / "recording.wav"
    source.write_bytes(b"original")
    (root / "separated").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(karaoke_job, "WORK_DIR", root)
    karaoke_job._discard_scratch_audio(root / "separated" / source.name)
    assert source.read_bytes() == b"original"
