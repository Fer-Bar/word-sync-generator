"""Timing, typography, contrast and packaging checks for the Plus render."""

import copy
import io
import subprocess
import zipfile
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import pytest
from PIL import Image

from karaoke_app.ass import generate_ass
from karaoke_app.cli import _create_render_bundle, build_render_parser
from karaoke_app.cosmic_background import CosmicBackground
from karaoke_app.lyrics_plus import FONT_DIRECTORY, PRESET, apply_lyrics_plus, cover_palette, switzer_font
from karaoke_app.style import StyleConfig
from karaoke_app.themes import apply_render_theme
from karaoke_app.word_synced import _groups


def segment(text, start, end):
    return {"text": text, "start": start, "end": end, "words": [{"text": text, "start": start, "end": end}]}


def test_preset_and_artwork_preserve_original_job(tmp_path):
    doc = {"background": {"kind": "solid", "color": "#111111"},
           "video": {"width": 1280, "height": 720, "fps": 24}, "style": {"font_family": "Old"}}
    original = copy.deepcopy(doc)
    cover = tmp_path / "cover.png"
    image = Image.new("RGB", (32, 32), "#CC2244")
    image.paste("#2244CC", (0, 0, 16, 32))
    image.save(cover)
    result, selected = apply_render_theme(doc, PRESET)
    apply_lyrics_plus(result, cover)
    assert doc == original
    assert selected == PRESET
    assert result["style"]["font_family"] == "Switzer Semibold"
    assert result["style"]["lyrics_effect"] == "word-synced"
    assert result["background"]["appearance"] == "fluid"
    assert set(cover_palette(cover).values()) == {"#CC2244", "#2244CC"}
    args = build_render_parser().parse_args(["job", "--theme", PRESET, "--cover", str(cover)])
    assert args.cover == cover


def test_fluid_bright_artwork_is_bounded_and_motion_loops():
    renderer = CosmicBackground({"kind": "cosmic", "appearance": "fluid", "color": "#FFFFFF",
                                 "secondary_color": "#FFAAFF", "brightness": 3}, 160, 90)
    frame = np.array(renderer.frame(0))
    assert frame.max() <= 110
    assert np.array_equal(frame, np.array(renderer.frame(20)))
    moving = CosmicBackground({"kind": "cosmic", "appearance": "fluid"}, 160, 90)
    assert not np.array_equal(moving.frame(0), moving.frame(3))


def test_overlapping_vocals_are_grouped_without_retiming():
    groups = _groups([segment("Lead", 1, 3), segment("Backing", 2, 2.5), segment("Next", 3.2, 4)])
    assert len(groups) == 2
    assert len(groups[0]["lines"]) == 2
    assert groups[0]["display_end"] == groups[1]["display_start"] == 310
    assert groups[0]["lines"][1]["words"][0]["start"] == 2


def test_fixed_pages_interleaves_background_vocals():
    from karaoke_app.word_synced import _fixed_pages

    segments = [
        segment("Lead 1", 1.0, 3.0),
        {
            "text": "(Backing 1)",
            "start": 1.5,
            "end": 2.5,
            "isBackground": True,
            "words": [{"text": "(Backing 1)", "start": 1.5, "end": 2.5, "isBackground": True}],
        },
        segment("Lead 2", 3.5, 5.0),
    ]
    pages = _fixed_pages(segments)
    assert len(pages) == 1
    assert len(pages[0]["lines"]) == 3
    assert pages[0]["lines"][0]["text"] == "Lead 1"
    assert pages[0]["lines"][1]["text"] == "(Backing 1)"
    assert pages[0]["lines"][2]["text"] == "Lead 2"


def test_words_keep_silence_and_fragment_timing(monkeypatch):
    bundled = Path(__file__).resolve().parents[1] / "src/karaoke_app/assets/fonts/Montserrat.ttf"
    monkeypatch.setattr("karaoke_app.word_synced.switzer_font", lambda: bundled)
    transcript = {"segments": [segment("Hello", 1, 2), segment("World", 2.4, 3.5)]}
    transcript["segments"][0]["words"][0]["timing"] = [
        {"text": "Hel", "start": 1, "end": 1.4}, {"text": "lo", "start": 1.4, "end": 2},
    ]
    before = copy.deepcopy(transcript)
    style = StyleConfig(lyrics_effect="word-synced", font_size=36)
    ass = generate_ass(transcript, {"width": 640, "height": 360}, style=style, mode="lyrics")
    assert r"{\k35}{\kf40}Hel{\kf60}lo" in ass
    assert r"\fnSwitzer Semibold" in ass
    assert r"\move" not in ass
    assert r"\fscx109" not in ass
    assert r"\fscy109" in ass
    assert transcript == before
    karaoke = generate_ass(transcript, {"width": 640, "height": 360}, style=style, mode="karaoke")
    assert r"\fscy109" in karaoke
    assert r"\move" in karaoke
    assert r"\alpha&H57&" in karaoke
    assert r"\alpha&HAA&" in karaoke
    assert r"\fnSwitzer Semibold" in karaoke


def test_font_download_is_cached_without_modification(tmp_path, monkeypatch):
    bundled = Path(__file__).resolve().parents[1] / "src/karaoke_app/assets/fonts/Anton-Regular.ttf"
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("Switzer_Complete/Fonts/OTF/Switzer-Semibold.otf", bundled.read_bytes())
        output.writestr("Switzer_Complete/License/FFL.txt", "license")
    monkeypatch.setattr("karaoke_app.lyrics_plus.FONT_DIRECTORY", tmp_path)
    calls = []
    def download(url, timeout):
        calls.append(url)
        return io.BytesIO(archive.getvalue())
    monkeypatch.setattr("karaoke_app.lyrics_plus.urllib.request.urlopen", download)
    assert switzer_font().read_bytes() == bundled.read_bytes()
    switzer_font()
    assert len(calls) == 1
    assert (tmp_path / "Switzer-FFL.txt").read_text() == "license"


