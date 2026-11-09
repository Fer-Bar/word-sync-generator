import json
import subprocess
import zipfile
from unittest.mock import patch

import imageio_ffmpeg
import numpy as np
import pytest
from media_samples import write_audio
from PIL import Image, ImageFilter

from colab import karaoke_job
from karaoke_app.cli import _create_render_bundle, build_background_parser, run_background
from karaoke_app.cosmic_background import CosmicBackground, normalize_cosmic_background, render_cosmic_video
from karaoke_app.job_document import validate_job_document


@pytest.mark.parametrize("key,value", [
    ("speed", -1), ("density", 2), ("opacity", True), ("brightness", float("nan")),
    ("loop_seconds", float("inf")), ("seed", 2.5), ("color", "red"), ("unknown", 1),
])
def test_invalid_configuration(key, value):
    with pytest.raises(ValueError, match="background"):
        normalize_cosmic_background({"kind": "cosmic", key: value})


def test_motion_is_deterministic_seamless_and_can_stop():
    renderer = CosmicBackground({"kind": "cosmic"}, 160, 90)
    first = np.array(renderer.frame(0))
    assert np.array_equal(first, np.array(renderer.frame(20)))
    assert np.array_equal(first, np.array(renderer.frame(0)))
    assert np.mean(np.abs(first.astype(float) - np.array(renderer.frame(3)))) > 1
    still = CosmicBackground({"kind": "cosmic", "speed": 0}, 160, 90)
    assert np.array_equal(np.array(still.frame(0)), np.array(still.frame(3)))


def test_dimming_and_opacity_are_distinct_from_color():
    cfg = {"kind": "cosmic", "color": "#FF0000", "secondary_color": "#FF0000"}
    normal = np.array(CosmicBackground(cfg, 160, 90).frame(0)).astype(float)
    dim = np.array(CosmicBackground(cfg | {"overlay_opacity": 0.5}, 160, 90).frame(0))
    assert np.mean(np.abs(dim - normal * 0.5)) < 1
    black = CosmicBackground(cfg | {"overlay_opacity": 1}, 160, 90)
    assert not np.array(black.frame(0)).any()
    base = CosmicBackground(cfg | {"opacity": 0, "base_color": "#123456"}, 160, 90)
    assert np.all(np.array(base.frame(0)) == [18, 52, 86])
    assert normal[..., 0].mean() > normal[..., 2].mean()


def test_detail_adds_fine_grain_including_between_the_veils():
    smooth = CosmicBackground({"kind": "cosmic", "detail": 0}, 640, 360).frame(0)
    granular = CosmicBackground({"kind": "cosmic", "detail": 1}, 640, 360).frame(0)

    def high_frequency(frame):
        return np.array(frame, dtype=float) - np.array(frame.filter(ImageFilter.GaussianBlur(2)), dtype=float)

    smooth_detail = high_frequency(smooth)
    grain_detail = high_frequency(granular)
    assert grain_detail.std() > smooth_detail.std() * 3
    dark_regions = np.array(smooth).mean(axis=2) < 15
    assert dark_regions.any()
    assert grain_detail[dark_regions].std() > smooth_detail[dark_regions].std() + 0.3


def test_job_bundle_and_remote_render_share_generator(tmp_path, monkeypatch):
    document = validate_job_document({
        "schema_version": 2, "title": "Cosmic", "video": {"width": 160, "height": 90, "fps": 12},
        "media": {"original_audio": "audio.wav", "instrumental_audio": "audio.wav",
                  "vocals_audio": "audio.wav", "lyrics": "lyrics.yaml"},
        "background": {"kind": "cosmic", "overlay_opacity": 0.4},
        "intro": {"enabled": False}, "watermark": {"enabled": False},
    })
    assert validate_job_document(document) == document
    write_audio(tmp_path / "audio.wav")
    bundle = tmp_path / "render.zip"
    _create_render_bundle(tmp_path, document, "both", {"lyrics": "ass", "karaoke": "ass"}, bundle)
    with zipfile.ZipFile(bundle) as archive:
        assert "cosmic_background.py" in archive.namelist()
        assert json.loads(archive.read(".karaoke/project.json"))["background"] == document["background"]
    monkeypatch.setattr(karaoke_job, "WORK_DIR", tmp_path / "remote")
    monkeypatch.setattr(karaoke_job, "RENDER_JOB_PATH", bundle)
    module = type("Generator", (), {"render_cosmic_video": None})()
    with (
        patch.object(karaoke_job.importlib.util, "module_from_spec", return_value=module),
        patch("importlib.machinery.SourceFileLoader.exec_module"),
        patch.object(module, "render_cosmic_video", return_value=tmp_path / "loop.mp4") as generate,
        patch.object(karaoke_job, "_render_video") as render,
        patch.object(karaoke_job, "_create_archive"),
    ):
        karaoke_job._render_existing_job({"mode": "both", "archive_path": str(tmp_path / "result.zip")})
    assert generate.call_count == 1
    assert generate.call_args.args[0]["overlay_opacity"] == 0.4
    assert render.call_count == 2
    assert render.call_args.args[2]["background"] == {"kind": "video", "value": str(tmp_path / "loop.mp4")}


