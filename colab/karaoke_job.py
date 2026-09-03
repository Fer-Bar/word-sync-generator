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
    if config.get("operation") == "render":
        _render_existing_job(config)
        return

    _configure_huggingface()

    source_path, metadata = _acquire_source(config)
    mixture_path = _prepare_mixture(source_path)
    vocals_path, instrumental_path = _separate_vocals(mixture_path, config["demucs_model"])
    lyrics, alignment = _prepare_lyrics(vocals_path, metadata, config)

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
    lyrics_module = _load_lyrics_module()
    lyrics_path.write_text(lyrics_module.dump_lyrics_file(lyrics), encoding="utf-8")
    alignment_path.write_text(json.dumps(alignment, ensure_ascii=False, indent=2), encoding="utf-8")

    background = {"kind": config["background"]["kind"], "color": "#0B1020"}
    if config["background"]["kind"] == "image":
        source_background = Path(config["background"]["value"])
        background_path = output_dir / f"background{source_background.suffix.lower()}"
        shutil.copy2(source_background, background_path)
        background["path"] = background_path.name
    else:
        background["color"] = config["background"]["value"]
    job_document = {
        "schema_version": 1,
        "job_id": config["job_id"],
        "title": metadata["title"],
        "source": metadata,
        "alignment": {key: value for key, value in alignment.items() if key != "words"},
        "media": {
            "original_audio": original_audio.name,
            "vocals_audio": vocals_flac.name,
            "instrumental_audio": instrumental_flac.name,
            "lyrics": lyrics_path.name,
        },
        "video": config["video"],
        "background": background,
    }
    (output_dir / "job.json").write_text(json.dumps(job_document, ensure_ascii=False, indent=2), encoding="utf-8")

    _create_archive(output_dir, Path(config["archive_path"]))
    LOGGER.info("Pipeline completed: %s", config["archive_path"])


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
    title = _safe_filename(document["title"])
    background = document["background"]
    render_background = {
        "kind": background["kind"],
        "value": str(job_dir / background["path"]) if background["kind"] == "image" else background["color"],
        "overlay_opacity": background.get("overlay_opacity", 0.38),
    }
    for mode in modes:
        source_ass = job_dir / f"{mode}.ass"
        if not source_ass.is_file():
            raise FileNotFoundError(f"Missing generated {mode} ASS file in render bundle")
        audio_path = job_dir / document["media"][audio_keys[mode]]
        video_path = output_dir / f"{title}_{mode}.mp4"
        if mode == "lyrics":
            subtitles_dir = output_dir / "subtitles"
            subtitles_dir.mkdir(parents=True, exist_ok=True)
            ass_path = subtitles_dir / f"{title}_{mode}.ass"
            shutil.copy2(source_ass, ass_path)
            _render_video(
                audio_path,
                video_path,
                {"video": document["video"], "background": render_background},
                ass_path=ass_path,
            )
        else:
            ass_path = output_dir / f"{title}_{mode}.ass"
            shutil.copy2(source_ass, ass_path)
            _render_video(
                audio_path,
                video_path,
                {"video": document["video"], "background": render_background},
                ass_path=None,
            )
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
    vocals_path: Path, metadata: dict[str, Any], config: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    lyrics_module = _load_lyrics_module()
    record = None if config.get("lyrics", {}).get("disable_lrclib") else _fetch_lrclib(metadata, config)
    if record is not None:
        try:
            document = _lyrics_document_from_record(record, metadata, config)
            if _has_complete_word_timings(document):
                lyrics = lyrics_module.validate_lyrics_file(document, require_words=True)
                return lyrics, {
                    "engine": "lrclib",
                    "lrclib_id": record.get("id"),
                    "word_timing": "provided",
                }
            lyrics, words = _align_known_lyrics(vocals_path, document, config)
            return lyrics, {
                "engine": "ctc-forced-aligner",
                "model": CTC_ALIGNER_MODEL,
                "model_revision": CTC_ALIGNER_MODEL_REVISION,
                "lrclib_id": record.get("id"),
                "word_timing": "generated",
                "words": words,
            }
        except (AssertionError, KeyError, RuntimeError, ValueError) as error:
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
    title_ratio_base = (
        SequenceMatcher(None, source_base, cand_base).ratio() if source_base and cand_base else 0.0
    )

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
    if source_editions and candidate_editions and not (source_editions & candidate_editions):
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
            ratio_primary = (
                SequenceMatcher(None, norm_primary, norm_cand_artist).ratio() if norm_primary else 0.0
            )
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
                score = _lrclib_match_score(
                    value, metadata, track=track, artist=artist, duration=duration
                )
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
                score = _lrclib_match_score(
                    value, metadata, track=track, artist=artist, duration=duration
                )
                LOGGER.info(
                    "LRCLIB selected id=%s score=%.2f via get-without-album", value.get("id"), score
                )
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
                score = _lrclib_match_score(
                    value, metadata, track=track, artist=artist, duration=duration
                )
                LOGGER.info(
                    "LRCLIB selected id=%s score=%.2f via get-primary-artist", value.get("id"), score
                )
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
                key=lambda c: _lrclib_match_score(
                    c, metadata, track=track, artist=artist, duration=duration
                ),
            )
            score = _lrclib_match_score(
                selected, metadata, track=track, artist=artist, duration=duration
            )
            LOGGER.info(
                "LRCLIB selected id=%s score=%.2f via structured-search", selected.get("id"), score
            )
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
                key=lambda c: _lrclib_match_score(
                    c, metadata, track=track, artist=artist, duration=duration
                ),
            )
            score = _lrclib_match_score(
                selected, metadata, track=track, artist=artist, duration=duration
            )
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
                and any(
                    isinstance(line, dict) and str(line.get("text") or "").strip() for line in raw_lines
                )
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
        lines = []
        for raw_line in synced_source.splitlines():
            text = re.sub(r"^\[\d{1,3}:\d{2}(?:\.\d{2,3})?\]\s*", "", raw_line).strip()
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


