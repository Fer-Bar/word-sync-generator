import copy
import json
import zipfile
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from colab import karaoke_job
from karaoke_app.cli import _create_render_bundle
from karaoke_app.cosmic_background import CosmicBackground
from karaoke_app.job_document import validate_job_document
from karaoke_app.render_graphics import (
    background_frame,
    generate_render_graphics,
    graphic_logo,
    graphic_metadata,
    intro_timing,
)


@pytest.fixture
def document():
    return {
        "title": "ALRIGHT",
        "source": {"artist": "Ashes to Amber"},
        "video": {"width": 640, "height": 360, "fps": 24},
        "background": {"kind": "solid", "color": "#183040"},
        "watermark": {"enabled": False},
        "media": {"original_audio": "audio.wav", "instrumental_audio": "audio.wav"},
    }


@pytest.mark.parametrize("start,expected", [(0, None), (0.8, None), (1, 0.2), (3, 2.2), (12, 5)])
def test_intro_does_not_cover_early_vocals(document, start, expected):
    timing = intro_timing(document, {"segments": [{"words": [{"start": start}]}]})
    if expected is None:
        assert timing is None
    else:
        assert timing["end"] == pytest.approx(expected)


def test_timing_considers_all_voices_and_custom_start(document):
    document["intro"] = {"start": 1, "duration": 8, "end": 6}
    transcript = {"segments": [{"words": [{"start": 12}]}, {"words": [{"start": 4}]}]}
    assert intro_timing(document, transcript) == {"enabled": True, "start": 1, "duration": 2.2, "end": 3.2}
    document["intro"]["start"] = 4
    assert intro_timing(document, transcript) is None


def test_metadata_precedence(document):
    document["metadata"] = {"artist": "Fallback"}
    assert graphic_metadata(document) == ("ALRIGHT", "Ashes to Amber")
    document["intro"] = {"title": "Custom", "artist": "Override"}
    assert graphic_metadata(document) == ("Custom", "Override")
    document.pop("intro")
    document.pop("source")
    assert graphic_metadata(document) == ("ALRIGHT", "Fallback")


def test_explicit_no_logo_wins_over_intro_logo(document, tmp_path):
    document["intro"] = {"logo": "missing.png"}
    assert graphic_logo(tmp_path, document) is None


def test_cosmic_snapshot_is_the_video_generator_frame(document, tmp_path):
    document["background"] = {"kind": "cosmic", "seed": 99, "overlay_opacity": 0.55}
    expected = CosmicBackground(document["background"], 640, 360).frame(0)
    assert np.array_equal(background_frame(tmp_path, document), expected)


def test_image_snapshot_applies_dimming_once(document, tmp_path):
    Image.new("RGB", (900, 600), (200, 100, 50)).save(tmp_path / "bg.png")
    document["background"] = {"kind": "image", "path": "bg.png", "overlay_opacity": 0.5}
    image = background_frame(tmp_path, document)
    assert image.size == (640, 360)
    assert image.getpixel((0, 0)) == (100, 50, 25)


def test_thumbnail_is_the_same_overlay_composited_over_background(document, tmp_path):
    original = copy.deepcopy(document)
    timing = generate_render_graphics(
        tmp_path,
        document,
        ("lyrics",),
        tmp_path / "graphics",
        {
            "segments": [{"words": [{"start": 10}]}],
        },
    )
    assert timing["end"] == 5
    assert original == document
    graphics = tmp_path / "graphics"
    with Image.open(graphics / "background.png") as bg, Image.open(graphics / "intro/intro_lyrics.png") as overlay:
        assert overlay.mode == "RGBA"
        assert overlay.getpixel((0, 0))[3] == 0
        expected = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")
        expected = expected.resize((1280, 720), Image.Resampling.LANCZOS)
    with Image.open(graphics / "thumbnails/thumbnail_lyrics.png") as thumbnail:
        assert np.array_equal(expected, thumbnail)


def test_render_bundle_routes_both_modes_and_returns_graphics(document, tmp_path, monkeypatch):
    (tmp_path / "audio.wav").write_bytes(b"audio")
    (tmp_path / "intro_card.png").write_bytes(b"obsolete")
    bundle = tmp_path / "bundle.zip"
    _create_render_bundle(
        tmp_path,
        document,
        "both",
        {"lyrics": "lyrics-ass", "karaoke": "karaoke-ass"},
        bundle,
        transcript={"segments": [{"words": [{"start": 4}]}]},
    )
    monkeypatch.setattr(karaoke_job, "WORK_DIR", tmp_path / "remote")
    monkeypatch.setattr(karaoke_job, "RENDER_JOB_PATH", bundle)
    archive = tmp_path / "result.zip"
    with patch.object(karaoke_job, "_render_video") as render:
        karaoke_job._render_existing_job({"mode": "both", "archive_path": str(archive)})
    assert render.call_count == 2
    for mode, call in zip(("karaoke", "lyrics"), render.call_args_list, strict=True):
        config = call.args[2]
        assert config["intro_card"]["path"].endswith(f"intro_{mode}.png")
        assert config["intro_card"]["end"] == pytest.approx(3.2)
    with zipfile.ZipFile(archive) as result:
        assert "background.png" in result.namelist()
        assert "thumbnails/thumbnail_lyrics.png" in result.namelist()
        assert "thumbnails/thumbnail_karaoke.png" in result.namelist()
        assert result.read("intro/intro_lyrics.png") != result.read("intro/intro_karaoke.png")
    with zipfile.ZipFile(bundle) as packed:
        assert json.loads(packed.read("job.json"))["intro"]["end"] == pytest.approx(3.2)


