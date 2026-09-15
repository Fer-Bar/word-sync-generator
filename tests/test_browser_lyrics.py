"""Original browser effects, media-time determinism, and final FFmpeg composition."""

import copy
import io
import json
import subprocess
import wave
from pathlib import Path
from unittest.mock import patch

import imageio_ffmpeg
import numpy as np
import pytest
from PIL import Image

from karaoke_app.browser_lyrics import browser_scene, build_browser_scene, render_browser_overlay
from karaoke_app.lyrics_plus import FONT_DIRECTORY, switzer_font


@pytest.fixture
def transcript():
    return {"segments": [
        {"start": 1, "end": 2, "words": [{"text": "Hello ", "start": 1, "end": 1.5},
                                         {"text": "world", "start": 1.5, "end": 2}]},
        {"start": 2.4, "end": 3.5, "words": [{"text": "Next line", "start": 2.4, "end": 3.5}]},
    ]}


def scene_for(transcript, mode):
    return build_browser_scene(transcript, {"width": 640, "height": 360, "fps": 12},
                               {"font_size": 40, "margin_h": 40}, mode)


def test_scene_preserves_original_word_and_fragment_times(transcript):
    transcript["segments"][0]["words"][0]["timing"] = [
        {"text": "Hel", "start": 1, "end": 1.2}, {"text": "lo ", "start": 1.2, "end": 1.5},
    ]
    before = copy.deepcopy(transcript)
    scene = scene_for(transcript, "lyrics")
    assert scene["lyrics"][0]["words"] == "Hello world"
    assert [part["startTimeMs"] for part in scene["lyrics"][0]["parts"]] == [1000, 1200, 1500]
    assert len(scene["groups"]) == 1
    assert len(scene_for(transcript, "karaoke")["groups"]) == 2
    assert transcript == before


def test_scene_includes_vertical_margin(transcript):
    scene = scene_for(transcript, "karaoke")
    assert "margin_v" in scene
    assert scene["margin_v"] == round(360 * 0.22)
    custom_scene = build_browser_scene(
        transcript,
        {"width": 1920, "height": 1080, "fps": 30},
        {"font_size": 64, "margin_h": 70, "margin_v": 150},
        "karaoke",
    )
    assert custom_scene["margin_v"] == 150


@pytest.fixture(scope="module")
def browser_font():
    pytest.importorskip("playwright.sync_api")
    if not (FONT_DIRECTORY / "Switzer-Semibold.otf").is_file():
        pytest.skip("Switzer must be cached to run browser rendering tests")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).is_file():
            pytest.skip("Install Chromium to run browser rendering tests")
        browser = playwright.chromium.launch(headless=True)
        browser.close()
    return switzer_font()


@pytest.mark.parametrize("mode", ["lyrics", "karaoke"])
def test_original_gradient_glow_and_wobble_are_deterministic(transcript, browser_font, mode):
    with browser_scene(scene_for(transcript, mode), browser_font) as page:
        page.evaluate("t=>window.renderFrame(t)", 1.1)
        early = page.evaluate("window.lyricsDiagnostics()")
        first = early[0]["words"][0]
        neighbor_x = early[0]["words"][1]["box"]["x"]
        assert "linear-gradient" in first["gradient"]
        assert "drop-shadow" in first["glow"]
        assert first["transform"] != "matrix(1, 0, 0, 1, 0, 0)"
        assert all(animation["state"] == "paused" for animation in first["animations"])
        page.evaluate("t=>window.renderFrame(t)", 1.3)
        middle = page.evaluate("window.lyricsDiagnostics()")
        assert middle[0]["words"][0]["gradient"] != first["gradient"]
        assert middle[0]["words"][1]["box"]["x"] == pytest.approx(neighbor_x, abs=.1)
        before = np.array(Image.open(io.BytesIO(page.screenshot(omit_background=True))))
        page.wait_for_timeout(150)
        page.evaluate("t=>window.renderFrame(t)", 1.3)
        after = np.array(Image.open(io.BytesIO(page.screenshot(omit_background=True))))
        assert np.array_equal(before, after)
        assert np.any(before[..., 3] > 200)
        page.evaluate("t=>window.renderFrame(t)", 2.6)
        later = page.evaluate("window.lyricsDiagnostics()")
        if mode == "lyrics":
            assert later[0]["box"]["y"] == pytest.approx(early[0]["box"]["y"], abs=.1)
        else:
            assert later[0]["box"]["y"] < early[0]["box"]["y"] - 10