def _align_known_lyrics(
    vocals_path: Path, document: dict[str, Any], config: dict[str, Any]
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
    emissions, stride = generate_emissions(model, waveform, batch_size=4)
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

    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    output_lines = []
    alignment_cursor = 0
    for raw_line, tokens in tokenized_lines:
        words = []
        for index, token in enumerate(tokens):
            unit_count = len(token["alignment_units"])
            token_timings = aligned[alignment_cursor : alignment_cursor + unit_count]
            alignment_cursor += unit_count
            confidences = [max(0.0, min(1.0, math.exp(float(timing["score"])))) for timing in token_timings]
            word = {
                "text": token["text"] if character_alignment or index + 1 == len(tokens) else f"{token['text']} ",
                "start_ms": round(float(token_timings[0]["start"]) * 1000),
                "end_ms": round(float(token_timings[-1]["end"]) * 1000),
                "confidence": round(sum(confidences) / len(confidences), 4),
                "agent": token["agent"],
            }
            if token.get("isBackground"):
                word["isBackground"] = True
            words.append(word)
        output_line = {
            "text": raw_line["text"],
            "words": words,
            "start_ms": min(word["start_ms"] for word in words),
            "end_ms": max(word["end_ms"] for word in words),
            "agent": raw_line.get("agent") or "v1",
        }
        if raw_line.get("isBackground") is True:
            output_line["isBackground"] = True
        output_lines.append(output_line)
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

    if background["kind"] == "image":
        background_path = Path(background["value"])
        if not background_path.is_file():
            raise FileNotFoundError(f"Uploaded background not found: {background_path}")
        overlay_opacity = background.get("overlay_opacity", 0.38)
        input_args = ["-loop", "1", "-framerate", str(fps), "-i", str(background_path)]
        filters = [
            f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
        ]
        if overlay_opacity > 0:
            filters.append(f"drawbox=x=0:y=0:w=iw:h=ih:color=black@{overlay_opacity:.2f}:t=fill")
        if ass_path is not None:
            filters.append(f"ass={_escape_filter_path(ass_path)}")
        video_filter = ",".join(filters)
    else:
        color = background["value"].lstrip("#")
        input_args = ["-f", "lavfi", "-i", f"color=c=0x{color}:s={width}x{height}:r={fps}"]
        video_filter = f"ass={_escape_filter_path(ass_path)}" if ass_path is not None else None

    filter_args = ["-vf", video_filter] if video_filter else []

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
