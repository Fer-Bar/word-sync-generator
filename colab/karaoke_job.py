import json
import logging
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

CONFIG_PATH = Path("/content/karaoke_job.json")
STATUS_PATH = Path("/content/karaoke_status.json")
WORK_DIR = Path("/content/karaoke_workspace")
LOGGER = logging.getLogger(__name__)
MAX_LYRIC_LINES_PER_PAGE = 3
PAGE_BREAK_SILENCE_SECONDS = 1.5
MAX_PAGE_DURATION_SECONDS = 15.0
PAGE_LEAD_SECONDS = 0.35
PAGE_TAIL_SECONDS = 0.35
PAGE_FADE_MILLISECONDS = 150


def main() -> None:
    """Generate karaoke artifacts inside a Colab runtime."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    _require_commands("ffmpeg", "ffprobe")

    source_path, metadata = _acquire_source(config)
    mixture_path = _prepare_mixture(source_path)
    vocals_path, instrumental_path = _separate_vocals(mixture_path, config["demucs_model"])
    transcript = _transcribe(vocals_path, metadata, config)

    safe_title = _safe_filename(metadata["title"])
    output_dir = WORK_DIR / safe_title
    output_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = output_dir / f"{safe_title}_transcript.json"
    ass_path = output_dir / f"{safe_title}_karaoke.ass"
    transcript_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_ass(transcript, ass_path, config["video"])

    karaoke_video = output_dir / f"{safe_title}_karaoke.mp4"
    lyrics_video = output_dir / f"{safe_title}_lyrics.mp4"
    instrumental_flac = output_dir / f"{safe_title}_instrumental.flac"
    _render_video(instrumental_path, ass_path, karaoke_video, config)
    _render_video(source_path, ass_path, lyrics_video, config)
    _run(["ffmpeg", "-y", "-i", str(instrumental_path), "-c:a", "flac", str(instrumental_flac)])

    manifest = _build_manifest(config, metadata, output_dir)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _create_archive(output_dir, Path(config["archive_path"]))
    LOGGER.info("Pipeline completed: %s", config["archive_path"])


def _acquire_source(config: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    source = config["source"]
    if source["kind"] == "file":
        source_path = Path(source["value"])
        if not source_path.is_file():
            raise FileNotFoundError(f"Uploaded source not found: {source_path}")
        return source_path, {
            "title": source.get("name") or source_path.stem,
            "uploader": None,
            "duration": _probe_duration(source_path),
            "source_url": None,
        }

    _ensure_deno()
    url = source["value"]
    command = _yt_dlp_base(config)
    try:
        metadata_result = _run([*command, "--dump-single-json", "--skip-download", url], capture_output=True)
        template = WORK_DIR / "source.%(ext)s"
        download_result = _run(
            [
                *command,
                "--no-simulate",
                "-f",
                "bestaudio/best",
                "--output",
                str(template),
                "--print",
                "after_move:filepath",
                url,
            ],
            capture_output=True,
        )
    except subprocess.CalledProcessError as error:
        details = (error.stderr or error.stdout or str(error)).strip()
        raise RuntimeError(f"yt-dlp failed: {details}") from error

    raw_metadata = json.loads(metadata_result.stdout)
    reported_paths = [Path(line.strip()) for line in download_result.stdout.splitlines() if line.strip()]
    source_path = next((path for path in reversed(reported_paths) if path.is_file()), None)
    if source_path is None:
        details = download_result.stderr.strip() or download_result.stdout.strip() or "no filepath reported"
        raise RuntimeError(f"yt-dlp did not produce a usable audio file: {details}")
    return source_path, {
        "title": raw_metadata.get("title") or "karaoke",
        "uploader": raw_metadata.get("uploader"),
        "duration": raw_metadata.get("duration") or _probe_duration(source_path),
        "source_url": raw_metadata.get("webpage_url") or url,
    }


def _yt_dlp_base(config: dict[str, Any]) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-config",
        "--no-playlist",
        "--remote-components",
        "ejs:github",
        "--js-runtimes",
        "deno",
    ]
    cookies_path = config.get("cookies_path")
    if cookies_path and Path(cookies_path).is_file():
        command.extend(["--cookies", cookies_path])
    return command


def _ensure_deno() -> None:
    if shutil.which("deno"):
        return
    installer = Path("/tmp/install-deno.sh")
    LOGGER.info("Installing the Deno runtime required by yt-dlp")
    urllib.request.urlretrieve("https://deno.land/install.sh", installer)
    _run(["sh", str(installer)])
    deno_bin = Path.home() / ".deno" / "bin"
    os.environ["PATH"] = f"{deno_bin}:{os.environ['PATH']}"
    if not shutil.which("deno"):
        raise RuntimeError("Deno installation failed")


def _prepare_mixture(source_path: Path) -> Path:
    mixture_path = WORK_DIR / "mixture.wav"
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            str(mixture_path),
        ]
    )
    return mixture_path


def _separate_vocals(mixture_path: Path, model_name: str) -> tuple[Path, Path]:
    separated_dir = WORK_DIR / "separated"
    _run(
        [
            sys.executable,
            "-m",
            "demucs",
            "--name",
            model_name,
            "--two-stems",
            "vocals",
            "--out",
            str(separated_dir),
            str(mixture_path),
        ]
    )
    track_dir = separated_dir / model_name / mixture_path.stem
    vocals_path = track_dir / "vocals.wav"
    instrumental_path = track_dir / "no_vocals.wav"
    if not vocals_path.is_file() or not instrumental_path.is_file():
        raise RuntimeError("Demucs did not produce the expected vocal stems")
    return vocals_path, instrumental_path


def _transcribe(vocals_path: Path, metadata: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    import torch
    from faster_whisper import WhisperModel

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    if device == "cpu":
        LOGGER.warning("CUDA is unavailable; transcription will run on CPU")

    model = WhisperModel(
        config["whisper_model"],
        device=device,
        compute_type=compute_type,
        download_root=str(WORK_DIR / "models"),
    )
    language = None if config["language"] == "auto" else config["language"]
    segments, info = model.transcribe(
        str(vocals_path),
        language=language,
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={
            "threshold": 0.25,
            "min_silence_duration_ms": 500,
            "speech_pad_ms": 250,
        },
        condition_on_previous_text=False,
    )

    words = []
    for segment in segments:
        for word in segment.words or []:
            text = word.word.strip()
            if not text or word.start is None or word.end is None:
                continue
            words.append(
                {
                    "start": round(float(word.start), 3),
                    "end": round(float(word.end), 3),
                    "text": text,
                    "probability": round(float(word.probability or 0), 4),
                }
            )
    if not words:
        raise RuntimeError("Faster Whisper did not produce word timestamps")

    grouped_segments = _group_words(words, max_chars=42, max_gap=0.8)
    return {
        "schema_version": 1,
        "song": {
            "title": metadata["title"],
            "uploader": metadata["uploader"],
            "duration": metadata["duration"],
        },
        "transcription": {
            "engine": "faster-whisper",
            "model": config["whisper_model"],
            "language": info.language,
            "language_probability": round(float(info.language_probability), 4),
        },
        "segments": grouped_segments,
    }


def _group_words(words: list[dict[str, Any]], max_chars: int, max_gap: float) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []

    for word in words:
        prospective_text = " ".join(item["text"] for item in [*current, word])
        gap = word["start"] - current[-1]["end"] if current else 0
        punctuation_break = bool(current and re.search(r"[.!?]$", current[-1]["text"]))
        should_break = current and (len(prospective_text) > max_chars or gap > max_gap or punctuation_break)
        if should_break:
            groups.append(current)
            current = []
        current.append(word)
    if current:
        groups.append(current)

    segments = []
    for segment_index, group in enumerate(groups):
        normalized_words = []
        for word_index, word in enumerate(group):
            normalized_words.append({"id": f"s{segment_index}-w{word_index}", **word})
        segments.append(
            {
                "id": f"s{segment_index}",
                "start": group[0]["start"],
                "end": group[-1]["end"],
                "text": " ".join(word["text"] for word in group),
                "words": normalized_words,
            }
        )
    return segments


def _group_page_lines(
    segments: list[dict[str, Any]],
    *,
    max_lines: int = MAX_LYRIC_LINES_PER_PAGE,
    break_silence: float = PAGE_BREAK_SILENCE_SECONDS,
    max_duration: float = MAX_PAGE_DURATION_SECONDS,
) -> list[list[dict[str, Any]]]:
    if max_lines < 1:
        raise ValueError("Lyric pages must allow at least one line")

    grouped_lines: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for segment in segments:
        if not segment.get("words"):
            continue
        gap = segment["start"] - current[-1]["end"] if current else 0
        duration = segment["end"] - current[0]["start"] if current else 0
        should_break = current and (
            len(current) >= max_lines or gap >= break_silence or duration > max_duration
        )
        if should_break:
            grouped_lines.append(current)
            current = []
        current.append(segment)
    if current:
        grouped_lines.append(current)
    return grouped_lines


def _page_words(page: dict[str, Any]) -> list[dict[str, Any]]:
    return [word for line in page["lines"] for word in line["words"]]


def _normalize_karaoke_timeline(
    words: list[dict[str, Any]], event_start_cs: int
) -> tuple[list[int], list[int], int]:
    word_starts_cs: list[int] = []
    for word in words:
        earliest_start_cs = word_starts_cs[-1] + 1 if word_starts_cs else event_start_cs
        word_starts_cs.append(max(earliest_start_cs, _to_centiseconds(word["start"])))

    karaoke_end_cs = max(word_starts_cs[-1] + 1, _to_centiseconds(words[-1]["end"]))
    durations_cs = [
        following_start_cs - start_cs
        for start_cs, following_start_cs in zip(
            word_starts_cs, [*word_starts_cs[1:], karaoke_end_cs], strict=True
        )
    ]
    return word_starts_cs, durations_cs, karaoke_end_cs


def _build_lyric_pages(
    segments: list[dict[str, Any]],
    *,
    max_lines: int = MAX_LYRIC_LINES_PER_PAGE,
    break_silence: float = PAGE_BREAK_SILENCE_SECONDS,
    max_duration: float = MAX_PAGE_DURATION_SECONDS,
    lead: float = PAGE_LEAD_SECONDS,
    tail: float = PAGE_TAIL_SECONDS,
) -> list[dict[str, Any]]:
    grouped_lines = _group_page_lines(
        segments,
        max_lines=max_lines,
        break_silence=break_silence,
        max_duration=max_duration,
    )
    pages: list[dict[str, Any]] = [{"lines": lines} for lines in grouped_lines]
    lead_centiseconds = _to_centiseconds(lead)
    tail_centiseconds = _to_centiseconds(tail)
    next_display_start_cs: int | None = None

    for page_index, page in enumerate(pages):
        words = _page_words(page)
        source_start_cs = _to_centiseconds(words[0]["start"])
        desired_display_start_cs = max(0, source_start_cs - lead_centiseconds)
        display_start_cs = (
            desired_display_start_cs if next_display_start_cs is None else next_display_start_cs
        )
        word_starts_cs, durations_cs, karaoke_end_cs = _normalize_karaoke_timeline(words, display_start_cs)
        desired_display_end_cs = max(
            karaoke_end_cs, _to_centiseconds(words[-1]["end"]) + tail_centiseconds
        )

        page.update(
            {
                "start": words[0]["start"],
                "end": words[-1]["end"],
                "display_start_cs": display_start_cs,
                "word_starts_cs": word_starts_cs,
                "durations_cs": durations_cs,
                "karaoke_end_cs": karaoke_end_cs,
            }
        )
        if page_index + 1 == len(pages):
            page["display_end_cs"] = desired_display_end_cs
            continue

        following_words = _page_words(pages[page_index + 1])
        following_source_start_cs = _to_centiseconds(following_words[0]["start"])
        following_desired_start_cs = max(0, following_source_start_cs - lead_centiseconds)
        if desired_display_end_cs <= following_desired_start_cs:
            page["display_end_cs"] = desired_display_end_cs
            next_display_start_cs = following_desired_start_cs
            continue

        if karaoke_end_cs <= following_source_start_cs:
            boundary_cs = (karaoke_end_cs + following_source_start_cs) // 2
        else:
            boundary_cs = karaoke_end_cs
        page["display_end_cs"] = boundary_cs
        next_display_start_cs = boundary_cs

    return pages


def _render_page_text(page: dict[str, Any]) -> str:
    words = _page_words(page)
    if not words:
        return ""

    karaoke_parts = [f"{{\\fad({PAGE_FADE_MILLISECONDS},{PAGE_FADE_MILLISECONDS})}}"]
    initial_delay = page["word_starts_cs"][0] - page["display_start_cs"]
    if initial_delay:
        karaoke_parts.append(f"{{\\k{initial_delay}}}")

    word_index = 0
    for line_index, line in enumerate(page["lines"]):
        for line_word_index, word in enumerate(line["words"]):
            if line_word_index:
                karaoke_parts.append(" ")
            karaoke_parts.append(f"{{\\kf{page['durations_cs'][word_index]}}}{_escape_ass_text(word['text'])}")
            word_index += 1
        if line_index + 1 < len(page["lines"]):
            karaoke_parts.append(r"\N")
    return "".join(karaoke_parts)


def _write_ass(transcript: dict[str, Any], ass_path: Path, video: dict[str, int]) -> None:
    width = video["width"]
    height = video["height"]
    font_size = 64 if height >= 1080 else 46
    margin = 70 if height >= 1080 else 48
    ass_lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,DejaVu Sans,{font_size},&H0000D7FF,&H00FFFFFF,&H00000000,&H70000000,-1,0,0,0,"
        f"100,100,0,0,1,4,1,5,{margin},{margin},{margin},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for page in _build_lyric_pages(transcript["segments"]):
        ass_lines.append(
            f"Dialogue: 0,{_ass_timestamp_from_centiseconds(page['display_start_cs'])},"
            f"{_ass_timestamp_from_centiseconds(page['display_end_cs'])},"
            f"Default,,0,0,0,,{_render_page_text(page)}"
        )
    ass_path.write_text("\n".join(ass_lines) + "\n", encoding="utf-8")


def _render_video(audio_path: Path, ass_path: Path, output_path: Path, config: dict[str, Any]) -> None:
    video = config["video"]
    width = video["width"]
    height = video["height"]
    fps = video["fps"]
    duration = _probe_duration(audio_path)
    background = config["background"]

    if background["kind"] == "image":
        background_path = Path(background["value"])
        if not background_path.is_file():
            raise FileNotFoundError(f"Uploaded background not found: {background_path}")
        input_args = ["-loop", "1", "-framerate", str(fps), "-i", str(background_path)]
        video_filter = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
            f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.38:t=fill,ass={_escape_filter_path(ass_path)}"
        )
    else:
        color = background["value"].lstrip("#")
        input_args = ["-f", "lavfi", "-i", f"color=c=0x{color}:s={width}x{height}:r={fps}"]
        video_filter = f"ass={_escape_filter_path(ass_path)}"

    base_command = [
        "ffmpeg",
        "-y",
        *input_args,
        "-i",
        str(audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-vf",
        video_filter,
        "-t",
        f"{duration:.3f}",
        "-r",
        str(fps),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ]

    if _nvenc_available():
        try:
            _run(
                [
                    *base_command,
                    "-c:v",
                    "h264_nvenc",
                    "-preset",
                    "p4",
                    "-rc",
                    "vbr",
                    "-cq",
                    "25",
                    "-b:v",
                    "0",
                    str(output_path),
                ]
            )
            return
        except subprocess.CalledProcessError:
            LOGGER.warning("NVENC failed; retrying with libx264")
            output_path.unlink(missing_ok=True)

    _run([*base_command, "-c:v", "libx264", "-preset", "medium", "-crf", "25", str(output_path)])


def _nvenc_available() -> bool:
    try:
        import torch

        if not torch.cuda.is_available():
            return False
        encoders = _run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True)
        return "h264_nvenc" in encoders.stdout
    except (ImportError, subprocess.CalledProcessError):
        return False


def _build_manifest(config: dict[str, Any], metadata: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    files = []
    for path in sorted(output_dir.iterdir()):
        if path.is_file():
            files.append({"name": path.name, "size_bytes": path.stat().st_size})
    return {
        "schema_version": 1,
        "job_id": config["job_id"],
        "status": "completed",
        "source": {
            "kind": config["source"]["kind"],
            "name": metadata["title"],
            "url": metadata["source_url"],
        },
        "configuration": {
            "language": config["language"],
            "whisper_model": config["whisper_model"],
            "demucs_model": config["demucs_model"],
            "background_kind": config["background"]["kind"],
            "video": config["video"],
        },
        "files": files,
    }


def _create_archive(output_dir: Path, archive_path: Path) -> None:
    archive_path.unlink(missing_ok=True)
    created_path = Path(shutil.make_archive(str(archive_path.with_suffix("")), "zip", root_dir=output_dir))
    if created_path != archive_path:
        created_path.replace(archive_path)


def _probe_duration(path: Path) -> float:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
    )
    return float(result.stdout.strip())


def _safe_filename(value: str) -> str:
    normalized = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._")
    return normalized[:80] or "karaoke"


def _escape_ass_text(value: str) -> str:
    return value.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def _escape_filter_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _ass_timestamp_from_centiseconds(centiseconds: int) -> str:
    centiseconds = max(0, centiseconds)
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    whole_seconds, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{fraction:02d}"


def _to_centiseconds(seconds: float) -> int:
    return max(0, round(seconds * 100))


def _require_commands(*commands: str) -> None:
    missing = [command for command in commands if not shutil.which(command)]
    if missing:
        raise RuntimeError(f"Missing required commands: {', '.join(missing)}")


def _run(command: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    LOGGER.info("Running %s", " ".join(command))
    return subprocess.run(command, check=True, capture_output=capture_output, text=True)


def _run_with_status() -> None:
    STATUS_PATH.unlink(missing_ok=True)
    try:
        main()
    except Exception as error:
        STATUS_PATH.write_text(
            json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), encoding="utf-8"
        )
        raise
    STATUS_PATH.write_text(json.dumps({"status": "completed"}), encoding="utf-8")


if __name__ == "__main__":
    _run_with_status()
