import importlib.util
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

CONFIG_PATH = Path("/content/karaoke_job.json")
STATUS_PATH = Path("/content/karaoke_status.json")
HF_TOKEN_PATH = Path("/content/.hf_token")
WORK_DIR = Path("/content/karaoke_workspace")
LYRICS_MODULE_PATH = Path("/content/karaoke_lyrics_file.py")
RENDER_JOB_PATH = Path("/content/karaoke_render_job.zip")
LOGGER = logging.getLogger(__name__)
LRCLIB_API = "https://lrclib.net/api"
CTC_ALIGNER_MODEL = "MahmoudAshraf/mms-300m-1130-forced-aligner"
CTC_ALIGNER_MODEL_REVISION = "49402e9577b1158620820667c218cd494cc44486"
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
    _ensure_system_fonts()
    _ensure_bebas_font()
    if config.get("operation") == "render":
        _render_existing_job(config)
        return

    _configure_huggingface()

    lyrics_config = config.get("lyrics", {})
    record = None
    if not lyrics_config.get("disable_lrclib") and lyrics_config.get("lrclib_id") is not None:
        record = _fetch_lrclib({}, config)
    source_path, metadata = _acquire_source(config)
    if not lyrics_config.get("disable_lrclib") and lyrics_config.get("lrclib_id") is None:
        record = _fetch_lrclib(metadata, config)
    if record is not None and lyrics_config.get("lrclib_id") is not None:
        document = _lyrics_document_from_record(record, metadata, config)
        if _has_complete_word_timings(document):
            _load_lyrics_module().validate_lyrics_file(document, require_words=True)
    mixture_path = _prepare_mixture(source_path)
    vocals_path, instrumental_path = _separate_vocals(mixture_path, config["demucs_model"])

    safe_title = _safe_filename(metadata["title"])
    output_dir = WORK_DIR / safe_title
    output_dir.mkdir(parents=True, exist_ok=True)
    original_audio = output_dir / f"original_audio{source_path.suffix.lower()}"
    vocals_flac = output_dir / "vocals.flac"
    instrumental_flac = output_dir / "instrumental.flac"
    lyrics_path = output_dir / "lyrics.lyricsfile.yaml"
    alignment_path = output_dir / "alignment.json"
    shutil.copy2(source_path, original_audio)
    _run(["ffmpeg", "-y", "-i", str(vocals_path), "-c:a", "flac", str(vocals_flac)])
    _run(["ffmpeg", "-y", "-i", str(instrumental_path), "-c:a", "flac", str(instrumental_flac)])
    preparation = {
        "demucs_model": config["demucs_model"],
        "whisper_model": config["whisper_model"],
        "requested_language": config["language"],
        "lrclib_id": record.get("id") if record else None,
        "disable_lrclib": bool(lyrics_config.get("disable_lrclib")),
    }
    try:
        lyrics, alignment = _prepare_lyrics(vocals_path, metadata, config, selected_record=record)
    except Exception as error:
        checkpoint = {
            "status": "lyrics_failed",
            "error": str(error),
            "source": metadata,
            "preparation": preparation,
            "media": {
                "original_audio": original_audio.name,
                "vocals_audio": vocals_flac.name,
                "instrumental_audio": instrumental_flac.name,
            },
        }
        (output_dir / "checkpoint.json").write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
        recovery_path = Path(config["archive_path"]).with_suffix(".checkpoint.zip")
        _create_archive(output_dir, recovery_path)
        raise LyricsPreparationError(str(error), recovery_path) from error
    lyrics_module = _load_lyrics_module()
    lyrics_path.write_text(lyrics_module.dump_lyrics_file(lyrics), encoding="utf-8")
    alignment_path.write_text(json.dumps(alignment, ensure_ascii=False, indent=2), encoding="utf-8")
    if hasattr(lyrics_module, "generate_srt"):
        (output_dir / "lyrics.srt").write_text(lyrics_module.generate_srt(lyrics), encoding="utf-8")

    background = {"kind": config["background"]["kind"]}
    if config["background"]["kind"] == "image":
        source_background = Path(config["background"]["value"])
        background_path = output_dir / f"background{source_background.suffix.lower()}"
        shutil.copy2(source_background, background_path)
        background["path"] = background_path.name
        background["overlay_opacity"] = 0
    else:
        background["color"] = config["background"]["value"]
    job_document = {
        "schema_version": 2,
        "job_id": config["job_id"],
        "title": metadata["title"],
        "source": metadata,
        "preparation": preparation,
        "alignment": {key: value for key, value in alignment.items() if key != "words"},
        "media": {
            "original_audio": original_audio.name,
            "vocals_audio": vocals_flac.name,
            "instrumental_audio": instrumental_flac.name,
            "lyrics": lyrics_path.name,
        },
        "video": config["video"],
        "background": config.get("render_background", background),
        "style": config.get("render_style", {}),
    }
    watermark_config = config.get("watermark")
    if watermark_config and watermark_config.get("enabled") is False:
        job_document["watermark"] = {"enabled": False}
    elif watermark_config and watermark_config.get("path"):
        job_document["watermark"] = {
            "enabled": True,
            "path": watermark_config["path"],
            "position": watermark_config.get("position", "top_left"),
            "scale": float(watermark_config.get("scale", 0.18)),
            "margin": float(watermark_config.get("margin", 0.05)),
            "opacity": float(watermark_config.get("opacity", 0.85)),
        }
    (output_dir / "job.json").write_text(json.dumps(job_document, ensure_ascii=False, indent=2), encoding="utf-8")

    _create_archive(output_dir, Path(config["archive_path"]))
    LOGGER.info("Pipeline completed: %s", config["archive_path"])


class LyricsPreparationError(RuntimeError):
    """Expose the stems checkpoint when lyric preparation fails."""

    def __init__(self, message: str, recovery_archive_path: Path) -> None:
        super().__init__(message)
        self.recovery_archive_path = recovery_archive_path


