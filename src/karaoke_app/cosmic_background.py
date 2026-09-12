"""Deterministic cosmic dust backgrounds shared by local previews and Colab renders."""

import logging
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter

LOGGER = logging.getLogger(__name__)


def normalize_cosmic_background(value: dict[str, Any]) -> dict[str, Any]:
    """Validate the complete cosmic background section, filling reproducible defaults."""
    defaults = {
        "kind": "cosmic", "color": "#BC737D", "secondary_color": "#E5A28E", "base_color": "#08090C",
        "overlay_opacity": 0.0, "opacity": 0.85, "speed": 0.35, "turbulence": 0.8,
        "density": 0.55, "detail": 0.65, "brightness": 1.0, "contrast": 1.4,
        "scale": 3.0, "seed": 7, "loop_seconds": 20.0, "appearance": "cosmic",
    }
    unknown = set(value) - defaults.keys()
    if unknown:
        raise ValueError(f"background: unknown keys: {', '.join(sorted(unknown))}")
    result = defaults | value
    if result["kind"] != "cosmic":
        raise ValueError("background.kind must be cosmic")
    for key in ("color", "secondary_color", "base_color"):
        color = result[key]
        if not isinstance(color, str) or not re.fullmatch(r"#?[0-9a-fA-F]{6}", color):
            raise ValueError(f"background.{key} must be an RGB hex color")
        result[key] = f"#{color.lstrip('#').upper()}"
    if result["appearance"] not in ("cosmic", "fluid"):
        raise ValueError("background.appearance must be cosmic or fluid")
    ranges = {
        "overlay_opacity": (0, 1), "opacity": (0, 1), "speed": (0, 3), "turbulence": (0, 2),
        "density": (0, 1), "detail": (0, 1), "brightness": (0, 3), "contrast": (0.2, 3),
        "scale": (1, 8), "loop_seconds": (2, 120),
    }
    for key, (low, high) in ranges.items():
        number = result[key]
        if type(number) not in (int, float) or not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f"background.{key} must be between {low} and {high}")
    if type(result["seed"]) is not int or not 0 <= result["seed"] <= 2**32 - 1:
        raise ValueError("background.seed must be an integer between 0 and 4294967295")
    return result


def _noise(x: np.ndarray, y: np.ndarray, seed: int) -> np.ndarray:
    ix, iy = np.floor(x), np.floor(y)
    fx, fy = x - ix, y - iy
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    ix, iy = ix.astype(np.int64).astype(np.uint32), iy.astype(np.int64).astype(np.uint32)

    def corner(dx: int, dy: int) -> np.ndarray:
        n = (ix + dx) * np.uint32(374761393) + (iy + dy) * np.uint32(668265263) + np.uint32(seed % 2**32)
        n = (n ^ (n >> 13)) * np.uint32(1274126177)
        return (n ^ (n >> 16)).astype(np.float64) / 4294967295

    return (corner(0, 0) * (1 - fx) + corner(1, 0) * fx) * (1 - fy) + (
        corner(0, 1) * (1 - fx) + corner(1, 1) * fx
    ) * fy


def _cloud_noise(x: np.ndarray, y: np.ndarray, seed: int, octaves: int = 5) -> np.ndarray:
    result = np.zeros_like(x)
    for octave in range(octaves):
        frequency = 2**octave
        result += _noise(x * frequency, y * frequency, seed + octave * 41) * 0.5 ** (octave + 1)
    return result / (1 - 0.5**octaves)


