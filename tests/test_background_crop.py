import subprocess
from unittest.mock import patch

import imageio_ffmpeg
import numpy as np
import pytest
from PIL import Image

from colab.karaoke_job import _encode_progress, _render_video
from karaoke_app.job_document import validate_job_document
from karaoke_app.render_graphics import background_frame


def test_crop_validation():
    document = {
        "schema_version": 2, "title": "Landscape",
        "media": dict.fromkeys(("original_audio", "vocals_audio", "instrumental_audio", "lyrics"), "asset"),
        "video": {"width": 320, "height": 180, "fps": 24},
        "background": {"kind": "video", "path": "scene.mp4", "crop_right": 0.12},
    }
    normalized = validate_job_document(document)
    assert normalized["background"]["crop_right"] == 0.12
    assert validate_job_document(normalized) == normalized
    for invalid in (-0.1, 0.51, True, "0.12"):
        document["background"]["crop_right"] = invalid
        with pytest.raises(ValueError, match="crop_right"):
            validate_job_document(document)


@pytest.mark.parametrize("kind", ["image", "video"])
@pytest.mark.parametrize("with_logo", [False, True])
def test_actual_render_removes_right_strip(tmp_path, kind, with_logo, monkeypatch):
    pixels = np.zeros((180, 320, 3), dtype=np.uint8)
    pixels[:, :, 2] = 180
    pixels[:, 280:] = (255, 255, 255)
    source = tmp_path / "source.png"
    Image.fromarray(pixels).save(source)
    audio = tmp_path / "audio.wav"
    subprocess.run([
        imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", "0.3", str(audio),
    ], check=True)
    if kind == "video":
        source = tmp_path / "source.mp4"
        subprocess.run([
            imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-loop", "1", "-i", str(tmp_path / "source.png"),
            "-t", "0.2", "-pix_fmt", "yuv420p", str(source),
        ], check=True)
    background = {"kind": kind, "path": source.name, "crop_right": 0.15}
    video = {"width": 320, "height": 180, "fps": 24}
    frame = background_frame(tmp_path, {"video": video, "background": background})
    assert np.asarray(frame)[:, :, 0].max() < 20
    config = {"video": video, "background": {**background, "value": str(source)}}
    if with_logo:
        logo = tmp_path / "logo.png"
        Image.new("RGBA", (20, 20), (0, 255, 0, 255)).save(logo)
        config["watermark"] = {"path": str(logo)}
    output = tmp_path / "render.mp4"

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    monkeypatch.setenv("PATH", "")

    def encode_ffmpeg(command, duration):
        assert command[0] == "ffmpeg"
        _encode_progress([ffmpeg, *command[1:]], duration)

    with (
        patch("colab.karaoke_job._nvenc_available", return_value=False),
        patch("colab.karaoke_job._probe_duration", return_value=0.3),
        patch("colab.karaoke_job._encode_progress", side_effect=encode_ffmpeg),
    ):
        _render_video(audio, output, config)
    rendered = background_frame(tmp_path, {
        "video": video, "background": {"kind": "video", "path": output.name},
    })
    assert rendered.size == (320, 180)
    assert np.asarray(rendered)[:, 160:, 0].max() < 35
    if with_logo:
        assert np.asarray(rendered)[:, :160, 1].max() > 150
