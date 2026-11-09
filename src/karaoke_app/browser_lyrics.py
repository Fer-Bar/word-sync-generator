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
import time
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
            "ink_color": (style.get("lyrics_colors") or {}).get("active", "#FFFFFF"),
            "inactive_color": (style.get("lyrics_colors") or {}).get("inactive") if mode == "karaoke" else None}


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
    with tempfile.TemporaryDirectory(prefix="lyrics-overlay-", dir=output.parent) as directory:
        destination = Path(directory) / "overlay.mov"
        command = [
            executable, "-nostdin", "-y", "-loglevel", "error",
            "-f", "image2pipe", "-framerate", str(fps), "-vcodec", "png", "-i", "pipe:0",
            "-an", "-c:v", "qtrle", "-pix_fmt", "argb", str(destination),
        ]
        _encode_browser_video_sync(scene, font, command, duration=duration, start=start, assets=assets)
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
        LOGGER.debug("Active asyncio loop detected; dispatching Playwright rendering to worker thread.")
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


def frame_has_lyrics(scene: dict, seconds: float) -> bool:
    """Mirror the player's visibility windows, including page lead and exit tails."""
    groups = scene["groups"]
    if not groups or seconds < groups[0]["start"] - .35 or seconds > groups[-1]["end"] + .85:
        return False
    if scene["mode"] == "karaoke":
        return True
    selected = groups[0]
    for group in groups:
        if seconds >= group["start"] - .35:
            selected = group
    return seconds <= selected["end"] + .35


def _write_browser_frames(page, scene, stream, *, duration, start=0, metrics=None):
    fps = scene["fps"]
    count = max(1, math.ceil(duration * fps))
    blank = None
    last_progress = time.perf_counter()
    stats = metrics if metrics is not None else {}
    stats.update(frames=count, captured_frames=0, reused_blank_frames=0,
                 draw_seconds=0.0, screenshot_seconds=0.0, pipe_seconds=0.0)
    for index in range(count):
        instant = start + index / fps
        visible = frame_has_lyrics(scene, instant)
        if not visible and blank is not None:
            png = blank
            stats["reused_blank_frames"] += 1
        else:
            began = time.perf_counter()
            page.evaluate("time => window.renderFrame(time)", instant)
            stats["draw_seconds"] += time.perf_counter() - began
            began = time.perf_counter()
            png = page.screenshot(omit_background=True, animations="allow")
            stats["screenshot_seconds"] += time.perf_counter() - began
            stats["captured_frames"] += 1
            if not visible:
                blank = png
        began = time.perf_counter()
        stream.write(png)
        stats["pipe_seconds"] += time.perf_counter() - began
        now = time.perf_counter()
        if index == 0 or now - last_progress >= .5 or index + 1 == count:
            last_progress = now
            LOGGER.info("Frame progress", extra={"user_event": {"kind": "stage", "id": "frames",
                "parent": f"render_{scene['mode']}",
                "label": f"Drawing {scene['mode']} frames", "completed": index + 1, "total": count,
                "detail": f"{index + 1:,}/{count:,} frames",
                "reset": index == 0, "state": "done" if index + 1 == count else "running"}})


def _encode_browser_video_sync(scene, font, command, *, duration, start=0, assets=ASSETS, metrics=None):
    if not math.isfinite(duration) or duration <= 0 or not math.isfinite(start) or start < 0:
        raise ValueError("Video duration must be positive and start non-negative")
    if type(scene["fps"]) is not int or not 1 <= scene["fps"] <= 120:
        raise ValueError("Video fps must be an integer between 1 and 120")
    began = time.perf_counter()
    with browser_scene(scene, font, assets=assets) as page, tempfile.TemporaryFile() as errors:
        if metrics is not None:
            metrics["browser_start_seconds"] = time.perf_counter() - began
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors, stdout=subprocess.DEVNULL)
        try:
            try:
                _write_browser_frames(page, scene, process.stdin, duration=duration, start=start, metrics=metrics)
                process.stdin.close()
            except BrokenPipeError:
                # FFmpeg may reject an encoder before consuming the first frame.
                pass
            began = time.perf_counter()
            LOGGER.info("Finalizing video", extra={"user_event": {"kind": "stage", "id": "encoder_drain",
                "parent": f"render_{scene['mode']}",
                "label": f"Finalizing {scene['mode']} video"}})
            returncode = process.wait()
            LOGGER.info("Encoder finished", extra={"user_event": {"kind": "stage", "id": "encoder_drain",
                "parent": f"render_{scene['mode']}",
                "label": f"Finalizing {scene['mode']} video", "state": "done" if returncode == 0 else "stopped"}})
            if metrics is not None:
                metrics["encoder_drain_seconds"] = time.perf_counter() - began
            if returncode != 0:
                errors.seek(0)
                details = errors.read().decode(errors="replace")
                LOGGER.debug("Video encoding failed: %s", details)
                raise subprocess.CalledProcessError(process.returncode, command, stderr=details)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            try:
                process.stdin.close()
            except BrokenPipeError:
                pass


def encode_bundled_video(job_dir: Path, mode: str, command: list[str], duration: float, *, metrics=None) -> None:
    """Stream transparent PNGs directly into the final compositor, without an intermediate MOV."""
    scene = json.loads((job_dir / f"{mode}.scene.json").read_text(encoding="utf-8"))
    kwargs = {"duration": duration, "assets": job_dir / "browser_assets", "metrics": metrics}
    font = job_dir / "fonts/Switzer-Semibold.otf"
    # Colab's notebook kernel already runs asyncio; Playwright owns its worker thread.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(_encode_browser_video_sync, scene, font, command, **kwargs).result()
