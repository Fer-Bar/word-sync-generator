"""Frame-accurate capture of the original Braccato word animations in Chromium."""

import asyncio
import concurrent.futures
import json
import logging
import math
import mimetypes
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

LOGGER = logging.getLogger(__name__)
ASSETS = Path(__file__).parent / "assets"


def build_browser_scene(transcript: dict[str, Any], video: dict[str, int], style: dict[str, Any], mode: str) -> dict:
    """Convert canonical timings to Braccato parts and mode-specific line groups."""
    from karaoke_app.word_synced import _fixed_pages, _groups

    if mode not in ("lyrics", "karaoke"):
        raise ValueError("Browser lyrics mode must be lyrics or karaoke")
    source = (_groups if mode == "karaoke" else _fixed_pages)(transcript.get("segments", []))
    lyrics, groups = [], []
    for group in source:
        indices = []
        for line in group["lines"]:
            words = line["words"]
            parts = []
            for index, word in enumerate(words):
                fragments = word.get("timing") or [word]
                for fragment_index, fragment in enumerate(fragments):
                    text = str(fragment["text"])
                    if fragment_index == 0:
                        text = text.lstrip()
                    if fragment_index == len(fragments) - 1:
                        text = text.rstrip() + (" " if index < len(words) - 1 else "")
                    part = {
                        "startTimeMs": fragment["start"] * 1000,
                        "durationMs": max(1, (fragment["end"] - fragment["start"]) * 1000),
                        "words": text,
                    }
                    if word.get("isBackground") or line.get("isBackground"):
                        part["isBackground"] = True
                    parts.append(part)
            start = min(word["start"] for word in words)
            end = max(word["end"] for word in words)
            indices.append(len(lyrics))
            lyric_record = {
                "startTimeMs": start * 1000,
                "durationMs": max(1, (end - start) * 1000),
                "words": "".join(p["words"] for p in parts),
                "parts": parts,
            }
            if line.get("isBackground"):
                lyric_record["isBackground"] = True
            lyrics.append(lyric_record)
        groups.append({"start": group["start"] / 100, "end": group["end"] / 100, "indices": indices})
    margin_h = min(style.get("margin_h", 70), video["width"] * .2)
    configured_mv = style.get("margin_v")
    if configured_mv is None:
        margin_v = round(video["height"] * .22)
    else:
        margin_v = max(configured_mv, round(video["height"] * .12))
    margin_v = min(margin_v, round(video["height"] * .30))
    return {"version": 1, "engine": "braccato-1.6.2", "mode": mode, "width": video["width"],
            "height": video["height"], "fps": video["fps"], "font_size": style["font_size"],
            "margin": margin_h, "margin_v": margin_v, "lyrics": lyrics, "groups": groups,
            "ink_color": (style.get("lyrics_colors") or {}).get("active", "#FFFFFF")}


@contextmanager
def browser_scene(scene: dict, font: Path, *, assets: Path = ASSETS):
    """Load only packaged assets through intercepted requests, with no network server."""
    from playwright.sync_api import Error, sync_playwright

    def serve(route):
        requested = urlparse(route.request.url)
        if requested.hostname != "lyrics.invalid":
            route.abort()
            return
        name = requested.path.lstrip("/")
        if name == "font.otf":
            path = font
        elif name == "index.html":
            path = assets / "browser_lyrics" / name
        else:
            path = (assets / name).resolve()
            if not path.is_relative_to(assets.resolve()):
                route.abort()
                return
        if not path.is_file():
            route.fulfill(status=404, body="Missing render asset")
            return
        content_type = "text/javascript" if path.suffix == ".js" else mimetypes.guess_type(path.name)[0]
        route.fulfill(body=path.read_bytes(), content_type=content_type or "application/octet-stream")

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        except Error as error:
            raise RuntimeError("Chromium is required: run uv run playwright install --with-deps chromium") from error
        try:
            page = browser.new_page(viewport={"width": scene["width"], "height": scene["height"]},
                                    device_scale_factor=1)
            page.route("**/*", serve)
            page.goto("http://lyrics.invalid/index.html")
            page.wait_for_function("window.moduleReady === true")
            page.evaluate("data => window.setup(data)", scene)
            page.wait_for_function("window.ready === true")
            yield page
        finally:
            browser.close()


def _render_browser_overlay_sync(
    scene: dict,
    font: Path,
    output: Path,
    *,
    duration: float,
    start: float = 0,
    assets: Path = ASSETS,
    ffmpeg: str | None = None,
) -> Path:
    """Encode a transparent, lossless overlay sampled at the exact output frame times."""
    if not math.isfinite(duration) or duration <= 0 or not math.isfinite(start) or start < 0:
        raise ValueError("Overlay duration must be positive and start non-negative")
    fps = scene["fps"]
    if type(fps) is not int or not 1 <= fps <= 120:
        raise ValueError("Overlay fps must be an integer between 1 and 120")
    executable = ffmpeg or shutil.which("ffmpeg")
    if executable is None:
        import imageio_ffmpeg

        executable = imageio_ffmpeg.get_ffmpeg_exe()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    count = max(1, math.ceil(duration * fps))
    with tempfile.TemporaryDirectory(prefix="lyrics-overlay-", dir=output.parent) as directory:
        destination = Path(directory) / "overlay.mov"
        with browser_scene(scene, font, assets=assets) as page, tempfile.TemporaryFile() as errors:
            command = [
                executable,
                "-nostdin",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "image2pipe",
                "-framerate",
                str(fps),
                "-vcodec",
                "png",
                "-i",
                "pipe:0",
                "-an",
                "-c:v",
                "qtrle",
                "-pix_fmt",
                "argb",
                str(destination),
            ]
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors)
            try:
                for index in range(count):
                    page.evaluate("time => window.renderFrame(time)", start + index / fps)
                    process.stdin.write(page.screenshot(omit_background=True, animations="allow"))
                    if (index + 1) % max(1, count // 4) == 0:
                        LOGGER.info("Braccato %s: %.0f%%", scene["mode"], (index + 1) * 100 / count)
                process.stdin.close()
                if process.wait() != 0:
                    errors.seek(0)
                    raise RuntimeError(f"Lyrics overlay encoding failed: {errors.read().decode(errors='replace')}")
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
        destination.replace(output)
    return output


def render_browser_overlay(
    scene: dict,
    font: Path,
    output: Path,
    *,
    duration: float,
    start: float = 0,
    assets: Path = ASSETS,
    ffmpeg: str | None = None,
) -> Path:
    """Encode a transparent, lossless overlay, dispatching to a worker thread if an asyncio loop is running."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        LOGGER.info("Active asyncio loop detected; dispatching Playwright rendering to worker thread.")
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(
                _render_browser_overlay_sync,
                scene,
                font,
                output,
                duration=duration,
                start=start,
                assets=assets,
                ffmpeg=ffmpeg,
            ).result()

    return _render_browser_overlay_sync(
        scene, font, output, duration=duration, start=start, assets=assets, ffmpeg=ffmpeg
    )


def render_bundled_overlay(job_dir: Path, mode: str, output: Path, duration: float) -> Path:
    """Render a portable scene shipped by the CLI using the same capture path as previews."""
    scene = json.loads((job_dir / f"{mode}.scene.json").read_text(encoding="utf-8"))
    return render_browser_overlay(scene, job_dir / "fonts/Switzer-Semibold.otf", output,
                                  duration=duration, assets=job_dir / "browser_assets")
