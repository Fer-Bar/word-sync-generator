"""Saved title cards, branding and lyrics reach both actual rendered videos."""

import wave
import zipfile

import imageio_ffmpeg
import numpy as np
import pytest
from PIL import Image

from colab import karaoke_job
from karaoke_app.ass import generate_ass
from karaoke_app.cli import _create_render_bundle
from karaoke_app.job_document import load_job_document
from karaoke_app.lyrics_file import dump_lyrics_file, load_lyrics_file, lyrics_to_transcript
from karaoke_app.style import StyleConfig
from karaoke_app.visual_config import configure_job


def test_saved_graphics_reach_both_rendered_videos(prepared_project, tmp_path, monkeypatch, media_tools):
    # Two seconds leave room for an intro and a later lyric.
    for name in ("original", "instrumental", "vocals"):
        path = prepared_project / f"{name}.wav"
        with wave.open(str(path), "rb") as audio:
            params, samples = audio.getparams(), audio.readframes(audio.getnframes())
        with wave.open(str(path), "wb") as audio:
            audio.setparams(params)
            audio.writeframes(samples * 2)
    lyric_path = prepared_project / "lyrics.yaml"
    lyrics = load_lyrics_file(lyric_path)
    lyrics["metadata"]["duration_ms"] = 2000
    for line in lyrics["lines"]:
        for item in (line, *line["words"]):
            item["start_ms"] += 1000
            item["end_ms"] += 1000
    lyric_path.write_text(dump_lyrics_file(lyrics))
    logo = prepared_project / "logo.png"
    Image.new("RGBA", (90, 30), (240, 20, 30, 255)).save(logo)
    configure_job(prepared_project, graphic_style="default", align="end")
    document = load_job_document(prepared_project)
    document["intro"]["enabled"] = True
    document["watermark"] = {"enabled": True, "path": str(logo), "position": "top_left"}
    transcript = lyrics_to_transcript(lyrics)
    subtitles = {mode: generate_ass(transcript, document["video"],
                                   style=StyleConfig.from_dict(document["style"]), mode=mode)
                 for mode in ("lyrics", "karaoke")}
    bundle = tmp_path / "bundle.zip"
    _create_render_bundle(prepared_project, document, "both", subtitles, bundle, transcript=transcript)
    monkeypatch.setattr(karaoke_job, "WORK_DIR", tmp_path / "remote")
    monkeypatch.setattr(karaoke_job, "RENDER_JOB_PATH", bundle)
    monkeypatch.setattr(karaoke_job, "_ensure_system_fonts", lambda: None)
    monkeypatch.setattr(karaoke_job, "_ensure_bebas_font", lambda: None)
    result = tmp_path / "result.zip"
    karaoke_job._render_existing_job({"mode": "both", "archive_path": str(result)})
    output = tmp_path / "download"
    with zipfile.ZipFile(result) as archive:
        assert archive.testzip() is None
        archive.extractall(output)
    background = Image.open(output / "background.png").convert("RGBA")
    intro_frames = {}
    for mode in ("lyrics", "karaoke"):
        video = imageio_ffmpeg.read_frames(str(output / f"Song_{mode}.mp4"), pix_fmt="rgb24")
        metadata = next(video)
        frames = [np.frombuffer(frame, dtype=np.uint8).reshape(180, 320, 3) for frame in video]
        assert metadata["duration"] == pytest.approx(2, abs=.15)
        assert len(frames) == 16
        with Image.open(output / "intro" / f"intro_{mode}.png") as intro:
            expected = np.asarray(Image.alpha_composite(background, intro).convert("RGB")).astype(float)
            ink = np.asarray(intro.getchannel("A")) > 240
        ink[:, :80] = False  # Exclude the independently applied watermark.
        assert np.count_nonzero(ink) > 20
        intro_frames[mode] = frames[1].astype(float)
        assert np.abs(intro_frames[mode][ink] - expected[ink]).mean() < 35
        plain = np.asarray(background.convert("RGB")).astype(float)
        gap = frames[6].astype(float)
        assert np.abs(gap[30:140, 80:300] - plain[30:140, 80:300]).mean() < 15
        singing = frames[12].astype(float)
        assert np.count_nonzero(np.abs(gap[20:170, 80:310] - singing[20:170, 80:310]) > 50) > 20
        with Image.open(output / "thumbnails" / f"thumbnail_{mode}.png") as thumbnail:
            assert thumbnail.size == (1280, 720)
        assert (output / "subtitles" / f"Song_{mode}.ass").read_text() == subtitles[mode]
    assert np.count_nonzero(np.abs(intro_frames["lyrics"] - intro_frames["karaoke"]) > 50) > 100
