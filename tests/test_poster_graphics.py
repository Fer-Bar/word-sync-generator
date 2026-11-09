"""Reusable poster layouts: content bounds, saved settings, and actual rendered media."""

import json
import wave
import zipfile

import imageio_ffmpeg
import numpy as np
import pytest
from PIL import Image

from colab import karaoke_job
from karaoke_app.ass import generate_ass
from karaoke_app.cli import _create_render_bundle
from karaoke_app.fomo import apply_graphic_options, title_rows
from karaoke_app.job_document import STATE_FILENAME, load_job_document
from karaoke_app.lyrics_file import dump_lyrics_file, load_lyrics_file, lyrics_to_transcript
from karaoke_app.render_graphics import generate_render_graphics
from karaoke_app.style import StyleConfig
from karaoke_app.thumbnail import create_title_overlay, run_thumbnail
from karaoke_app.visual_config import configure_job


@pytest.mark.parametrize("title", ["A", "AN EXAMPLE POSTER TITLE", "W" * 200,
                                   "A much longer song title with many more words than the album name", "ONE\nTWO"])
@pytest.mark.parametrize("layout", ["stacked", "wide"])
@pytest.mark.parametrize("align", ["start", "center", "end"])
def test_titles_fit_without_losing_words(title, layout, align):
    rows = title_rows(title, layout)
    assert " ".join(rows) == " ".join(title.upper().split())
    overlay = create_title_overlay(title, "EXAMPLE ARTIST", graphic_style="fomo", title_layout=layout,
                                   align=align, size=(1280, 720))
    x0, y0, x1, y1 = overlay.getbbox()
    assert 70 <= x0 < x1 <= 1210
    assert 75 <= y0 < y1 <= 590
    assert overlay.getpixel((0, 0))[3] == 0


def test_saved_poster_settings_match_intro_background_and_thumbnail(tmp_path):
    document = {"schema_version": 2, "title": "A long song title", "source": {"artist": "Lead Singer"},
                "video": {"width": 1280, "height": 720, "fps": 24},
                "background": {"kind": "solid", "color": "#123456"}, "watermark": {"enabled": False},
                "media": {"original_audio": "a.wav", "instrumental_audio": "i.wav",
                          "vocals_audio": "v.wav", "lyrics": "lyrics.yaml"}}
    state = tmp_path / STATE_FILENAME
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps(document))
    configure_job(tmp_path, graphic_style="fomo", title_layout="wide", align="end")
    saved = load_job_document(tmp_path)
    assert saved["background"] == {"kind": "solid", "color": "#FFFFFF"}
    assert saved["style"]["lyrics_colors"]["active"] == "#111111"
    assert apply_graphic_options(saved) == saved
    destination = tmp_path / "graphics"
    timing = generate_render_graphics(tmp_path, saved, ("lyrics",), destination,
                                     {"segments": [{"words": [{"start": 4}]}]})
    assert timing["end"] == 3.2
    with Image.open(destination / "intro/intro_lyrics.png") as overlay:
        with Image.open(destination / "background.png") as background:
            composed = Image.alpha_composite(background.convert("RGBA"), overlay).convert("RGB")
        with Image.open(destination / "thumbnails/thumbnail_lyrics.png") as thumbnail:
            assert composed.tobytes() == thumbnail.tobytes()
    run_thumbnail([str(tmp_path), "--mode", "lyrics", "--no-logo"])
    with Image.open(tmp_path / "thumbnails/thumbnail_lyrics.png") as thumbnail:
        assert thumbnail.getpixel((0, 0)) == (255, 255, 255)


@pytest.mark.parametrize("title", [" ", "one\n\ntwo", "1\n2\n3\n4\n5", "a" * 201])
def test_invalid_poster_titles_fail(title):
    with pytest.raises(ValueError):
        title_rows(title, "stacked")


@pytest.mark.parametrize("palette", ["light", "dark"])
def test_print_texture_is_repeatable_and_keeps_transparent_edges(palette):
    from karaoke_app.fomo import fomo_paper

    options = {"size": (1280, 720), "align": "center", "graphic_palette": palette}
    clean = create_title_overlay("Example Poster", "Example Artist", graphic_style="fomo", **options)
    textured = create_title_overlay("Example Poster", "Example Artist", graphic_style="fomo-xerox", **options)
    repeated = create_title_overlay("Example Poster", "Example Artist", graphic_style="fomo-xerox", **options)
    assert textured.tobytes() == repeated.tobytes()
    assert textured.tobytes() != clean.tobytes()
    assert textured.getpixel((0, 0))[3] == 0
    assert textured.getchannel("A").getbbox() is not None
    paper = fomo_paper((1280, 720), xerox=True, palette=palette)
    assert paper.tobytes() == fomo_paper((1280, 720), xerox=True, palette=palette).tobytes()
    channels = paper.split()
    assert channels[0].tobytes() == channels[1].tobytes() == channels[2].tobytes()
    # Palette contrast is a behavior; a particular noise mean/stddev is not.
    opposite = fomo_paper((1280, 720), xerox=True, palette="dark" if palette == "light" else "light")
    if palette == "light":
        assert np.asarray(paper).mean() > np.asarray(opposite).mean()
    else:
        assert np.asarray(paper).mean() < np.asarray(opposite).mean()


@pytest.mark.parametrize("graphic_style,palette", [
    ("default", "light"), ("fomo", "light"), ("fomo", "dark"),
    ("fomo-xerox", "light"), ("fomo-xerox", "dark"),
])
def test_saved_graphics_reach_both_rendered_videos(
    prepared_project, tmp_path, monkeypatch, media_tools, graphic_style, palette,
):
    # Two seconds of valid audio leave room for an intro and a later lyric.
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
    configure_job(prepared_project, graphic_style=graphic_style, graphic_palette=palette,
                  title_layout="wide", align="end")
    document = load_job_document(prepared_project)
    document["intro"]["enabled"] = True
    document["watermark"] = {"enabled": True, "path": str(logo), "position": "top_left"}
    document = apply_graphic_options(document)
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
        if graphic_style != "default":
            # Readability is independent of whether the generated PNG has the same bug.
            direction = 1 if palette == "dark" else -1
            assert (direction * (intro_frames[mode][ink] - plain[ink])).mean() > 100
        # At 0.75 s the intro has ended and vocals have not started. Keep clear of logos.
        gap = frames[6].astype(float)
        assert np.abs(gap[30:140, 80:300] - plain[30:140, 80:300]).mean() < 15
        # Compare against the gap so a persistent watermark cannot stand in for lyrics.
        singing = frames[12].astype(float)
        assert np.count_nonzero(np.abs(gap[20:170, 80:310] - singing[20:170, 80:310]) > 50) > 20
        with Image.open(output / "thumbnails" / f"thumbnail_{mode}.png") as thumbnail:
            assert thumbnail.size == (1280, 720)
        assert (output / "subtitles" / f"Song_{mode}.ass").read_text() == subtitles[mode]
    if graphic_style == "default":
        # The default modes have distinct title cards; FOMO intentionally shares its layout.
        assert np.count_nonzero(np.abs(intro_frames["lyrics"] - intro_frames["karaoke"]) > 50) > 100