class CosmicBackground:
    """Render translucent flowing veils with multiscale granular dust."""

    def __init__(self, background: dict[str, Any], width: int, height: int):
        self.config = normalize_cosmic_background(background)
        if type(width) is not int or type(height) is not int or width < 2 or height < 2:
            raise ValueError("Background dimensions must be integers of at least 2 pixels")
        self.size = (width, height)
        # A fixed field resolution keeps motion consistent across preview/output sizes.
        field_width = 240 if self.config["appearance"] == "fluid" else 480
        field_height = max(2, round(field_width * height / width))
        self.y, self.x = np.mgrid[0:field_height, 0:field_width].astype(np.float64)
        self.x = (self.x / field_width - 0.5) * width / height * self.config["scale"]
        self.y = (self.y / field_height - 0.5) * self.config["scale"]
        self.grain_margin = math.ceil(self.config["speed"] * 24) + 2
        rng = np.random.default_rng(self.config["seed"])
        grain_size = (height + 2 * self.grain_margin, width + 2 * self.grain_margin)
        # A skewed distribution gives fine dust bright flecks and dark gaps, instead of uniform TV noise.
        fine = rng.random(grain_size).astype(np.float32) ** 5
        coarse = Image.fromarray((rng.random((max(2, height // 3), max(2, width // 3))) * 255).astype(np.uint8))
        coarse = coarse.resize((grain_size[1], grain_size[0]), Image.Resampling.BILINEAR)
        grain = np.clip(fine * 0.75 + np.array(coarse, dtype=np.float32) / 255 * 0.25, 0, 1)
        self.grain = Image.fromarray((grain * 255).astype(np.uint8))

    def frame(self, seconds: float) -> Image.Image:
        """Return an RGB frame; motion closes seamlessly after loop_seconds."""
        cfg = self.config
        angle = 2 * math.pi * (seconds % cfg["loop_seconds"]) / cfg["loop_seconds"]
        radius = cfg["speed"] * cfg["loop_seconds"] / (2 * math.pi) * 0.13
        x = self.x + radius * math.sin(angle)
        y = self.y + radius * (math.cos(angle) - 1)
        seed = cfg["seed"]
        flow_x = radius * (math.cos(angle) - 1)
        flow_y = radius * math.sin(angle)
        warp_x = _cloud_noise(x + 4.2 + flow_x, y + 1.7 - flow_y, seed, 3) - 0.5
        warp_y = _cloud_noise(x - 2.3 - flow_y, y + 6.1 + flow_x, seed + 83, 3) - 0.5
        x = x + cfg["turbulence"] * 1.4 * warp_x
        y = y + cfg["turbulence"] * 1.4 * warp_y
        if cfg["appearance"] == "fluid":
            return self._fluid_frame(x, y)
        phase = (seed % 997) * 0.17
        fold = y + 0.65 * np.sin(x * 1.15 + phase) + 0.4 * np.sin(x * 2.1 - y * 0.7)
        haze = _cloud_noise(x * 0.65, y * 0.65, seed + 197, 2)
        width = (0.16 + cfg["density"] * 0.4) * (0.55 + haze)
        ribbon = np.exp(-((fold - 0.55) / width) ** 2)
        upper_fold = y + 0.85 * np.sin(x * 0.85 + phase + 0.9) + 1.1
        ribbon += np.exp(-(upper_fold / (width * 1.4)) ** 2) * 0.65
        glow = np.exp(-((x - 1.8) ** 2 * 0.5 + (y + 1.1) ** 2 * 1.4))
        veil = ribbon * (0.2 + 0.6 * haze) + haze * 0.16 + glow * 0.32
        density = np.clip(veil * (0.5 + cfg["density"]), 0, 1) ** cfg["contrast"]
        light = np.clip(ribbon * haze * 0.7, 0, 1)[..., None]

        def rgb(key: str) -> np.ndarray:
            color = cfg[key].lstrip("#")
            return np.array([int(color[i:i + 2], 16) for i in (0, 2, 4)])

        tint = rgb("color") * (1 - light) + rgb("secondary_color") * light
        alpha = (density * cfg["opacity"])[..., None]
        pixels = (rgb("base_color") * (1 - alpha) + tint * alpha * cfg["brightness"])
        smooth = Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2))
        smooth = smooth.resize(self.size, Image.Resampling.LANCZOS)
        pixels = np.array(smooth, dtype=np.float32)
        shift = cfg["speed"] * 24
        grain = self.grain.transform(
            self.size, Image.Transform.AFFINE,
            (1, 0, self.grain_margin + shift * math.sin(angle),
             0, 1, self.grain_margin + shift * math.cos(angle)),
            Image.Resampling.BILINEAR,
        )
        # Dust also catches a little light in the dark gaps, as in the reference's granular veil.
        dust = np.array(grain, dtype=np.float32)[..., None] / 255
        emission = pixels - rgb("base_color")
        pixels += emission * cfg["detail"] * (dust - 0.25) * 1.8
        pixels += rgb("color") * cfg["opacity"] * cfg["brightness"] * cfg["detail"] * dust**2 * 0.22
        pixels *= 1 - cfg["overlay_opacity"]
        return Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8))

    def _fluid_frame(self, x: np.ndarray, y: np.ndarray) -> Image.Image:
        cfg = self.config
        blend = (np.sin(x * 0.7 + np.sin(y * 0.8)) + 1) / 2
        colors = [np.array([int(cfg[key][i:i + 2], 16) for i in (1, 3, 5)])
                  for key in ("color", "secondary_color")]
        pixels = colors[0] * blend[..., None] + colors[1] * (1 - blend[..., None])
        haze = 0.55 + 0.45 * _cloud_noise(x, y, cfg["seed"], 2)
        pixels *= haze[..., None] * cfg["brightness"] * cfg["opacity"] * (1 - cfg["overlay_opacity"])
        # Bound every channel so bright artwork cannot wash out white sung words.
        pixels = np.clip(pixels, 0, 110)
        frame = Image.fromarray(pixels.astype(np.uint8)).filter(ImageFilter.GaussianBlur(12))
        return frame.resize(self.size, Image.Resampling.BILINEAR)


def render_cosmic_video(
    background: dict[str, Any], video: dict[str, int], destination: Path,
    *, duration: float | None = None, start: float = 0, ffmpeg: str | None = None,
) -> Path:
    """Encode the same procedural frames for previews and final-render background loops."""
    renderer = CosmicBackground(background, video["width"], video["height"])
    fps = video["fps"]
    if type(fps) is not int or not 1 <= fps <= 120:
        raise ValueError("Background video fps must be an integer between 1 and 120")
    duration = renderer.config["loop_seconds"] if duration is None else duration
    if not math.isfinite(duration) or duration <= 0 or duration > 120:
        raise ValueError("Background duration must be between 0 (exclusive) and 120 seconds")
    if not math.isfinite(start) or start < 0:
        raise ValueError("Background start must be finite and non-negative")
    if video["width"] % 2 or video["height"] % 2:
        raise ValueError("Background video dimensions must be even for H.264")
    executable = ffmpeg or shutil.which("ffmpeg")
    if executable is None:
        import imageio_ffmpeg

        executable = imageio_ffmpeg.get_ffmpeg_exe()
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame_count = max(1, round(duration * fps))
    LOGGER.info("Generating cosmic background: %s (%s frames)", destination, frame_count)
    with tempfile.TemporaryDirectory(prefix="cosmic-", dir=destination.parent) as temporary:
        output = Path(temporary) / "background.mp4"
        command = [
            executable, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{video['width']}x{video['height']}", "-r", str(fps), "-i", "pipe:0",
            "-an", "-c:v", "libx264", "-preset", "fast", "-tune", "grain", "-crf", "16", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(output),
        ]
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors)
            try:
                for frame in range(frame_count):
                    # Exactly one temporal period even when duration * fps is fractional.
                    seconds = start + frame * duration / frame_count
                    process.stdin.write(renderer.frame(seconds).tobytes())
                    if (frame + 1) % max(1, frame_count // 4) == 0:
                        LOGGER.info("Cosmic background: %.0f%%", (frame + 1) / frame_count * 100)
                process.stdin.close()
                if process.wait() != 0:
                    errors.seek(0)
                    raise RuntimeError(f"Background encoding failed: {errors.read().decode(errors='replace')}")
            except BaseException:
                if process.poll() is None:
                    process.kill()
                process.wait()
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
                raise
        output.replace(destination)
    return destination