@pytest.mark.parametrize("watermark", [False, True])
def test_video_background_loops_under_lyrics_without_dimming_twice(tmp_path, watermark):
    logo = tmp_path / "logo.png"
    logo.touch()
    (tmp_path / "loop.mp4").touch()
    config = {
        "video": {"width": 160, "height": 90, "fps": 12},
        "background": {"kind": "video", "value": str(tmp_path / "loop.mp4")},
    }
    if watermark:
        config["watermark"] = {"path": str(logo)}
    with (
        patch.object(karaoke_job, "_probe_duration", return_value=30),
        patch.object(karaoke_job, "_nvenc_available", return_value=False),
        patch.object(karaoke_job, "_encode_progress") as run,
    ):
        karaoke_job._render_video(tmp_path / "audio.wav", tmp_path / "out.mp4", config, tmp_path / "lyrics.ass")
    command = run.call_args.args[0]
    assert command[command.index("-stream_loop") + 1] == "-1"
    assert "ass=" in " ".join(command)
    assert "drawbox" not in " ".join(command)


def test_preview_cli_encodes_real_video_with_job_dimming(tmp_path):
    (tmp_path / ".karaoke").mkdir(exist_ok=True)
    config = tmp_path / ".karaoke/project.json"
    config.write_text(json.dumps({
        "video": {"width": 160, "height": 90, "fps": 12},
        "background": {"kind": "cosmic", "overlay_opacity": 1},
    }))
    output = tmp_path / "preview.mp4"
    args = build_background_parser().parse_args([str(tmp_path), "--duration", "0.25", "--output", str(output)])
    assert run_background(args) == output
    decoded = subprocess.run([
        imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(output),
        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ], capture_output=True, check=True).stdout
    assert len(decoded) == 3 * 160 * 90 * 3
    assert max(decoded) <= 2
    assert json.loads(config.read_text())["background"] == {"kind": "cosmic", "overlay_opacity": 1}


def test_invalid_video_leaves_existing_output_untouched(tmp_path):
    output = tmp_path / "preview.mp4"
    output.write_bytes(b"existing")
    with pytest.raises(ValueError, match="even"):
        render_cosmic_video({"kind": "cosmic"}, {"width": 161, "height": 90, "fps": 12}, output)
    assert output.read_bytes() == b"existing"


def test_real_final_composition_repeats_background_under_subtitles_and_logo(tmp_path):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    video = {"width": 160, "height": 90, "fps": 12}
    loop = render_cosmic_video({"kind": "cosmic"}, video, tmp_path / "loop.mp4", duration=0.25)
    audio = tmp_path / "audio.wav"
    subprocess.run([
        ffmpeg, "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(audio),
    ], check=True)
    logo = tmp_path / "logo.png"
    Image.new("RGB", (20, 10), "white").save(logo)
    subtitles = tmp_path / "lyrics.ass"
    subtitles.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 160\nPlayResY: 90\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, Alignment\n"
        "Style: Default,Arial,14,&H00FFFFFF,2\n[Events]\n"
        "Format: Layer, Start, End, Style, Text\nDialogue: 0,0:00:00.00,0:00:01.00,Default,Lyrics\n"
    )
    output = tmp_path / "final.mp4"

    def run_local(command, duration):
        return subprocess.run([ffmpeg, *command[1:]], check=True, capture_output=True)

    with (
        patch.object(karaoke_job, "_probe_duration", return_value=1),
        patch.object(karaoke_job, "_nvenc_available", return_value=False),
        patch.object(karaoke_job, "_encode_progress", side_effect=run_local),
    ):
        karaoke_job._render_video(audio, output, {
            "video": video, "background": {"kind": "video", "value": str(loop)},
            "watermark": {"path": str(logo)},
        }, subtitles)
    decoded = subprocess.run([
        ffmpeg, "-v", "error", "-i", str(output), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ], capture_output=True, check=True).stdout
    assert len(decoded) == 12 * 160 * 90 * 3
