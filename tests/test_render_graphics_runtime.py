"""Exercise the actual FFmpeg composition with shared branding and themed backgrounds."""

import json
import subprocess
import wave
import zipfile
from unittest.mock import patch

import imageio_ffmpeg
import numpy as np
from PIL import Image

from colab import karaoke_job
from karaoke_app.cli import _create_render_bundle
from karaoke_app.themes import apply_render_theme


def test_real_render_has_one_video_watermark_and_unbranded_intro(tmp_path):
    logo = tmp_path / "logo.png"
    Image.new("RGB", (100, 30), (255, 0, 0)).save(logo)
    with wave.open(str(tmp_path / "audio.wav"), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 8000 * 3)
    document, theme = apply_render_theme(
        {
            "title": "Song",
            "source": {"artist": "Artist"},
            "video": {"width": 320, "height": 180, "fps": 6},
            "background": {"kind": "cosmic", "loop_seconds": 2},
            "watermark": {"enabled": True, "path": str(logo), "position": "top_left", "opacity": 1},
            "media": {"original_audio": "audio.wav", "instrumental_audio": "audio.wav"},
        },
        "synthwave",
        seed=19,
    )
    ass = """[Script Info]
ScriptType: v4.00+
PlayResX: 320
PlayResY: 180
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:02.30,0:00:03.00,Default,,0,0,0,,Lyrics
"""  # noqa: E501
    bundle = tmp_path / "bundle.zip"
    _create_render_bundle(
        tmp_path,
        document,
        "both",
        {"lyrics": ass, "karaoke": ass},
        bundle,
        transcript={"segments": [{"words": [{"start": 2.3}]}]},
    )
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    def run(command, *, capture_output=False):
        assert command[0] == "ffmpeg"
        return subprocess.run([ffmpeg, "-loglevel", "error", *command[1:]], capture_output=True, text=True, check=True)

    with (
        patch.object(karaoke_job, "WORK_DIR", tmp_path / "remote"),
        patch.object(karaoke_job, "RENDER_JOB_PATH", bundle),
        patch.object(karaoke_job, "_run", run),
        patch.object(karaoke_job, "_probe_duration", return_value=3),
        patch.object(karaoke_job, "_nvenc_available", return_value=False),
    ):
        karaoke_job._render_existing_job({"mode": "both", "theme": theme, "archive_path": str(tmp_path / "result.zip")})
    output = tmp_path / "remote/render_result"
    with zipfile.ZipFile(tmp_path / "result.zip") as archive:
        assert "background.mp4" not in archive.namelist()
        assert all(info.compress_type == zipfile.ZIP_STORED for info in archive.infolist())
        assert {
            "background.png",
            "Song_lyrics.mp4",
            "Song_karaoke.mp4",
            "render-settings.json",
            "thumbnails/thumbnail_lyrics.png",
            "thumbnails/thumbnail_karaoke.png",
        } <= set(archive.namelist())
        settings = json.loads(archive.read("render-settings.json"))
        assert settings["theme"] == "synthwave"
        assert settings["background"]["seed"] == 19
    frames = []
    for instant in (0, 0.5, 2):
        result = subprocess.run(
            [
                ffmpeg,
                "-loglevel",
                "error",
                "-ss",
                str(instant),
                "-i",
                str(output / "Song_lyrics.mp4"),
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ],
            capture_output=True,
            check=True,
        )
        frame = np.frombuffer(result.stdout, dtype=np.uint8).reshape(180, 320, 3)
        frames.append(frame)
        # The same red watermark remains top-left, during and after the intro.
        assert frame[15, 25, 0] > 200 and frame[15, 25, 1] < 60
        assert frame[164, 25, 0] < 180  # No second red logo at the bottom.
    assert not np.array_equal(frames[0][80:150], frames[1][80:150])
    with Image.open(output / "intro/intro_lyrics.png") as intro:
        assert intro.getchannel("A").crop((0, 155, 65, 180)).getbbox() is None
    with Image.open(output / "thumbnails/thumbnail_lyrics.png") as thumbnail:
        assert thumbnail.getpixel((80, 665)) == (255, 0, 0)