@pytest.mark.skipif(not (FONT_DIRECTORY / "Switzer-Semibold.otf").is_file(), reason="Switzer not cached locally")
def test_real_libass_selects_switzer_and_bundle_carries_font(tmp_path):
    doc, _ = apply_render_theme({"title": "Sample", "source": {"artist": "Test"},
        "video": {"width": 320, "height": 180, "fps": 8},
        "background": {"kind": "solid", "color": "#000000"}, "watermark": {"enabled": False},
        "media": {"original_audio": "audio.wav"}}, PRESET)
    transcript = {"segments": [segment("Switzer", 0.2, 0.9)]}
    ass = generate_ass(transcript, doc["video"], style=StyleConfig.from_dict(doc["style"]), mode="lyrics")
    (tmp_path / "audio.wav").write_bytes(b"unused for bundle")
    bundle = tmp_path / "bundle.zip"
    _create_render_bundle(tmp_path, doc, "lyrics", {"lyrics": ass}, bundle, transcript=transcript)
    with zipfile.ZipFile(bundle) as archive:
        assert {"fonts/Switzer-Semibold.otf", "fonts/Switzer-FFL.txt"} <= set(archive.namelist())
        archive.extractall(tmp_path / "render")
    result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "verbose", "-f", "lavfi", "-i",
        "color=s=320x180:r=8:d=1", "-vf", "ass=lyrics.ass:fontsdir=fonts", "-f", "null", "-"],
        cwd=tmp_path / "render", capture_output=True, text=True, check=True)
    selections = [line for line in result.stderr.splitlines() if "fontselect:" in line]
    assert selections
    assert all("-> Switzer-Semibold" in line for line in selections)


@pytest.mark.skipif(not (FONT_DIRECTORY / "Switzer-Semibold.otf").is_file(), reason="Switzer not cached locally")
def test_real_active_and_upcoming_rows_have_identical_word_spacing(tmp_path):
    transcript = {"segments": [segment("Warm up", 0.5, 2), {
        "text": "Yeah all they'll become", "start": 2.4, "end": 4,
        "words": [{"text": text, "start": 2.4 + index * 0.4, "end": 2.8 + index * 0.4}
                  for index, text in enumerate(["Yeah ", "all ", "they'll ", "become"])]}]}
    style = StyleConfig(lyrics_effect="word-synced", font_size=36, margin_h=45)
    ass = generate_ass(transcript, {"width": 640, "height": 360}, style=style, mode="karaoke")
    (tmp_path / "lyrics.ass").write_text(ass)
    (tmp_path / "Switzer-Semibold.otf").write_bytes(switzer_font().read_bytes())
    result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i",
        "color=s=640x360:r=10:d=4", "-vf", "ass=lyrics.ass:fontsdir=.",
        "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], cwd=tmp_path, capture_output=True, check=True)
    frames = np.frombuffer(result.stdout, dtype=np.uint8).reshape(-1, 360, 640, 3)
    upcoming = frames[10, 280:340].max(axis=(0, 2))
    active = frames[32, 150:215].max(axis=(0, 2))
    upcoming_ink = upcoming > upcoming.max() * 0.25
    active_ink = active > active.max() * 0.25
    assert upcoming_ink.any() and active_ink.any()
    # Each ink edge stays within one pixel despite different alpha/antialiasing.
    for source, target in ((upcoming_ink, active_ink), (active_ink, upcoming_ink)):
        expanded = target | np.roll(target, 1) | np.roll(target, -1)
        assert np.all(~source | expanded)


@pytest.mark.parametrize("mode", ["lyrics", "karaoke"])
@pytest.mark.skipif(not (FONT_DIRECTORY / "Switzer-Semibold.otf").is_file(), reason="Switzer not cached locally")
def test_real_word_pulse_grows_and_settles_without_moving_neighbors(tmp_path, mode):
    transcript = {"segments": [{"text": "MMM MMM MMM", "start": 1, "end": 5, "words": [
        {"text": "MMM", "start": 1, "end": 1.4},
        {"text": "MMM", "start": 2, "end": 3},
        {"text": "MMM", "start": 4, "end": 5},
    ]}]}
    style = StyleConfig(lyrics_effect="word-synced", font_size=64, margin_h=45)
    (tmp_path / "lyrics.ass").write_text(generate_ass(transcript, {"width": 640, "height": 360},
                                                    style=style, mode=mode))
    (tmp_path / "Switzer-Semibold.otf").write_bytes(switzer_font().read_bytes())
    result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i",
        "color=s=640x360:r=10:d=3.5", "-vf", "ass=lyrics.ass:fontsdir=.",
        "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], cwd=tmp_path, capture_output=True, check=True)
    frames = np.frombuffer(result.stdout, dtype=np.uint8).reshape(-1, 360, 640, 3)

    def bounds(frame, left, right):
        y, x = np.where(frames[frame, :, left:right].max(axis=2) > 60)
        return np.array([x.min(), x.max(), y.min(), y.max()])

    before, peak, settled = [bounds(frame, 190, 333) for frame in (19, 22, 33)]
    assert peak[2] <= before[2] - 2
    assert peak[3] - peak[2] >= before[3] - before[2] + 2
    assert np.max(np.abs(before - settled)) <= 1
    assert np.max(np.abs(before[:2] - peak[:2])) <= 1
    for left, right in ((45, 185), (335, 480)):
        assert np.max(np.abs(bounds(19, left, right) - bounds(22, left, right))) <= 1
