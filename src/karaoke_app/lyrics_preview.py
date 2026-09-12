"""Local FFmpeg samples of the actual Plus subtitle renderer, with original audio."""

import argparse
import json
import logging
import math
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg

from karaoke_app.ass import generate_ass
from karaoke_app.browser_lyrics import build_browser_scene, render_browser_overlay
from karaoke_app.cosmic_background import render_cosmic_video
from karaoke_app.job_document import load_job_document, resolve_job_asset
from karaoke_app.lyrics_file import load_lyrics_file, lyrics_to_transcript
from karaoke_app.lyrics_plus import switzer_font
from karaoke_app.style import StyleConfig
from karaoke_app.themes import apply_render_theme
from karaoke_app.visual_config import BACKGROUND_STYLES, apply_visual_options


def run_lyrics_preview(argv: list[str]) -> Path:
    """Create a local video sample without Colab, transcription or editing the job."""
    parser = argparse.ArgumentParser(prog="karaoke preview", description=__doc__)
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--mode", choices=("lyrics", "karaoke"), default="lyrics")
    parser.add_argument("--background-style", choices=BACKGROUND_STYLES)
    parser.add_argument("--cover", type=Path)
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--duration", type=float, default=10)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args(argv)
    if not math.isfinite(args.start) or args.start < 0:
        raise ValueError("--start must be finite and non-negative")
    if not math.isfinite(args.duration) or not 0 < args.duration <= 120:
        raise ValueError("--duration must be between 0 and 120 seconds")
    if not 180 <= args.height <= 2160 or args.height % 2:
        raise ValueError("--height must be an even integer between 180 and 2160")
    output = args.output.expanduser().resolve()
    if output.suffix.lower() != ".mp4":
        raise ValueError("Preview output must end in .mp4")
    if any(output.with_suffix(suffix).exists() for suffix in (".mp4", ".ass", ".json")):
        raise FileExistsError(f"Preview already exists: {output}")
    root = args.job_dir.expanduser().resolve()
    document = load_job_document(root)
    video = document["video"]
    video["width"] = round(video["width"] * args.height / video["height"] / 2) * 2
    video["height"] = args.height
    document = apply_visual_options(document, visual_style="plus",
                                    background_style=args.background_style, cover=args.cover)
    if args.seed is not None:
        document, _ = apply_render_theme(document, "job", args.seed)
    if document["background"]["kind"] != "cosmic":
        raise ValueError("Preview requires --background-style fluid or cosmic-sand for a static job")
    transcript = lyrics_to_transcript(load_lyrics_file(resolve_job_asset(root, document["media"]["lyrics"], "lyrics"),
                                                     require_words=True))
    audio_key = "original_audio" if args.mode == "lyrics" else "instrumental_audio"
    audio = resolve_job_asset(root, document["media"][audio_key], "audio")
    font = switzer_font()
    ass = generate_ass(transcript, video, style=StyleConfig.from_dict(document["style"]), mode=args.mode)
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory(prefix="lyrics-preview-") as directory:
        temporary = Path(directory)
        (temporary / "lyrics.ass").write_text(ass, encoding="utf-8")
        (temporary / font.name).write_bytes(font.read_bytes())
        render_cosmic_video(document["background"], video, temporary / "background.mp4",
                            duration=args.duration, start=args.start, ffmpeg=ffmpeg)
        scene = build_browser_scene(transcript, video, document["style"], args.mode)
        overlay = render_browser_overlay(scene, font, temporary / "lyrics.mov",
                                         duration=args.duration, start=args.start, ffmpeg=ffmpeg)
        subprocess.run([
            ffmpeg, "-nostdin", "-v", "error", "-i", str(temporary / "background.mp4"),
            "-ss", str(args.start), "-i", str(audio), "-i", str(overlay), "-filter_complex",
            "[0:v][2:v]overlay=0:0:shortest=1[v]",
            "-map", "[v]", "-map", "1:a:0", "-t", str(args.duration), "-shortest",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-movflags", "+faststart", str(temporary / "preview.mp4"),
        ], cwd=temporary, check=True)
        # Copy only after successful encoding, keeping partial files out of the output folder.
        output.write_bytes((temporary / "preview.mp4").read_bytes())
    output.with_suffix(".ass").write_text(ass, encoding="utf-8")
    output.with_suffix(".json").write_text(json.dumps({
        "renderer": "braccato-1.6.2", "visual_style": "plus", "mode": args.mode, "start": args.start,
        "duration": args.duration, "video": video, "style": document["style"],
        "background": document["background"]}, indent=2) + "\n", encoding="utf-8")
    logging.getLogger(__name__).info("Lyrics preview created: %s", output)
    return output