@pytest.mark.parametrize("mode", ["lyrics", "karaoke"])
@pytest.mark.parametrize("line_count", [1, 8])
def test_lines_stay_centered_including_scaled_pages(browser_font, mode, line_count):
    transcript = {"segments": [
        {"start": 1, "end": 2, "words": [{"text": "Centered line", "start": 1, "end": 2}]}
        for _ in range(line_count)
    ]}
    scene = scene_for(transcript, mode)
    if line_count > 1:
        scene["font_size"] = 64
    with browser_scene(scene, browser_font) as page:
        page.evaluate("t=>window.renderFrame(t)", .8)
        lines = page.evaluate("window.lyricsDiagnostics()")
        for line in lines:
            left = min(word["box"]["x"] for word in line["words"])
            right = max(word["box"]["right"] for word in line["words"])
            assert (left + right) / 2 == pytest.approx(320, abs=.5)
        if line_count > 1:
            assert lines[0]["box"]["width"] < 560
        margin_v_val = page.evaluate(
            "getComputedStyle(document.querySelector('#mount')).getPropertyValue('--margin-v')"
        )
        assert margin_v_val.strip() == f"{scene['margin_v']}px"
        if mode == "karaoke":
            assert lines[0]["box"]["y"] == pytest.approx(scene["height"] * 0.45, abs=10)


@pytest.mark.parametrize("position", ["top_left", "bottom_right"])

