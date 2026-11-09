"""Prepare portable render inputs without choosing a frontend or hosted session."""

import hashlib
import json
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from karaoke_app import ass, job_document, lyrics_file, srt
from karaoke_app.media_transfer import prepare_audio_transfer
from karaoke_app.render_graphics import generate_render_graphics
from karaoke_app.resources import PACKAGE_ROOT
from karaoke_app.style import StyleConfig
from karaoke_app.visual_config import resolve_options


@dataclass(frozen=True)
class RenderRequest:
    """Validated project settings and lyrics, before creating any output files."""

    root: Path
    document: dict[str, Any]
    theme: str
    mode: str
    lyrics: dict[str, Any]


@dataclass(frozen=True)
class RenderSubtitles:
    transcript: dict[str, Any]
    ass_by_mode: dict[str, str]
    srt: str


def prepare_render(
    job_dir: Path, options: dict[str, Any], *, report: Callable[[dict[str, Any]], None] | None = None,
) -> RenderRequest:
    """Resolve overrides and validate required assets without writing or starting Colab."""
    root = job_dir.expanduser().resolve()
    document, theme = resolve_options(root, options)
    if report is not None:
        report(document)
    mode = options.get("mode") or document["render"]["mode"]
    for item in ("karaoke", "lyrics") if mode == "both" else (mode,):
        key = "instrumental_audio" if item == "karaoke" else "original_audio"
        job_document.resolve_job_asset(root, document["media"][key], f"{item} audio")
    if document["background"]["kind"] in {"image", "video"}:
        job_document.resolve_job_asset(root, document["background"]["path"], "background")
    path = job_document.resolve_job_asset(root, document["media"]["lyrics"], "lyrics")
    lyrics = lyrics_file.load_lyrics_file(path, require_words=True)
    return RenderRequest(root, document, theme, mode, lyrics)


def render_subtitles(request: RenderRequest) -> RenderSubtitles:
    """Generate the same timed subtitle content for CLI and notebook renders."""
    document = request.document
    transcript = lyrics_file.lyrics_to_transcript(request.lyrics)
    style = (StyleConfig.from_dict(document["style"], height=document["video"]["height"])
             if document.get("style") else None)
    modes = ("karaoke", "lyrics") if request.mode == "both" else (request.mode,)
    subtitles = {mode: ass.generate_ass(transcript, document["video"], style=style, mode=mode) for mode in modes}
    return RenderSubtitles(transcript, subtitles, srt.generate_srt(transcript))


def create_render_bundle(
    job_dir: Path,
    document: dict[str, Any],
    mode: str,
    ass_by_mode: dict[str, str],
    destination: Path,
    transcript: dict[str, Any] | None = None,
    srt_content: str | None = None,
) -> None:
    """Package graphics, audio and subtitles without modifying the source project."""
    media = document["media"]
    if not isinstance(media, dict):
        raise ValueError("Invalid job media configuration")
    modes = ("karaoke", "lyrics") if mode == "both" else (mode,)
    audio_keys = {"karaoke": "instrumental_audio", "lyrics": "original_audio"}
    required = set()
    background = document["background"]
    if isinstance(background, dict) and background.get("kind") in {"image", "video"}:
        required.add(str(background["path"]))
    bundle_document = json.loads(json.dumps(document))
    watermark = bundle_document.get("watermark")
    watermark_file = None
    if isinstance(watermark, dict) and watermark.get("enabled", True):
        watermark_file = job_document.resolve_watermark_path(job_dir, watermark.get("path"))
        watermark["path"] = f"watermark{watermark_file.suffix.lower()}"

    with tempfile.TemporaryDirectory(prefix="render-graphics-") as directory:
        graphics = Path(directory)
        audio_files = {}
        for item in modes:
            key = audio_keys[item]
            source = job_document.resolve_job_asset(job_dir, str(media[key]), f"{item} audio")
            audio = prepare_audio_transfer(source, graphics / "audio-transfer")
            with audio.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            relative = f"media/{digest}{audio.suffix.lower()}"
            audio_files[relative] = audio
            bundle_document["media"][key] = relative
        timing = generate_render_graphics(job_dir, document, modes, graphics, transcript)
        bundle_document["intro"] = timing or {"enabled": False}
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr(
                job_document.STATE_FILENAME, json.dumps(bundle_document, ensure_ascii=False, indent=2) + "\n",
            )
            if background.get("kind") == "cosmic":
                cosmic_module = PACKAGE_ROOT / "cosmic_background.py"
                if not cosmic_module.is_file():
                    raise FileNotFoundError(f"Missing cosmic background generator module: {cosmic_module}")
                archive.write(cosmic_module, "cosmic_background.py")
            if (document.get("style") or {}).get("lyrics_effect") == "word-synced":
                from karaoke_app.browser_lyrics import ASSETS, build_browser_scene
                from karaoke_app.lyrics_plus import switzer_font

                font = switzer_font()
                archive.write(font, f"fonts/{font.name}")
                archive.write(font.with_name("Switzer-FFL.txt"), "fonts/Switzer-FFL.txt")
                if transcript is None:
                    raise ValueError("Plus rendering requires the timed transcript")
                archive.write(PACKAGE_ROOT / "browser_lyrics.py", "browser_lyrics.py")
                for asset_root in (ASSETS / "braccato", ASSETS / "browser_lyrics"):
                    for asset in sorted(asset_root.rglob("*")):
                        if asset.is_file():
                            archive.write(asset, f"browser_assets/{asset.relative_to(ASSETS).as_posix()}")
                for item in modes:
                    scene = build_browser_scene(transcript, document["video"], document["style"], item)
                    archive.writestr(f"{item}.scene.json", json.dumps(scene, ensure_ascii=False))
            if srt_content:
                archive.writestr("lyrics.srt", srt_content)
            elif (job_dir / "lyrics.srt").is_file():
                archive.write(job_dir / "lyrics.srt", "lyrics.srt")
            for item in modes:
                archive.writestr(f"{item}.ass", ass_by_mode[item])
            for relative, audio in sorted(audio_files.items()):
                archive.write(audio, relative)
            for relative in sorted(required):
                archive.write(job_document.resolve_job_asset(job_dir, relative, relative), relative)
            if watermark_file is not None:
                archive.write(watermark_file, bundle_document["watermark"]["path"])
            for graphic in sorted(graphics.rglob("*.png")):
                archive.write(graphic, f"graphics/{graphic.relative_to(graphics).as_posix()}")