def _render_existing_job(config: dict[str, Any]) -> None:
    if not RENDER_JOB_PATH.is_file():
        raise FileNotFoundError("Missing uploaded render job")
    job_dir = WORK_DIR / "render_job"
    job_dir.mkdir(parents=True, exist_ok=True)
    _extract_archive(RENDER_JOB_PATH, job_dir)
    document = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    requested_mode = config["mode"]
    modes = ("karaoke", "lyrics") if requested_mode == "both" else (requested_mode,)
    audio_keys = {"karaoke": "instrumental_audio", "lyrics": "original_audio"}
    output_dir = WORK_DIR / "render_result"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "render-settings.json").write_text(json.dumps({
        "theme": config.get("theme", "job"), "mode": requested_mode,
        "renderer": "braccato-1.6.2" if (document.get("style") or {}).get("lyrics_effect") == "word-synced" else "ass",
        "background": document["background"], "video": document["video"], "style": document.get("style", {}),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    title = _safe_filename(document["title"])
    background = document["background"]
    render_background = {
        "kind": background["kind"],
        "value": str(job_dir / background["path"]) if background["kind"] == "image" else background.get("color"),
        "overlay_opacity": background.get("overlay_opacity", 0),
    }
    if background["kind"] == "cosmic":
        cosmic_module_path = job_dir / "cosmic_background.py"
        if not cosmic_module_path.is_file():
            raise FileNotFoundError(f"Missing cosmic background generator in render bundle: {cosmic_module_path}")
        spec = importlib.util.spec_from_file_location("cosmic_background", cosmic_module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Missing cosmic background generator in render bundle")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        loop_path = module.render_cosmic_video(
            background,
            document["video"],
            output_dir / "background.mp4",
        )
        render_background = {"kind": "video", "value": str(loop_path)}
    watermark = document.get("watermark")
    render_watermark = None
    if watermark and watermark.get("enabled", True) and watermark.get("path"):
        watermark_file = job_dir / watermark["path"]
        if watermark_file.is_file():
            render_watermark = {
                "path": str(watermark_file),
                "position": watermark.get("position", "top_left"),
                "scale": float(watermark.get("scale", 0.18)),
                "margin": float(watermark.get("margin", 0.05)),
                "opacity": float(watermark.get("opacity", 0.85)),
            }
    graphics = job_dir / "graphics"
    if graphics.is_dir():
        shutil.copytree(graphics, output_dir, dirs_exist_ok=True)
    intro_config = document.get("intro") or {}
    browser_renderer = None
    if (document.get("style") or {}).get("lyrics_effect") == "word-synced":
        module_path = job_dir / "browser_lyrics.py"
        if not module_path.is_file():
            raise FileNotFoundError("Missing Braccato renderer in render bundle")
        _ensure_playwright()
        spec = importlib.util.spec_from_file_location("browser_lyrics", module_path)
        browser_renderer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(browser_renderer)
    for mode in modes:
        source_ass = job_dir / f"{mode}.ass"
        if not source_ass.is_file():
            raise FileNotFoundError(f"Missing generated {mode} ASS file in render bundle")
        audio_path = job_dir / document["media"][audio_keys[mode]]
        video_path = output_dir / f"{title}_{mode}.mp4"
        subtitles_dir = output_dir / "subtitles"
        subtitles_dir.mkdir(parents=True, exist_ok=True)
        ass_path = subtitles_dir / f"{title}_{mode}.ass"
        shutil.copy2(source_ass, ass_path)
        source_srt = job_dir / "lyrics.srt"
        if source_srt.is_file():
            shutil.copy2(source_srt, subtitles_dir / f"{title}.srt")
            shutil.copy2(source_srt, subtitles_dir / f"{title}_{mode}.srt")
        render_config = {
            "video": document["video"],
            "background": render_background,
        }
        if (job_dir / "fonts").is_dir():
            render_config["fonts_dir"] = str(job_dir / "fonts")
        if render_watermark is not None:
            render_config["watermark"] = render_watermark
        intro_card_file = graphics / "intro" / f"intro_{mode}.png"
        if intro_config.get("enabled", True) and intro_card_file.is_file():
            render_config["intro_card"] = {
                "path": str(intro_card_file),
                "start": float(intro_config.get("start", 0)),
                "end": float(intro_config.get("end", intro_config.get("duration", 5))),
            }
        overlay = None
        if browser_renderer is not None:
            overlay = browser_renderer.render_bundled_overlay(
                job_dir, mode, job_dir / f"{mode}-overlay.mov", _probe_duration(audio_path),
            )
            render_config["lyrics_overlay"] = str(overlay)
        _render_video(
            audio_path,
            video_path,
            render_config,
            ass_path=None if overlay else ass_path,
        )
        if overlay:
            overlay.unlink()
    _create_archive(output_dir, Path(config["archive_path"]))


def _load_lyrics_module() -> Any:
    if not LYRICS_MODULE_PATH.is_file():
        try:
            import karaoke_app.lyrics_file as module

            return module
        except ImportError:
            pass
    spec = importlib.util.spec_from_file_location("karaoke_lyrics_file", LYRICS_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the uploaded LyricsFile module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _extract_archive(archive_path: Path, destination: Path) -> None:
    import zipfile

    root = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            if not (destination / member.filename).resolve().is_relative_to(root):
                raise ValueError(f"Unsafe render archive member: {member.filename}")
        archive.extractall(destination)


def _configure_huggingface() -> None:
    if not HF_TOKEN_PATH.is_file():
        return
    try:
        token = HF_TOKEN_PATH.read_text(encoding="utf-8").strip()
    finally:
        HF_TOKEN_PATH.unlink(missing_ok=True)
    if token:
        os.environ["HF_TOKEN"] = token


def _acquire_source(config: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    source = config["source"]
    if source["kind"] == "file":
        source_path = Path(source["value"])
        if not source_path.is_file():
            raise FileNotFoundError(f"Uploaded source not found: {source_path}")
        lyrics_options = config.get("lyrics", {})
        return source_path, {
            "title": lyrics_options.get("title") or source.get("name") or source_path.stem,
            "track": lyrics_options.get("title") or source.get("name") or source_path.stem,
            "artist": lyrics_options.get("artist"),
            "album": lyrics_options.get("album"),
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
    lyrics_options = config.get("lyrics", {})
    return source_path, {
        "title": lyrics_options.get("title") or raw_metadata.get("title") or "karaoke",
        "track": lyrics_options.get("title") or raw_metadata.get("track") or raw_metadata.get("title") or "karaoke",
        "artist": lyrics_options.get("artist") or raw_metadata.get("artist") or raw_metadata.get("creator"),
        "album": lyrics_options.get("album") or raw_metadata.get("album"),
        "language": raw_metadata.get("language"),
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


def _prepare_lyrics(
    vocals_path: Path, metadata: dict[str, Any], config: dict[str, Any],
    *, selected_record: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    lyrics_module = _load_lyrics_module()
    record = selected_record
    fallback_reason = "lrclib_disabled" if config.get("lyrics", {}).get("disable_lrclib") else "no_safe_lrclib_match"
    if record is not None:
        try:
            document = _lyrics_document_from_record(record, metadata, config)
            if _has_complete_word_timings(document):
                lyrics = lyrics_module.validate_lyrics_file(document, require_words=True)
                return lyrics, {
                    "engine": "lrclib",
                    "lrclib_id": record.get("id"),
                    "word_timing": "provided",
                    "language": lyrics["metadata"].get("language"),
                    "strategy": "provided_word_timings",
                }
            provenance: dict[str, Any] = {}
            lyrics, words = _align_known_lyrics(vocals_path, document, config, provenance=provenance)
            return lyrics, {
                "engine": "ctc-forced-aligner",
                "model": CTC_ALIGNER_MODEL,
                "model_revision": CTC_ALIGNER_MODEL_REVISION,
                "lrclib_id": record.get("id"),
                "word_timing": "generated",
                "words": words,
                **provenance,
            }
        except (AssertionError, KeyError, RuntimeError, ValueError) as error:
            fallback_reason = str(error)
            LOGGER.warning(
                "LRCLIB record %s (%s) could not be used; falling back to Faster Whisper: %s",
                record.get("id"),
                record.get("trackName"),
                error,
            )

    transcript = _transcribe(vocals_path, metadata, config)
    lyrics = _transcript_to_lyrics(transcript)
    words = []
    for line_idx, line in enumerate(lyrics["lines"]):
        for word_idx, word in enumerate(line.get("words", [])):
            words.append(
                {
                    "id": f"s{line_idx}-w{word_idx}",
                    "start": round(word["start_ms"] / 1000, 3),
                    "end": round(word["end_ms"] / 1000, 3),
                    "text": word["text"].strip(),
                    "probability": word.get("confidence", 0.0),
                }
            )
    return lyrics, {
        "engine": "faster-whisper",
        "model": config["whisper_model"],
        "language": transcript["transcription"]["language"],
        "word_timing": "generated",
        "strategy": "transcription",
        "fallback_reason": fallback_reason,
        "lrclib_id": record.get("id") if record else None,
        "words": words,
    }


def _normalize_text(text: str | None) -> str:
    if not text:
        return ""
    normalized = "".join(character if character.isalnum() else " " for character in text.casefold())
    return " ".join(normalized.split())


def _match_text(value: str) -> str:
    return _normalize_text(value)


def _primary_artist(artist: str | None) -> str | None:
    if not artist:
        return None
    trimmed = artist.strip()
    if not trimmed:
        return None
    lower = trimmed.lower()
    for pattern in (" feat. ", " feat ", " ft. ", " ft ", " featuring ", " with "):
        idx = lower.find(pattern)
        if idx != -1:
            prefix = trimmed[:idx].strip()
            if prefix:
                return prefix
    for separator in (",", ";"):
        if separator in trimmed:
            parts = [part.strip() for part in trimmed.split(separator) if part.strip()]
            if parts:
                return parts[0]
    return trimmed


def _artist_variants(artist: str | None) -> list[str]:
    if not artist:
        return []
    full = artist.strip()
    if not full:
        return []
    primary = _primary_artist(full)
    results = [full]
    if primary and _normalize_text(primary) != _normalize_text(full):
        results.append(primary)
    return results


def _title_variants(track: str | None) -> list[str]:
    if not track:
        return []
    original = " ".join(track.strip().split())
    if not original:
        return []
    candidates = [original]
    stripped = re.sub(r"\s*\([^)]*\)\s*", " ", original)
    stripped = re.sub(r"\s*\[[^\]]*\]\s*", " ", stripped)
    stripped = " ".join(stripped.split())
    if stripped and stripped != original:
        candidates.append(stripped)
    return candidates


EDITION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bacoustic\b", re.IGNORECASE), "acoustic"),
    (re.compile(r"\blive\b", re.IGNORECASE), "live"),
    (re.compile(r"\bremix\b", re.IGNORECASE), "remix"),
    (re.compile(r"\binstrumental\b", re.IGNORECASE), "instrumental"),
    (re.compile(r"\ba\s+cappella\b", re.IGNORECASE), "acapella"),
    (re.compile(r"\bacapella\b", re.IGNORECASE), "acapella"),
    (re.compile(r"\bradio\s+edit\b", re.IGNORECASE), "radio edit"),
    (re.compile(r"\bextended\b", re.IGNORECASE), "extended"),
    (re.compile(r"\bdemo\b", re.IGNORECASE), "demo"),
    (re.compile(r"\bsped\s+up\b", re.IGNORECASE), "sped up"),
    (re.compile(r"\bslowed\b", re.IGNORECASE), "slowed"),
    (re.compile(r"\breverb\b", re.IGNORECASE), "reverb"),
)


def _title_edition_tokens(title: str | None) -> set[str]:
    if not title:
        return set()
    found: set[str] = set()
    for pattern, token in EDITION_PATTERNS:
        if pattern.search(title):
            found.add(token)
    return found


def _artist_matches(source_artist: str | None, candidate_artist: str | None) -> bool:
    if not source_artist:
        return True
    if not candidate_artist:
        return False
    source_vars = {_normalize_text(v) for v in _artist_variants(source_artist) if _normalize_text(v)}
    cand_vars = {_normalize_text(v) for v in _artist_variants(candidate_artist) if _normalize_text(v)}
    if source_vars & cand_vars:
        return True
    for s in source_vars:
        for c in cand_vars:
            if SequenceMatcher(None, s, c).ratio() >= 0.8:
                return True
    return False


def _usable_lrclib_record(record: dict[str, Any]) -> bool:
    return not record.get("instrumental") and any(
        isinstance(record.get(key), str) and record[key].strip()
        for key in ("lyricsfile", "lyricsFile", "syncedLyrics", "plainLyrics")
    )


def _lrclib_candidate_is_safe(
    candidate: dict[str, Any],
    *,
    track: str,
    artist: str | None,
    duration: float | int | None,
) -> bool:
    if not isinstance(candidate, dict) or not _usable_lrclib_record(candidate):
        return False

    candidate_track = str(candidate.get("trackName") or "")
    if not candidate_track.strip():
        return False

    # 1. Strict artist matching (score must not compensate for an artist mismatch)
    candidate_artist = candidate.get("artistName")
    if not _artist_matches(artist, candidate_artist):
        LOGGER.debug(
            "candidate=%s rejected: artist mismatch (%r != %r)",
            candidate.get("id"),
            candidate_artist,
            artist,
        )
        return False

    # 2. Title matching
    source_titles = _title_variants(track)
    cand_titles = _title_variants(candidate_track)
    source_base = _normalize_text(source_titles[-1]) if source_titles else ""
    cand_base = _normalize_text(cand_titles[-1]) if cand_titles else ""
    norm_source_track = _normalize_text(track)
    norm_cand_track = _normalize_text(candidate_track)

    title_ratio_full = SequenceMatcher(None, norm_source_track, norm_cand_track).ratio()
    title_ratio_base = SequenceMatcher(None, source_base, cand_base).ratio() if source_base and cand_base else 0.0

    title_match = (
        (source_base and cand_base and source_base == cand_base)
        or (norm_source_track and norm_cand_track and norm_source_track == norm_cand_track)
        or title_ratio_full >= 0.75
        or title_ratio_base >= 0.75
    )
    if not title_match:
        LOGGER.debug(
            "candidate=%s rejected: title mismatch (%r != %r)",
            candidate.get("id"),
            candidate_track,
            track,
        )
        return False

    # 3. Edition conflict check: incompatible explicit editions must be rejected
    source_editions = _title_edition_tokens(track)
    candidate_editions = _title_edition_tokens(candidate_track)
    if source_editions and candidate_editions and source_editions != candidate_editions:
        LOGGER.debug(
            "candidate=%s rejected: edition mismatch (%s != %s)",
            candidate.get("id"),
            source_editions,
            candidate_editions,
        )
        return False

    # 4. Duration check: reject if difference > 10 seconds when both are present
    candidate_duration = candidate.get("duration")
    if duration and candidate_duration:
        try:
            delta = abs(float(duration) - float(candidate_duration))
            if delta > 10.0:
                LOGGER.debug(
                    "candidate=%s rejected: duration delta %.1fs > 10s",
                    candidate.get("id"),
                    delta,
                )
                return False
        except (TypeError, ValueError):
            pass

    return True


def _lrclib_match_score(
    record: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    *,
    track: str | None = None,
    artist: str | None = None,
    duration: float | int | None = None,
) -> float:
    if metadata:
        track = track or str(metadata.get("track") or metadata.get("title") or "")
        artist = artist if artist is not None else metadata.get("artist")
        duration = duration if duration is not None else metadata.get("duration")

    expected_title = track or ""
    candidate_title = str(record.get("trackName") or "")
    norm_expected = _normalize_text(expected_title)
    norm_candidate = _normalize_text(candidate_title)

    title_score = SequenceMatcher(None, norm_expected, norm_candidate).ratio()
    source_titles = _title_variants(expected_title)
    cand_titles = _title_variants(candidate_title)
    if source_titles and cand_titles and _normalize_text(source_titles[-1]) == _normalize_text(cand_titles[-1]):
        title_score = max(title_score, 0.95)

    artist_score = 0.5
    candidate_artist = str(record.get("artistName") or "")
    if artist:
        norm_artist = _normalize_text(artist)
        norm_cand_artist = _normalize_text(candidate_artist)
        primary = _primary_artist(artist)
        norm_primary = _normalize_text(primary) if primary else ""

        if norm_artist == norm_cand_artist or (norm_primary and norm_primary == norm_cand_artist):
            artist_score = 1.0
        else:
            ratio_full = SequenceMatcher(None, norm_artist, norm_cand_artist).ratio()
            ratio_primary = SequenceMatcher(None, norm_primary, norm_cand_artist).ratio() if norm_primary else 0.0
            artist_score = max(ratio_full, ratio_primary)

    duration_score = 0.0
    cand_duration = record.get("duration")
    if duration and cand_duration:
        try:
            difference = abs(float(duration) - float(cand_duration))
            duration_score = (
                1.0 if difference <= 2.0 else 0.5 if difference <= 5.0 else 0.2 if difference <= 10.0 else 0.0
            )
        except (TypeError, ValueError):
            pass

    edition_score = 0.0
    source_editions = _title_edition_tokens(expected_title)
    cand_editions = _title_edition_tokens(candidate_title)
    if source_editions and cand_editions:
        if source_editions & cand_editions:
            edition_score = 0.5
        else:
            edition_score = -0.5
    elif source_editions and not cand_editions:
        edition_score = -0.25
    elif not source_editions and cand_editions:
        edition_score = -0.25
    else:
        edition_score = 0.2

    total = title_score + artist_score + duration_score + edition_score
    LOGGER.debug(
        "candidate=%s title=%.2f artist=%.2f duration=%.2f edition=%.2f total=%.2f",
        record.get("id"),
        title_score,
        artist_score,
        duration_score,
        edition_score,
        total,
    )
    return total


def _fetch_lrclib(metadata: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    forced_id = config.get("lyrics", {}).get("lrclib_id")
    if forced_id is not None:
        try:
            value = _lrclib_request(f"/get/{int(forced_id)}")
        except (OSError, ValueError) as error:
            raise RuntimeError(f"Unable to load requested LRCLIB id {forced_id}: {error}") from error
        if not isinstance(value, dict):
            raise RuntimeError(f"LRCLIB id {forced_id} returned an invalid record")
        if not _usable_lrclib_record(value):
            raise RuntimeError(f"LRCLIB id {forced_id} does not contain usable lyrics")
        LOGGER.info("Using requested LRCLIB id %s: %s", value.get("id"), value.get("trackName"))
        return value

    track = str(metadata.get("track") or metadata["title"])
    artist = metadata.get("artist")
    album = metadata.get("album")
    duration = metadata.get("duration")
    duration_str = str(round(float(duration))) if duration else ""
    primary_artist = _primary_artist(artist)

    # --- Tier 1: GET exact (full metadata) ---
    if artist:
        t1_params: dict[str, str] = {
            "track_name": track,
            "artist_name": artist,
        }
        if duration_str:
            t1_params["duration"] = duration_str
        if album:
            t1_params["album_name"] = str(album)
        LOGGER.debug(
            "LRCLIB GET Tier 1 track=%r artist=%r album=%r duration=%r",
            track,
            artist,
            album,
            duration_str,
        )
        try:
            value = _lrclib_request(f"/get?{urllib.parse.urlencode(t1_params)}")
            if isinstance(value, dict) and _lrclib_candidate_is_safe(
                value, track=track, artist=artist, duration=duration
            ):
                score = _lrclib_match_score(value, metadata, track=track, artist=artist, duration=duration)
                LOGGER.info("LRCLIB selected id=%s score=%.2f via get-exact", value.get("id"), score)
                return value
        except OSError as error:
            LOGGER.debug("LRCLIB GET Tier 1 failed: %s", error)

    # --- Tier 2: GET without album ---
    if artist and album:
        t2_params = {
            "track_name": track,
            "artist_name": artist,
        }
        if duration_str:
            t2_params["duration"] = duration_str
        LOGGER.debug(
            "LRCLIB GET Tier 2 (without album) track=%r artist=%r duration=%r",
            track,
            artist,
            duration_str,
        )
        try:
            value = _lrclib_request(f"/get?{urllib.parse.urlencode(t2_params)}")
            if isinstance(value, dict) and _lrclib_candidate_is_safe(
                value, track=track, artist=artist, duration=duration
            ):
                score = _lrclib_match_score(value, metadata, track=track, artist=artist, duration=duration)
                LOGGER.info("LRCLIB selected id=%s score=%.2f via get-without-album", value.get("id"), score)
                return value
        except OSError as error:
            LOGGER.debug("LRCLIB GET Tier 2 failed: %s", error)

    # --- Tier 3: GET with primary artist ---
    if primary_artist and _normalize_text(primary_artist) != _normalize_text(artist):
        t3_params = {
            "track_name": track,
            "artist_name": primary_artist,
        }
        if duration_str:
            t3_params["duration"] = duration_str
        LOGGER.debug(
            "LRCLIB GET Tier 3 (primary artist) track=%r artist=%r duration=%r",
            track,
            primary_artist,
            duration_str,
        )
        try:
            value = _lrclib_request(f"/get?{urllib.parse.urlencode(t3_params)}")
            if isinstance(value, dict) and _lrclib_candidate_is_safe(
                value, track=track, artist=artist, duration=duration
            ):
                score = _lrclib_match_score(value, metadata, track=track, artist=artist, duration=duration)
                LOGGER.info("LRCLIB selected id=%s score=%.2f via get-primary-artist", value.get("id"), score)
                return value
        except OSError as error:
            LOGGER.debug("LRCLIB GET Tier 3 failed: %s", error)

    # --- Tier 4: Structured search ---
    candidates_by_id: dict[int, dict[str, Any]] = {}
    title_variants = _title_variants(track)
    base_track = title_variants[-1] if len(title_variants) > 1 else None

    search_queries: list[dict[str, str]] = []
    target_artist = primary_artist or artist
    if target_artist:
        search_queries.append({"track_name": track, "artist_name": target_artist})
        if base_track and base_track != track:
            search_queries.append({"track_name": base_track, "artist_name": target_artist})
        if artist and primary_artist and _normalize_text(artist) != _normalize_text(primary_artist):
            search_queries.append({"track_name": track, "artist_name": artist})

    for params in search_queries:
        LOGGER.debug("LRCLIB SEARCH structured: %s", params)
        try:
            results = _lrclib_request(f"/search?{urllib.parse.urlencode(params)}")
        except OSError as error:
            LOGGER.debug("LRCLIB SEARCH structured %s failed: %s", params, error)
            continue
        if isinstance(results, list):
            LOGGER.debug("LRCLIB SEARCH returned %d candidates", len(results))
            for record in results:
                if isinstance(record, dict) and isinstance(record.get("id"), int):
                    candidates_by_id.setdefault(record["id"], record)

        safe_candidates = [
            c
            for c in candidates_by_id.values()
            if _lrclib_candidate_is_safe(c, track=track, artist=artist, duration=duration)
        ]
        if safe_candidates:
            selected = max(
                safe_candidates,
                key=lambda c: _lrclib_match_score(c, metadata, track=track, artist=artist, duration=duration),
            )
            score = _lrclib_match_score(selected, metadata, track=track, artist=artist, duration=duration)
            LOGGER.info("LRCLIB selected id=%s score=%.2f via structured-search", selected.get("id"), score)
            return selected

    # --- Tier 5: Fallback q= search ---
    q_queries: list[str] = []
    if target_artist:
        q_queries.append(f"{target_artist} {track}")
        if base_track and base_track != track:
            q_queries.append(f"{target_artist} {base_track}")
    q_queries.append(track)
    if base_track and base_track != track:
        q_queries.append(base_track)
    q_queries = list(dict.fromkeys(q_queries))

    for query in q_queries:
        LOGGER.debug("LRCLIB SEARCH q=%r", query)
        try:
            results = _lrclib_request(f"/search?{urllib.parse.urlencode({'q': query})}")
        except OSError as error:
            LOGGER.debug("LRCLIB SEARCH q=%r failed: %s", query, error)
            continue
        if isinstance(results, list):
            LOGGER.debug("LRCLIB SEARCH returned %d candidates", len(results))
            for record in results:
                if isinstance(record, dict) and isinstance(record.get("id"), int):
                    candidates_by_id.setdefault(record["id"], record)

        safe_candidates = [
            c
            for c in candidates_by_id.values()
            if _lrclib_candidate_is_safe(c, track=track, artist=artist, duration=duration)
        ]
        if safe_candidates:
            selected = max(
                safe_candidates,
                key=lambda c: _lrclib_match_score(c, metadata, track=track, artist=artist, duration=duration),
            )
            score = _lrclib_match_score(selected, metadata, track=track, artist=artist, duration=duration)
            LOGGER.info("LRCLIB selected id=%s score=%.2f via q-search", selected.get("id"), score)
            return selected

    LOGGER.info("No safe LRCLIB match found; using Faster Whisper")
    return None


def _lrclib_request(path: str, max_retries: int = 2) -> Any:
    request = urllib.request.Request(
        f"{LRCLIB_API}{path}",
        headers={"User-Agent": "yt-video-generator/0.1.0 (LyricsFile preparation)"},
    )
    attempts = 0
    while True:
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempts < max_retries:
                attempts += 1
                retry_after_header = error.headers.get("Retry-After") if error.headers else None
                retry_seconds = 1.0
                if retry_after_header:
                    try:
                        retry_seconds = min(max(float(retry_after_header), 0.5), 10.0)
                    except (TypeError, ValueError):
                        retry_seconds = 1.0
                LOGGER.warning(
                    "LRCLIB rate limited (429); sleeping %.1fs (attempt %d/%d)",
                    retry_seconds,
                    attempts,
                    max_retries,
                )
                time.sleep(retry_seconds)
                continue
            raise OSError(f"HTTP {error.code}: {error.reason}") from error
        except (json.JSONDecodeError, TimeoutError, urllib.error.URLError) as error:
            raise OSError(str(error)) from error


def _parse_synced_lyrics(synced_source: str, duration_ms: int | None = None) -> list[dict[str, Any]]:
    pattern = re.compile(r"^\[(?P<min>\d{1,3}):(?P<sec>\d{2})(?:\.(?P<msec>\d{2,3}))?\]\s*(?P<text>.*)$")
    raw_entries: list[tuple[int, str]] = []
    for raw_line in synced_source.splitlines():
        line_str = raw_line.strip()
        if not line_str:
            continue
        m = pattern.match(line_str)
        if not m:
            continue
        minutes = int(m.group("min"))
        seconds = int(m.group("sec"))
        sub = m.group("msec") or "0"
        ms = int(sub) * 10 if len(sub) == 2 else int(sub)
        time_ms = (minutes * 60 + seconds) * 1000 + ms
        text = m.group("text").strip()
        raw_entries.append((time_ms, text))

    lines: list[dict[str, Any]] = []
    for i, (t_ms, text) in enumerate(raw_entries):
        if not text:
            continue
        end_ms = None
        for next_t_ms, _ in raw_entries[i + 1 :]:
            end_ms = next_t_ms
            break
        if end_ms is None or end_ms <= t_ms:
            if duration_ms and duration_ms > t_ms:
                end_ms = min(t_ms + 8000, duration_ms)
            else:
                end_ms = t_ms + 4000
        lines.append({"text": text, "start_ms": t_ms, "end_ms": end_ms})
    return lines


def _lyrics_document_from_record(
    record: dict[str, Any], metadata: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    import yaml

    raw_lyrics_file = record.get("lyricsfile") or record.get("lyricsFile")
    if isinstance(raw_lyrics_file, str) and raw_lyrics_file.strip():
        document = None
        try:
            loaded = yaml.safe_load(raw_lyrics_file)
            if isinstance(loaded, dict):
                document = loaded
        except yaml.YAMLError as error:
            LOGGER.warning("LRCLIB returned invalid LyricsFile YAML: %s", error)

        if document is not None:
            raw_lines = document.get("lines")
            has_text_lines = (
                isinstance(raw_lines, list)
                and raw_lines
                and any(isinstance(line, dict) and str(line.get("text") or "").strip() for line in raw_lines)
            )
            if has_text_lines:
                document.setdefault("version", "1.0")
                if not isinstance(document.get("metadata"), dict):
                    document["metadata"] = {}
                document["metadata"].setdefault("title", record.get("trackName") or metadata["title"])
                document["metadata"].setdefault("duration_ms", round(float(metadata["duration"]) * 1000))
                language = config["language"] if config["language"] != "auto" else metadata.get("language")
                if language:
                    document["metadata"].setdefault("language", language)
                return document
            LOGGER.info("LRCLIB lyricsfile has no usable lines, trying syncedLyrics/plainLyrics")

    synced_source = record.get("syncedLyrics")
    if isinstance(synced_source, str) and synced_source.strip():
        duration_ms = (
            round(float(metadata["duration"]) * 1000)
            if isinstance(metadata.get("duration"), int | float) and metadata["duration"]
            else None
        )
        lines = _parse_synced_lyrics(synced_source, duration_ms)
        if lines:
            return {
                "version": "1.0",
                "metadata": {
                    "title": record.get("trackName") or metadata["title"],
                    "artist": record.get("artistName") or metadata.get("artist"),
                    "album": record.get("albumName") or metadata.get("album"),
                    "language": config["language"] if config["language"] != "auto" else metadata.get("language"),
                    "duration_ms": duration_ms or 0,
                },
                "lines": lines,
            }

    plain_source = record.get("plainLyrics")
    if isinstance(plain_source, str) and plain_source.strip():
        lines = []
        for raw_line in plain_source.splitlines():
            text = raw_line.strip()
            if text:
                lines.append({"text": text})
        if lines:
            return {
                "version": "1.0",
                "metadata": {
                    "title": record.get("trackName") or metadata["title"],
                    "artist": record.get("artistName") or metadata.get("artist"),
                    "album": record.get("albumName") or metadata.get("album"),
                    "language": config["language"] if config["language"] != "auto" else metadata.get("language"),
                    "duration_ms": round(float(metadata["duration"]) * 1000),
                },
                "lines": lines,
            }

    raise ValueError("LRCLIB record does not contain usable lyrics")


def _has_complete_word_timings(document: dict[str, Any]) -> bool:
    lines = document.get("lines")
    if not isinstance(lines, list):
        return False
    lyric_lines = [line for line in lines if isinstance(line, dict) and str(line.get("text") or "").strip()]
    return bool(lyric_lines) and all(
        isinstance(line.get("words"), list)
        and line["words"]
        and all(
            isinstance(word, dict)
            and isinstance(word.get("text"), str)
            and word["text"].strip()
            and isinstance(word.get("start_ms"), int | float)
            and isinstance(word.get("end_ms"), int | float)
            and word["end_ms"] > word["start_ms"]
            for word in line["words"]
        )
        for line in lyric_lines
    )


def _alignment_line_tokens(line: dict[str, Any], *, character_alignment: bool) -> list[dict[str, Any]]:
    text = line["text"]
    line_agent = line.get("agent") if isinstance(line.get("agent"), str) and line["agent"].strip() else "v1"
    line_is_background = line.get("isBackground") is True
    tokens: list[dict[str, Any]] = []
    parenthesis_depth = 0
    source_tokens = (
        [character for character in text if not character.isspace()] if character_alignment else text.split()
    )

    for source_token in source_tokens:
        opens = source_token.count("(")
        closes = source_token.count(")")
        is_background = line_is_background or parenthesis_depth > 0 or opens > 0
        token_text = source_token.replace("(", "").replace(")", "")
        parenthesis_depth += opens - closes
        if parenthesis_depth < 0:
            raise ValueError(f"Unbalanced background-vocal parentheses in lyric line: {text!r}")
        if not token_text:
            continue
        token = {"text": token_text, "agent": line_agent}
        if is_background:
            token["isBackground"] = True
        tokens.append(token)
    if parenthesis_depth:
        raise ValueError(f"Unbalanced background-vocal parentheses in lyric line: {text!r}")
    return tokens


def _alignment_units(text: str, language: str) -> list[str]:
    if not any(character.isdigit() for character in text):
        return [text]

    from num2words import num2words

    language_codes = {
        "ara": "ar",
        "chi": "zh",
        "deu": "de",
        "eng": "en",
        "fra": "fr",
        "ita": "it",
        "jpn": "ja",
        "kor": "ko",
        "por": "pt",
        "rus": "ru",
        "spa": "es",
    }
    number_language = language_codes.get(language, language)

    def replace_number(match: re.Match[str]) -> str:
        try:
            return f" {num2words(int(match.group()), lang=number_language)} "
        except NotImplementedError as error:
            raise ValueError(f"Numeric lyric alignment is not supported for language {language!r}") from error

    expanded = re.sub(r"\d+", replace_number, text)
    normalized = re.sub(r"[^\w'’-]+", " ", expanded, flags=re.UNICODE)
    if language in {"chi", "jpn"}:
        return [character for character in normalized if not character.isspace()]
    return normalized.split()


def _is_alignment_healthy(
    output_lines: list[dict[str, Any]],
    raw_lines: list[dict[str, Any]] | None = None,
) -> bool:
    """Validate forced alignment quality and detect acoustic trellis collapse or severe drift."""
    if not output_lines:
        return False

    for line in output_lines:
        words = line.get("words")
        if not words or not isinstance(words, list):
            return False
        start_ms = line.get("start_ms")
        end_ms = line.get("end_ms")
        if start_ms is None or end_ms is None or end_ms <= start_ms:
            return False

    squashed_consecutive = 0
    for line in output_lines:
        words = line["words"]
        line_duration_ms = line["end_ms"] - line["start_ms"]
        word_count = len(words)
        avg_word_dur_ms = line_duration_ms / max(1, word_count)
        avg_conf = sum(w.get("confidence", 0.0) for w in words) / max(1, word_count)

        if word_count >= 3 and avg_word_dur_ms < 50 and avg_conf < 0.05:
            LOGGER.warning("Alignment anomaly: line squashed into <50ms/word with low confidence (%.3f)", avg_conf)
            return False

        if avg_word_dur_ms < 85 and avg_conf < 0.15:
            squashed_consecutive += 1
            if squashed_consecutive >= 2:
                LOGGER.warning(
                    "Alignment anomaly: consecutive squashed lines with low confidence (<85ms/word, %.3f)",
                    avg_conf,
                )
                return False
        else:
            squashed_consecutive = 0

    if raw_lines and len(raw_lines) == len(output_lines):
        severe_drift_count = 0
        for raw_line, out_line in zip(raw_lines, output_lines, strict=False):
            raw_start_ms = raw_line.get("start_ms")
            if not isinstance(raw_start_ms, int | float) or raw_start_ms <= 0:
                continue
            aligned_start_ms = out_line["start_ms"]
            drift_sec = abs(aligned_start_ms - raw_start_ms) / 1000.0
            words = out_line.get("words", [])
            avg_conf = sum(w.get("confidence", 0.0) for w in words) / max(1, len(words)) if words else 0.0

            if drift_sec > 30.0:
                LOGGER.warning(
                    "Alignment anomaly: catastrophic drift (%.1fs) on line %r",
                    drift_sec,
                    out_line.get("text"),
                )
                return False

            if drift_sec > 12.0 and avg_conf < 0.20:
                LOGGER.warning(
                    "Alignment anomaly: drift (%.1fs) with low confidence (%.3f) on line %r",
                    drift_sec,
                    avg_conf,
                    out_line.get("text"),
                )
                return False

            if drift_sec > 15.0:
                severe_drift_count += 1
                if severe_drift_count >= 2:
                    LOGGER.warning("Alignment anomaly: multiple lines (>2) drifting >15s from reference")
                    return False

    return True


def _group_lines_into_macro_sections(
    tokenized_lines: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    gap_threshold_sec: float = 6.0,
) -> list[list[tuple[dict[str, Any], list[dict[str, Any]]]]]:
    """Partition lyric lines into macro-sections bounded by long musical gaps/solos."""
    if not tokenized_lines:
        return []

    sections: list[list[tuple[dict[str, Any], list[dict[str, Any]]]]] = []
    current_section: list[tuple[dict[str, Any], list[dict[str, Any]]]] = [tokenized_lines[0]]

    for i in range(len(tokenized_lines) - 1):
        curr_raw, _ = tokenized_lines[i]
        next_raw, _ = tokenized_lines[i + 1]

        curr_start_sec = float(curr_raw.get("start_ms", 0)) / 1000.0
        next_start_sec = float(next_raw.get("start_ms", 0)) / 1000.0

        curr_raw_end = (
            float(curr_raw["end_ms"]) / 1000.0
            if curr_raw.get("end_ms") is not None and curr_raw["end_ms"] > curr_raw.get("start_ms", 0)
            else curr_start_sec + 4.0
        )
        gap = next_start_sec - curr_raw_end
        if gap >= gap_threshold_sec and next_start_sec > curr_start_sec:
            sections.append(current_section)
            current_section = [tokenized_lines[i + 1]]
        else:
            current_section.append(tokenized_lines[i + 1])

    if current_section:
        sections.append(current_section)

    return sections


def _align_tokenized_lines(
    *,
    model: Any,
    tokenizer: Any,
    waveform: Any,
    tokenized_lines: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    language: str,
    character_alignment: bool,
    generate_emissions: Any,
    preprocess_text: Any,
    get_alignments: Any,
    get_spans: Any,
    postprocess_results: Any,
    time_offset_sec: float = 0.0,
    batch_size: int = 4,
) -> list[dict[str, Any]]:
    """Execute CTC forced alignment across tokenized lines against a waveform."""
    flat_tokens = [token for _, tokens in tokenized_lines for token in tokens]
    alignment_units = [unit for token in flat_tokens for unit in token["alignment_units"]]
    if not alignment_units:
        return []

    emissions, stride = generate_emissions(model, waveform, batch_size=batch_size)
    alignment_text = "".join(alignment_units) if character_alignment else " ".join(alignment_units)
    tokens_starred, text_starred = preprocess_text(
        alignment_text,
        romanize=True,
        language=language,
        split_size="char" if character_alignment else "word",
        star_frequency="segment",
    )
    segments, scores, blank_token = get_alignments(emissions, tokens_starred, tokenizer)
    spans = get_spans(tokens_starred, segments, blank_token)
    aligned = postprocess_results(text_starred, spans, stride, scores)
    if len(aligned) != len(alignment_units):
        raise ValueError(f"CTC aligned {len(aligned)} units but expected {len(alignment_units)}")

    offset_ms = round(time_offset_sec * 1000)
    output_lines: list[dict[str, Any]] = []
    alignment_cursor = 0
    for raw_line, tokens in tokenized_lines:
        words = []
        for index, token in enumerate(tokens):
            unit_count = len(token["alignment_units"])
            token_timings = aligned[alignment_cursor : alignment_cursor + unit_count]
            alignment_cursor += unit_count
            confidences = [max(0.0, min(1.0, math.exp(float(timing["score"])))) for timing in token_timings]
            word_start = round(float(token_timings[0]["start"]) * 1000) + offset_ms
            word_end = round(float(token_timings[-1]["end"]) * 1000) + offset_ms
            word = {
                "text": token["text"] if character_alignment or index + 1 == len(tokens) else f"{token['text']} ",
                "start_ms": word_start,
                "end_ms": max(word_start + 20, word_end),
                "confidence": round(sum(confidences) / len(confidences), 4),
                "agent": token["agent"],
            }
            if token.get("isBackground"):
                word["isBackground"] = True
            words.append(word)
        output_line = {
            "text": raw_line["text"] if character_alignment else " ".join(raw_line["text"].split()),
            "words": words,
            "start_ms": min(word["start_ms"] for word in words),
            "end_ms": max(word["end_ms"] for word in words),
            "agent": raw_line.get("agent") or "v1",
        }
        if raw_line.get("isBackground") is True:
            output_line["isBackground"] = True
        output_lines.append(output_line)
    return output_lines


def _align_known_lyrics(
    vocals_path: Path, document: dict[str, Any], config: dict[str, Any],
    *, provenance: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    import torch
    from ctc_forced_aligner import (
        generate_emissions,
        get_alignments,
        get_spans,
        load_alignment_model,
        load_audio,
        postprocess_results,
        preprocess_text,
    )
    from huggingface_hub import snapshot_download

    raw_lines = document.get("lines")
    if not isinstance(raw_lines, list):
        raise ValueError("Known lyrics do not contain lines")
    language = _alignment_language(config["language"], document.get("metadata"))
    if provenance is not None:
        provenance.update(language=language, strategy="global_ctc")
    character_alignment = language in {"chi", "jpn"}
    tokenized_lines: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for line in raw_lines:
        if not isinstance(line, dict) or not isinstance(line.get("text"), str):
            continue
        tokens = _alignment_line_tokens(line, character_alignment=character_alignment)
        if tokens:
            for token in tokens:
                token["alignment_units"] = _alignment_units(token["text"], language)
            tokenized_lines.append((line, tokens))
    flat_tokens = [token for _, tokens in tokenized_lines for token in tokens]
    alignment_units = [unit for token in flat_tokens for unit in token["alignment_units"]]
    if not alignment_units:
        raise ValueError("Known lyrics do not contain words")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    model_path = snapshot_download(
        repo_id=CTC_ALIGNER_MODEL,
        revision=CTC_ALIGNER_MODEL_REVISION,
        cache_dir=WORK_DIR / "models",
    )
    model, tokenizer = load_alignment_model(device, model_path=model_path, dtype=dtype)
    waveform = load_audio(str(vocals_path), model.dtype, model.device)

    has_line_timestamps = any(
        isinstance(raw_line.get("start_ms"), int | float) and raw_line["start_ms"] > 0
        for raw_line, _ in tokenized_lines
    )

    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    raw_lines_for_check = [line for line, _ in tokenized_lines]
    output_lines: list[dict[str, Any]] = []

    # --- Tier 1: Global Continuous MMS CTC Alignment (Quality-First) ---
    global_succeeded = False
    try:
        candidate_lines = _align_tokenized_lines(
            model=model,
            tokenizer=tokenizer,
            waveform=waveform,
            tokenized_lines=tokenized_lines,
            language=language,
            character_alignment=character_alignment,
            generate_emissions=generate_emissions,
            preprocess_text=preprocess_text,
            get_alignments=get_alignments,
            get_spans=get_spans,
            postprocess_results=postprocess_results,
            time_offset_sec=0.0,
            batch_size=4,
        )
        if _is_alignment_healthy(candidate_lines, raw_lines_for_check):
            output_lines = candidate_lines
            global_succeeded = True
            LOGGER.info("Global continuous CTC alignment succeeded with healthy metrics")
        else:
            LOGGER.warning("Global continuous CTC alignment detected as anomalous (trellis drift/collapse)")
            if provenance is not None:
                provenance["fallback_reason"] = "global_alignment_failed_health_checks"
    except Exception as error:
        if provenance is not None:
            provenance["fallback_reason"] = str(error)
        LOGGER.warning("Global continuous CTC alignment failed: %s", error)

    # --- Tier 2: Anchor-Guided Macro-Section Alignment (Recovery for long instrumental solos) ---
    if not global_succeeded:
        if has_line_timestamps:
            LOGGER.info("Attempting Tier 2 anchor-guided macro-section alignment")
            sections = _group_lines_into_macro_sections(tokenized_lines, gap_threshold_sec=6.0)
            sample_rate = 16000
            total_samples = waveform.shape[-1]
            audio_duration_sec = total_samples / sample_rate
            macro_output_lines = []
            try:
                for section in sections:
                    first_raw, _ = section[0]
                    last_raw, _ = section[-1]
                    sec_start_ref = float(first_raw.get("start_ms", 0)) / 1000.0
                    sec_end_ref = (
                        float(last_raw.get("end_ms", 0)) / 1000.0
                        if last_raw.get("end_ms") is not None
                        else float(last_raw.get("start_ms", 0)) / 1000.0 + 4.0
                    )
                    clip_start_sec = max(0.0, sec_start_ref - 1.5)
                    clip_end_sec = min(audio_duration_sec, sec_end_ref + 2.0)
                    if clip_end_sec <= clip_start_sec:
                        clip_end_sec = min(audio_duration_sec, clip_start_sec + 5.0)

                    start_sample = int(clip_start_sec * sample_rate)
                    end_sample = min(total_samples, int(clip_end_sec * sample_rate))
                    if end_sample <= start_sample:
                        end_sample = min(total_samples, start_sample + sample_rate)

                    section_waveform = waveform[..., start_sample:end_sample]
                    aligned_section = _align_tokenized_lines(
                        model=model,
                        tokenizer=tokenizer,
                        waveform=section_waveform,
                        tokenized_lines=section,
                        language=language,
                        character_alignment=character_alignment,
                        generate_emissions=generate_emissions,
                        preprocess_text=preprocess_text,
                        get_alignments=get_alignments,
                        get_spans=get_spans,
                        postprocess_results=postprocess_results,
                        time_offset_sec=clip_start_sec,
                        batch_size=1,
                    )
                    macro_output_lines.extend(aligned_section)

                if _is_alignment_healthy(macro_output_lines, raw_lines_for_check):
                    output_lines = macro_output_lines
                    if provenance is not None:
                        provenance["strategy"] = "macro_section_ctc"
                    LOGGER.info("Tier 2 macro-section alignment succeeded with healthy metrics")
                else:
                    raise RuntimeError("Tier 2 macro-section alignment failed health checks")
            except Exception as error:
                LOGGER.warning("Tier 2 macro-section alignment failed: %s", error)
                raise RuntimeError(f"Forced alignment failed health verification: {error}") from error
        else:
            raise RuntimeError("Global alignment unhealthy and no reference timestamps available for macro-sections")
    lyrics_module = _load_lyrics_module()
    sanitized_lines = lyrics_module.sanitize_lyrics_lines(output_lines)
    lyrics = {"version": "1.0", "metadata": metadata, "lines": sanitized_lines}
    alignment_words = []
    for line_idx, line in enumerate(sanitized_lines):
        for word_idx, word in enumerate(line.get("words", [])):
            alignment_word = {
                "id": f"s{line_idx}-w{word_idx}",
                "start": round(word["start_ms"] / 1000, 3),
                "end": round(word["end_ms"] / 1000, 3),
                "text": word["text"].strip(),
                "probability": word.get("confidence", 1.0),
            }
            if "agent" in word:
                alignment_word["agent"] = word["agent"]
            if word.get("isBackground"):
                alignment_word["isBackground"] = True
            alignment_words.append(alignment_word)
    return lyrics_module.validate_lyrics_file(lyrics, require_words=True), alignment_words


def _alignment_language(language: str, metadata: Any) -> str:
    value = language
    if value == "auto" and isinstance(metadata, dict):
        value = str(metadata.get("language") or "")
    primary = value.split("-", maxsplit=1)[0].lower()
    codes = {
        "ar": "ara",
        "de": "deu",
        "en": "eng",
        "es": "spa",
        "fr": "fra",
        "it": "ita",
        "ja": "jpn",
        "ko": "kor",
        "pt": "por",
        "ru": "rus",
        "zh": "chi",
    }
    if len(primary) == 3:
        return primary
    if primary not in codes:
        raise ValueError(f"CTC alignment needs an ISO 639-3 language code, not {language!r}")
    return codes[primary]


def _transcript_to_lyrics(transcript: dict[str, Any]) -> dict[str, Any]:
    lines = []
    for segment in transcript["segments"]:
        source_words = segment.get("words") or []
        if not source_words:
            continue
        words = []
        for index, word in enumerate(source_words):
            words.append(
                {
                    "text": f"{word['text']} " if index + 1 < len(source_words) else word["text"],
                    "start_ms": round(float(word["start"]) * 1000),
                    "end_ms": round(float(word["end"]) * 1000),
                    "confidence": round(float(word.get("probability", 0)), 4),
                }
            )
        lines.append(
            {
                "text": " ".join(word["text"] for word in source_words),
                "words": words,
                "start_ms": words[0]["start_ms"],
                "end_ms": words[-1]["end_ms"],
            }
        )
    song = transcript["song"]
    metadata = {
        "title": song["title"],
        "duration_ms": round(float(song["duration"]) * 1000),
        "language": transcript["transcription"]["language"],
    }
    if song.get("artist") or song.get("uploader"):
        metadata["artist"] = song.get("artist") or song["uploader"]
    if song.get("album"):
        metadata["album"] = song["album"]
    lyrics_module = _load_lyrics_module()
    sanitized_lines = lyrics_module.sanitize_lyrics_lines(lines)
    return lyrics_module.validate_lyrics_file(
        {"version": "1.0", "metadata": metadata, "lines": sanitized_lines}, require_words=True
    )


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
            "artist": metadata.get("artist"),
            "album": metadata.get("album"),
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
        should_break = current and (len(current) >= max_lines or gap >= break_silence or duration > max_duration)
        if should_break:
            grouped_lines.append(current)
            current = []
        current.append(segment)
    if current:
        grouped_lines.append(current)
    return grouped_lines


def _page_words(page: dict[str, Any]) -> list[dict[str, Any]]:
    return [word for line in page["lines"] for word in line["words"]]


def _normalize_karaoke_timeline(words: list[dict[str, Any]], event_start_cs: int) -> tuple[list[int], list[int], int]:
    word_starts_cs: list[int] = []
    for word in words:
        earliest_start_cs = word_starts_cs[-1] + 1 if word_starts_cs else event_start_cs
        word_starts_cs.append(max(earliest_start_cs, _to_centiseconds(word["start"])))

    karaoke_end_cs = max(word_starts_cs[-1] + 1, _to_centiseconds(words[-1]["end"]))
    durations_cs = [
        following_start_cs - start_cs
        for start_cs, following_start_cs in zip(word_starts_cs, [*word_starts_cs[1:], karaoke_end_cs], strict=True)
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
        display_start_cs = desired_display_start_cs if next_display_start_cs is None else next_display_start_cs
        word_starts_cs, durations_cs, karaoke_end_cs = _normalize_karaoke_timeline(words, display_start_cs)
        desired_display_end_cs = max(karaoke_end_cs, _to_centiseconds(words[-1]["end"]) + tail_centiseconds)

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
        "WrapStyle: 1",
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


def _render_video(
    audio_path: Path,
    output_path: Path,
    config: dict[str, Any],
    ass_path: Path | None = None,
) -> None:
    video = config["video"]
    width = video["width"]
    height = video["height"]
    fps = video["fps"]
    duration = _probe_duration(audio_path)
    background = config["background"]
    watermark = config.get("watermark")
    intro_card = config.get("intro_card")
    subtitle_filter = f"ass={_escape_filter_path(ass_path)}" if ass_path is not None else None
    if subtitle_filter and config.get("fonts_dir"):
        subtitle_filter += f":fontsdir={_escape_filter_path(Path(config['fonts_dir']))}"

    if background["kind"] == "video":
        input_args = ["-stream_loop", "-1", "-i", str(background["value"])]
        bg_chain = "[0:v]setpts=PTS-STARTPTS[bg]"
    elif background["kind"] == "image":
        background_path = Path(background["value"])
        if not background_path.is_file():
            raise FileNotFoundError(f"Uploaded background not found: {background_path}")
        overlay_opacity = background.get("overlay_opacity", 0)
        input_args = ["-loop", "1", "-framerate", str(fps), "-i", str(background_path)]
        bg_filters = [f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"]
        if overlay_opacity > 0:
            bg_filters.append(f"drawbox=x=0:y=0:w=iw:h=ih:color=black@{overlay_opacity:.2f}:t=fill")
        bg_chain = f"[0:v]{','.join(bg_filters)}[bg]"
    else:
        color = background["value"].lstrip("#")
        input_args = ["-f", "lavfi", "-i", f"color=c=0x{color}:s={width}x{height}:r={fps}"]
        bg_chain = "[0:v]null[bg]"

    has_watermark = bool(watermark and watermark.get("path"))
    has_intro = bool(intro_card and intro_card.get("path"))

    lyrics_overlay = config.get("lyrics_overlay")
    if has_watermark or has_intro or lyrics_overlay:
        extra_inputs = []
        filter_chains = [bg_chain]
        current_stream = "bg"
        next_input_idx = 2

        if has_watermark:
            watermark_path = Path(watermark["path"])
            if not watermark_path.is_file():
                raise FileNotFoundError(f"Watermark not found: {watermark_path}")
            scale = float(watermark.get("scale", 0.18))
            margin = float(watermark.get("margin", 0.05))
            opacity = float(watermark.get("opacity", 0.85))
            position = watermark.get("position", "top_left")

            extra_inputs.extend(["-loop", "1", "-framerate", str(fps), "-i", str(watermark_path)])
            target_w = int(width * scale)
            wm_chain = f"[{next_input_idx}:v]scale=w={target_w}:h=-1,format=rgba,colorchannelmixer=aa={opacity:.2f}[wm]"
            filter_chains.append(wm_chain)

            pos_expressions = {
                "top_left": f"x=main_w*{margin:.2f}:y=main_h*{margin:.2f}",
                "top_right": f"x=main_w-overlay_w-(main_w*{margin:.2f}):y=main_h*{margin:.2f}",
                "bottom_left": f"x=main_w*{margin:.2f}:y=main_h-overlay_h-(main_h*{margin:.2f})",
                "bottom_right": f"x=main_w-overlay_w-(main_w*{margin:.2f}):y=main_h-overlay_h-(main_h*{margin:.2f})",
            }
            overlay_coords = pos_expressions.get(position, pos_expressions["top_left"])
            filter_chains.append(f"[{current_stream}][wm]overlay={overlay_coords}[v_wm]")
            current_stream = "v_wm"
            next_input_idx += 1

        if has_intro:
            intro_card_path = Path(intro_card["path"])
            if not intro_card_path.is_file():
                raise FileNotFoundError(f"Intro card not found: {intro_card_path}")
            intro_start = float(intro_card.get("start", 0.0))
            intro_end = float(intro_card.get("end", 5.0))
            fade_dur = min(0.6, (intro_end - intro_start) / 4)
            fade_out_st = max(intro_start, intro_end - fade_dur)

            extra_inputs.extend(["-loop", "1", "-framerate", str(fps), "-i", str(intro_card_path)])
            if intro_start > 0:
                intro_fade_chain = (
                    f"[{next_input_idx}:v]format=rgba,"
                    f"fade=t=in:st={intro_start:.2f}:d={fade_dur:.2f}:alpha=1,"
                    f"fade=t=out:st={fade_out_st:.2f}:d={fade_dur:.2f}:alpha=1[intro_faded]"
                )
            else:
                intro_fade_chain = (
                    f"[{next_input_idx}:v]format=rgba,"
                    f"fade=t=out:st={fade_out_st:.2f}:d={fade_dur:.2f}:alpha=1[intro_faded]"
                )
            filter_chains.append(intro_fade_chain)
            filter_chains.append(
                f"[{current_stream}][intro_faded]overlay=0:0:enable='between(t,{intro_start:.2f},{intro_end:.2f})'[v_intro]"
            )
            current_stream = "v_intro"
            next_input_idx += 1

        if lyrics_overlay:
            if not Path(lyrics_overlay).is_file():
                raise FileNotFoundError(f"Lyrics overlay not found: {lyrics_overlay}")
            extra_inputs.extend(["-i", str(lyrics_overlay)])
            filter_chains.append(f"[{current_stream}][{next_input_idx}:v]overlay=0:0:shortest=1[v_lyrics]")
            current_stream = "v_lyrics"
        if ass_path is not None:
            filter_chains.append(f"[{current_stream}]{subtitle_filter}[v_out]")
        else:
            filter_chains.append(f"[{current_stream}]null[v_out]")

        filter_complex = ";".join(filter_chains)
        filter_args = ["-filter_complex", filter_complex]
        video_map = "[v_out]"
    else:
        extra_inputs = []
        video_map = "0:v:0"
        if background["kind"] == "video":
            video_filter = subtitle_filter
        elif background["kind"] == "image":
            filters = [
                f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
            ]
            if overlay_opacity > 0:
                filters.append(f"drawbox=x=0:y=0:w=iw:h=ih:color=black@{overlay_opacity:.2f}:t=fill")
            if ass_path is not None:
                filters.append(subtitle_filter)
            video_filter = ",".join(filters)
        else:
            video_filter = subtitle_filter

        filter_args = ["-vf", video_filter] if video_filter else []

    base_command = [
        "ffmpeg",
        "-y",
        *input_args,
        "-i",
        str(audio_path),
        *extra_inputs,
        "-map",
        video_map,
        "-map",
        "1:a:0",
        *filter_args,
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


def _ensure_system_fonts() -> None:
    """Ensure typography packages such as Inter font are available in the runtime."""
    if not shutil.which("apt-get"):
        return
    if shutil.which("fc-match"):
        result = subprocess.run(["fc-match", "Inter:bold"], capture_output=True, text=True, check=False)
        if "inter" in result.stdout.lower():
            return
    try:
        LOGGER.info("Installing system fonts (fonts-inter)...")
        install_res = subprocess.run(["apt-get", "install", "-y", "-qq", "fonts-inter"], check=False)
        if install_res.returncode != 0:
            subprocess.run(["apt-get", "update", "-qq"], check=False)
            subprocess.run(["apt-get", "install", "-y", "-qq", "fonts-inter"], check=False)
        if shutil.which("fc-cache"):
            subprocess.run(["fc-cache", "-f"], check=False)
    except Exception as exc:
        LOGGER.warning("Failed to ensure system fonts: %s", exc)


BEBAS_NEUE_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/bebasneue/BebasNeue-Regular.ttf"


def _ensure_bebas_font() -> None:
    """Ensure Bebas Neue font is available in fontconfig for subtitle rendering."""
    if shutil.which("fc-match"):
        result = subprocess.run(["fc-match", "Bebas Neue"], capture_output=True, text=True, check=False)
        if "bebas" in result.stdout.lower():
            return

    installed = False
    if shutil.which("apt-get"):
        try:
            LOGGER.info("Installing system fonts (fonts-bebas-neue)...")
            install_res = subprocess.run(["apt-get", "install", "-y", "-qq", "fonts-bebas-neue"], check=False)
            if install_res.returncode == 0:
                installed = True
        except Exception as exc:
            LOGGER.warning("apt-get install fonts-bebas-neue failed: %s", exc)

    if not installed:
        try:
            font_dir = Path("/usr/local/share/fonts/truetype/bebasneue")
            try:
                font_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                font_dir = Path.home() / ".local/share/fonts"
                font_dir.mkdir(parents=True, exist_ok=True)

            font_path = font_dir / "BebasNeue-Regular.ttf"
            if not font_path.is_file():
                LOGGER.info("Downloading Bebas Neue font from Google Fonts...")
                req = urllib.request.Request(BEBAS_NEUE_URL, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as response:
                    font_path.write_bytes(response.read())
                installed = True
        except Exception as exc:
            LOGGER.warning("Failed to download Bebas Neue font: %s", exc)

    if installed and shutil.which("fc-cache"):
        subprocess.run(["fc-cache", "-f"], check=False)


PLAYWRIGHT_PACKAGE = "playwright==1.62.0"


def _run(command: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    LOGGER.info("Running %s", " ".join(command))
    try:
        return subprocess.run(command, check=True, capture_output=capture_output, text=True)
    except subprocess.CalledProcessError as error:
        details = (error.stderr or error.stdout or "").strip()
        if details:
            raise RuntimeError(f"Command {' '.join(command)} failed ({error.returncode}):\n{details}") from error
        raise


def _run_installer(command: list[str], *, label: str = "Package") -> subprocess.CompletedProcess[str]:
    """Execute an installation command, capturing and reporting full output if it fails."""
    LOGGER.info("Running installation: %s", " ".join(command))
    try:
        return _run(command, capture_output=True)
    except Exception as error:
        error_msg = f"{label} installation failed: {error}"
        LOGGER.error("%s", error_msg)
        raise RuntimeError(error_msg) from error


def _ensure_playwright() -> None:
    """Ensure the Playwright Python package and Chromium browser are installed."""
    if importlib.util.find_spec("playwright") is None:
        LOGGER.info("Installing Playwright Python package...")
        installer = (
            ["uv", "pip", "install", "--system", PLAYWRIGHT_PACKAGE]
            if shutil.which("uv")
            else [sys.executable, "-m", "pip", "install", PLAYWRIGHT_PACKAGE]
        )
        _run_installer(installer, label="Playwright Python package")

    LOGGER.info("Installing Chromium and dependencies via Playwright...")
    _run_installer(
        [sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"],
        label="Playwright Chromium and system dependencies",
    )


def _require_commands(*commands: str) -> None:
    missing = [command for command in commands if not shutil.which(command)]
    if missing:
        raise RuntimeError(f"Missing required commands: {', '.join(missing)}")


def _run_with_status() -> None:
    STATUS_PATH.unlink(missing_ok=True)
    try:
        main()
    except Exception as error:
        status = {"status": "failed", "error": str(error)}
        if isinstance(error, LyricsPreparationError):
            status["recovery_archive_path"] = str(error.recovery_archive_path)
            status["stage"] = "lyrics"
        STATUS_PATH.write_text(
            json.dumps(status, ensure_ascii=False), encoding="utf-8"
        )
        raise
    STATUS_PATH.write_text(json.dumps({"status": "completed"}), encoding="utf-8")


if __name__ == "__main__":
    _run_with_status()