def test_colab_bundle_renders_browser_overlay_and_keeps_subtitle_export(tmp_path, browser_font, position):
    from colab import karaoke_job
    from karaoke_app.ass import generate_ass
    from karaoke_app.cli import _create_render_bundle
    from karaoke_app.lyrics_plus import PRESET
    from karaoke_app.style import StyleConfig
    from karaoke_app.themes import apply_render_theme

    with wave.open(str(tmp_path / "audio.wav"), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 8000 * 3)
    logo = tmp_path / "logo.png"
    Image.new("RGB", (100, 30), (255, 0, 0)).save(logo)
    doc, _ = apply_render_theme({"title": "Sample", "source": {"artist": "Test"},
        "video": {"width": 320, "height": 180, "fps": 8},
        "background": {"kind": "cosmic", "loop_seconds": 2},
        "watermark": {"enabled": True, "path": str(logo), "position": position,
                       "opacity": 1, "scale": .18, "margin": .05},
        "media": {"original_audio": "audio.wav", "instrumental_audio": "audio.wav"}}, PRESET)
    transcript = {"segments": [{"start": 2.3, "end": 2.9, "words": [
        {"text": "Hello browser", "start": 2.3, "end": 2.9}]}]}
    ass = generate_ass(transcript, doc["video"], style=StyleConfig.from_dict(doc["style"]), mode="lyrics")
    bundle = tmp_path / "bundle.zip"
    _create_render_bundle(tmp_path, doc, "both", {"lyrics": ass, "karaoke": ass}, bundle, transcript=transcript)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if "playwright" in command:
            return subprocess.CompletedProcess(command, 0)
        return subprocess.run([ffmpeg, "-loglevel", "error", *command[1:]], capture_output=True, text=True, check=True)

    with patch.object(karaoke_job, "WORK_DIR", tmp_path / "remote"), \
         patch.object(karaoke_job, "RENDER_JOB_PATH", bundle), \
         patch.object(karaoke_job, "_run", run), \
         patch.object(karaoke_job, "_probe_duration", return_value=3), \
         patch.object(karaoke_job, "_nvenc_available", return_value=False):
        karaoke_job._render_existing_job({"mode": "both", "archive_path": str(tmp_path / "result.zip")})
    output = tmp_path / "remote/render_result"
    for mode in ("lyrics", "karaoke"):
        for instant in (0.5, 2.5):
            result = subprocess.run([ffmpeg, "-v", "error", "-ss", str(instant),
                "-i", str(output / f"Sample_{mode}.mp4"), "-frames:v", "1", "-f", "rawvideo",
                "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
            pixels = np.frombuffer(result.stdout, dtype=np.uint8).reshape(180, 320, 3)
            assert np.count_nonzero(np.min(pixels, axis=2) > 180) > 10
            y, x = (15, 25) if position == "top_left" else (160, 280)
            assert pixels[y, x, 0] > 200 and pixels[y, x, 1] < 60
        assert (output / "subtitles" / f"Sample_{mode}.ass").is_file()
        assert (output / "intro" / f"intro_{mode}.png").is_file()
    bundled = json.loads((tmp_path / "remote/render_job/job.json").read_text())
    scene = json.loads((tmp_path / "remote/render_job/lyrics.scene.json").read_text())
    assert bundled["intro"]["end"] < scene["groups"][0]["start"] - .35
    assert all("ass=" not in " ".join(command) for command in commands)
    assert not list((tmp_path / "remote/render_job").glob("*-overlay.mov"))
    assert json.loads((tmp_path / "remote/render_job/lyrics.scene.json").read_text())["engine"] == "braccato-1.6.2"


def test_render_browser_overlay_inside_active_asyncio_loop(tmp_path, browser_font, transcript):
    import asyncio

    scene = scene_for(transcript, "lyrics")
    output = tmp_path / "test_async_overlay.mov"

    async def run_in_loop():
        return render_browser_overlay(scene, browser_font, output, duration=0.25)

    result_path = asyncio.run(run_in_loop())
    assert result_path.is_file()
    assert result_path == output


def test_lyrics_deactivation_transition_is_smooth(browser_font):
    transcript = {
        "segments": [
            {
                "start": 1.0,
                "end": 2.0,
                "words": [
                    {"text": "Smooth ", "start": 1.0, "end": 1.5},
                    {"text": "fade", "start": 1.5, "end": 2.0},
                ],
            }
        ]
    }
    scene = build_browser_scene(
        transcript,
        {"width": 640, "height": 360, "fps": 30},
        {"font_size": 48, "margin_h": 40, "margin_v": 60},
        "karaoke",
    )
    scene["groups"][0]["end"] = 10.0
    with browser_scene(scene, browser_font) as page:
        page.evaluate("t => window.renderFrame(t)", 2.84)
        info_before = page.evaluate("""() => {
            const el = document.querySelector('.blyrics-container > div');
            const hl = el.querySelector('.blyrics-word-highlight');
            return {
                state: el.dataset.state,
                hlVis: getComputedStyle(hl).visibility,
                opacity: parseFloat(getComputedStyle(el).opacity),
            };
        }""")
        page.evaluate("t => window.renderFrame(t)", 2.86)
        info_after = page.evaluate("""() => {
            const el = document.querySelector('.blyrics-container > div');
            const hl = el.querySelector('.blyrics-word-highlight');
            return {
                state: el.dataset.state,
                hlVis: getComputedStyle(hl).visibility,
                opacity: parseFloat(getComputedStyle(el).opacity),
            };
        }""")
        assert info_before["hlVis"] == "visible"
        assert info_after["hlVis"] == "visible"
        assert info_before["state"] == "active"
        assert info_after["state"] == "past"
        assert abs(info_after["opacity"] - info_before["opacity"]) < 0.01




def test_dark_ink_reaches_actual_browser(transcript, browser_font):
    scene = build_browser_scene(transcript, {"width": 640, "height": 360, "fps": 12},
                                {"font_size": 40, "lyrics_colors": {"active": "#111111"}}, "lyrics")
    with browser_scene(scene, browser_font) as page:
        page.evaluate("window.renderFrame(1.3)")
        color = page.evaluate("getComputedStyle(document.documentElement)"
                              ".getPropertyValue('--blyrics-lyric-active-color').trim()")
        assert color == "#111111"
        pixels = np.array(Image.open(io.BytesIO(page.screenshot(omit_background=True))).convert("RGBA"))
        visible = pixels[:, :, 3] > 150
        assert visible.any()
        assert pixels[:, :, :3][visible].mean() < 80