def test_disabled_intro_still_generates_thumbnail(document, tmp_path):
    document["intro"] = {"enabled": False}
    timing = generate_render_graphics(tmp_path, document, ("karaoke",), tmp_path, None)
    assert timing is None
    assert (tmp_path / "thumbnails/thumbnail_karaoke.png").is_file()
    assert not (tmp_path / "thumbnails/thumbnail_lyrics.png").exists()
    assert not (tmp_path / "intro").exists()


def test_thumbnail_has_logo_but_intro_is_unbranded(document, tmp_path):
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (270, 80), (255, 0, 0, 255)).save(logo)
    document["watermark"] = {"enabled": True, "path": str(logo)}
    generate_render_graphics(
        tmp_path,
        document,
        ("lyrics",),
        tmp_path / "graphics",
        {
            "segments": [{"words": [{"start": 10}]}],
        },
    )
    with Image.open(tmp_path / "graphics/intro/intro_lyrics.png") as intro:
        assert intro.getchannel("A").crop((0, 300, 130, 360)).getbbox() is None
    with Image.open(tmp_path / "graphics/thumbnails/thumbnail_lyrics.png") as thumbnail:
        assert thumbnail.getpixel((80, 665)) == (255, 0, 0)


def test_watermark_keeps_its_top_left_position_during_intro(tmp_path):
    logo, intro = tmp_path / "logo.png", tmp_path / "intro.png"
    logo.touch()
    intro.touch()
    config = {
        "video": {"width": 1280, "height": 720, "fps": 24},
        "background": {"kind": "solid", "value": "#000000"},
        "watermark": {"path": str(logo), "position": "top_left"},
        "intro_card": {"path": str(intro), "start": 0, "end": 3},
    }
    with (
        patch.object(karaoke_job, "_probe_duration", return_value=10),
        patch.object(karaoke_job, "_nvenc_available", return_value=False),
        patch.object(karaoke_job, "_run") as run,
    ):
        karaoke_job._render_video(tmp_path / "audio.wav", tmp_path / "video.mp4", config)
    command = run.call_args.args[0]
    filters = command[command.index("-filter_complex") + 1]
    assert "[bg][wm]overlay=x=main_w*0.05:y=main_h*0.05[v_wm]" in filters
    assert "not(between" not in filters
    assert command.count(str(logo)) == 1


def test_thumbnail_configuration_survives_normalization(document):
    document.update({"schema_version": 2, "thumbnail": {"time": 3, "align": "end"}})
    document["media"].update({"vocals_audio": "audio.wav", "lyrics": "lyrics.yaml"})
    normalized = validate_job_document(document)
    assert normalized["thumbnail"] == {"time": 3, "align": "end"}
    assert validate_job_document(normalized) == normalized


@pytest.mark.parametrize("config", [
    {"time": -1}, {"time": True}, {"time": float("nan")}, {"time": "3"}, {"align": "right"},
])
def test_invalid_thumbnail_configuration(document, config):
    document.update({"schema_version": 2, "thumbnail": config})
    document["media"].update({"vocals_audio": "audio.wav", "lyrics": "lyrics.yaml"})
    with pytest.raises(ValueError, match="thumbnail"):
        validate_job_document(document)


def test_thumbnail_time_and_alignment_do_not_change_intro(document, tmp_path):
    from karaoke_app.thumbnail import create_title_overlay

    document["thumbnail"] = {"time": 3, "align": "end"}
    frames = [Image.new("RGB", (640, 360), color) for color in ("red", "blue")]
    with patch("karaoke_app.render_graphics.background_frame", side_effect=frames) as sample:
        generate_render_graphics(tmp_path, document, ("lyrics",), tmp_path,
                                 {"segments": [{"words": [{"start": 10}]}]})
    assert sample.call_args_list[1].kwargs == {"time": 3}
    expected_intro = create_title_overlay("ALRIGHT", "Ashes to Amber", mode="lyrics", size=(640, 360))
    expected_title = create_title_overlay("ALRIGHT", "Ashes to Amber", mode="lyrics", size=(640, 360), align="end")
    expected_thumbnail = Image.alpha_composite(frames[1].convert("RGBA"), expected_title).convert("RGB")
    expected_thumbnail = expected_thumbnail.resize((1280, 720), Image.Resampling.LANCZOS)
    with Image.open(tmp_path / "intro/intro_lyrics.png") as intro:
        assert np.array_equal(intro, expected_intro)
    with Image.open(tmp_path / "thumbnails/thumbnail_lyrics.png") as thumbnail:
        assert np.array_equal(thumbnail, expected_thumbnail)


def test_video_thumbnail_samples_requested_frame(document, tmp_path):
    import subprocess

    import imageio_ffmpeg

    subprocess.run([
        imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i",
        "color=c=red:s=320x180:r=24:d=0.5", "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=24:d=0.5",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-pix_fmt", "yuv420p",
        str(tmp_path / "scene.mp4"),
    ], check=True, capture_output=True)
    document["background"] = {"kind": "video", "path": "scene.mp4"}
    first = background_frame(tmp_path, document).getpixel((0, 0))
    selected = background_frame(tmp_path, document, time=0.75).getpixel((0, 0))
    assert first[0] > 240 and first[2] < 10
    assert selected[2] > 240 and selected[0] < 10
    with pytest.raises(ValueError, match="No background frame"):
        background_frame(tmp_path, document, time=2)
