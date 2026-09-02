import importlib.util
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
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
    source_ass = job_dir / "lyrics.ass"
    if not source_ass.is_file():
        raise FileNotFoundError("Missing generated ASS file in render bundle")
    background = document["background"]
    render_background = {
        "kind": background["kind"],
        "value": str(job_dir / background["path"]) if background["kind"] == "image" else background["color"],
    }
    for mode in modes:
        audio_path = job_dir / document["media"][audio_keys[mode]]
        ass_path = output_dir / f"{title}_{mode}.ass"
        video_path = output_dir / f"{title}_{mode}.mp4"
        shutil.copy2(source_ass, ass_path)
        _render_video(audio_path, ass_path, video_path, {"video": document["video"], "background": render_background})
    _create_archive(output_dir, Path(config["archive_path"]))


def _load_lyrics_module() -> Any:
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
    words = [word for segment in transcript["segments"] for word in segment["words"]]
    return lyrics, {
        "engine": "faster-whisper",
        "model": config["whisper_model"],
        "language": transcript["transcription"]["language"],
        "word_timing": "generated",
        "words": words,
    }


def _artist_variants(artist: str | None) -> list[str]:
    if not artist:
        return []
    parts: list[str] = []
    for separator in (",", ";"):
        if separator in artist:
            parts.extend(part.strip() for part in artist.split(separator) if part.strip())
            break
    if not parts:
        parts = [artist.strip()]
    expanded: list[str] = []
    for part in parts:
        lower = part.lower()
        for pattern in ("feat.", "ft.", "featuring", "x", "with"):
            idx = lower.find(pattern)
            if idx != -1:
                prefix = part[:idx].strip()
                suffix = part[idx + len(pattern) :].strip()
                if prefix:
                    expanded.append(prefix)
                if suffix:
                    expanded.append(suffix)
                break
        else:
            expanded.append(part)
    seen: set[str] = set()
    result: list[str] = []
    for value in [artist] + expanded:
        key = _match_text(value)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _title_variants(track: str) -> list[str]:
    candidates: list[str] = [track]
    stripped = re.sub(r"\s*\([^)]*\)\s*", " ", track).strip()
    stripped = re.sub(r"\s*\[[^\]]*\]\s*", " ", stripped).strip()
    stripped = " ".join(stripped.split())
    if stripped and _match_text(stripped) != _match_text(track):
        candidates.append(stripped)
    return candidates


def _fetch_lrclib(metadata: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    forced_id = config.get("lyrics", {}).get("lrclib_id")
    if forced_id is not None:
        try:
            value = _lrclib_request(f"/get/{int(forced_id)}")
        except (OSError, ValueError) as error:
            raise RuntimeError(f"Unable to load requested LRCLIB id {forced_id}: {error}") from error
        if not isinstance(value, dict):
            raise RuntimeError(f"LRCLIB id {forced_id} returned an invalid record")
        return value

    track = str(metadata.get("track") or metadata["title"])
    artist = metadata.get("artist")
    album = metadata.get("album")
    duration = metadata.get("duration")
    duration_str = str(round(float(duration))) if duration else ""
    titles = _title_variants(track)
    artists = _artist_variants(artist)

    if artists:
        for title in titles:
            for artist_variant in artists:
                for with_album in (bool(album), False):
                    parameters: dict[str, str] = {
                        "track_name": title,
                        "artist_name": artist_variant,
                        "duration": duration_str,
                    }
                    if with_album and album:
                        parameters["album_name"] = str(album)
                    try:
                        value = _lrclib_request(f"/get?{urllib.parse.urlencode(parameters)}")
                        if isinstance(value, dict) and _usable_lrclib_record(value):
                            LOGGER.info("Using LRCLIB record %s: %s", value.get("id"), value.get("trackName"))
                            return value
                    except OSError:
                        continue

    seen_ids: set[int] = set()
    candidates: list[dict[str, Any]] = []
    queries = []
    if artists:
        queries.append(f"{artists[0]} {titles[0]}")
    queries.append(titles[0])
    if artists:
        queries.append(f"{artist} {track}")
    if len(titles) > 1:
        if artists:
            queries.append(f"{artists[0]} {titles[1]}")
        queries.append(titles[1])
    queries = list(dict.fromkeys(queries))

    for query in queries:
        try:
            results = _lrclib_request(f"/search?{urllib.parse.urlencode({'q': query})}")
        except OSError as error:
            LOGGER.warning("LRCLIB search query %r failed: %s", query, error)
            continue
        if not isinstance(results, list):
            continue
        for record in results:
            if not isinstance(record, dict):
                continue
            record_id = record.get("id")
            if isinstance(record_id, int) and record_id in seen_ids:
                continue
            if isinstance(record_id, int):
                seen_ids.add(record_id)
            if _usable_lrclib_record(record) and _lrclib_match_score(record, metadata) >= 1.25:
                candidates.append(record)
    if not candidates:
        LOGGER.info("LRCLIB did not return a safe lyrics match for %r by %r", track, artist)
        return None
    selected = max(candidates, key=lambda record: _lrclib_match_score(record, metadata))
    LOGGER.info("Using LRCLIB record %s: %s", selected.get("id"), selected.get("trackName"))
    return selected


def _lrclib_request(path: str) -> Any:
    request = urllib.request.Request(
        f"{LRCLIB_API}{path}",
        headers={"User-Agent": "yt-video-generator/0.1.0 (LyricsFile preparation)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (json.JSONDecodeError, TimeoutError, urllib.error.URLError) as error:
        raise OSError(str(error)) from error


def _usable_lrclib_record(record: dict[str, Any]) -> bool:
    return not record.get("instrumental") and any(
        isinstance(record.get(key), str) and record[key].strip()
        for key in ("lyricsfile", "lyricsFile", "syncedLyrics", "plainLyrics")
    )


def _lrclib_match_score(record: dict[str, Any], metadata: dict[str, Any]) -> float:
    expected_title = str(metadata.get("track") or metadata["title"])
    title_score = SequenceMatcher(
        None, _match_text(expected_title), _match_text(str(record.get("trackName") or ""))
    ).ratio()
    artist = metadata.get("artist")
    artist_score = 0.5
    if artist:
        artist_score = SequenceMatcher(
            None, _match_text(str(artist)), _match_text(str(record.get("artistName") or ""))
        ).ratio()
    duration_score = 0.0
    if metadata.get("duration") and record.get("duration"):
        difference = abs(float(metadata["duration"]) - float(record["duration"]))
        duration_score = 1.0 if difference <= 2 else 0.5 if difference <= 5 else 0.0
    return title_score + artist_score + duration_score


def _match_text(value: str) -> str:
    normalized = "".join(character if character.isalnum() else " " for character in value.casefold())
    return " ".join(normalized.split())


def _lyrics_document_from_record(
    record: dict[str, Any], metadata: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    import yaml

    raw_lyrics_file = record.get("lyricsfile") or record.get("lyricsFile")
    if isinstance(raw_lyrics_file, str) and raw_lyrics_file.strip():
        try:
            document = yaml.safe_load(raw_lyrics_file)
        except yaml.YAMLError as error:
            raise ValueError(f"LRCLIB returned invalid LyricsFile YAML: {error}") from error
        if isinstance(document, dict):
            document.setdefault("version", "1.0")
            if not isinstance(document.get("metadata"), dict):
                document["metadata"] = {}
            document["metadata"].setdefault("title", record.get("trackName") or metadata["title"])
            document["metadata"].setdefault("duration_ms", round(float(metadata["duration"]) * 1000))
            language = config["language"] if config["language"] != "auto" else metadata.get("language")
            if language:
                document["metadata"].setdefault("language", language)
            raw_lines = document.get("lines")
            has_text_lines = (
                isinstance(raw_lines, list) and raw_lines and any(
                    isinstance(line, dict) and str(line.get("text") or "").strip() for line in raw_lines
                )
            )
            if has_text_lines:
                return document
            LOGGER.info("LRCLIB lyricsfile has no usable lines, trying syncedLyrics/plainLyrics")

    source = record.get("syncedLyrics") or record.get("plainLyrics")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("LRCLIB record does not contain usable lyrics")
    lines = []
    for raw_line in source.splitlines():
        text = re.sub(r"^\[\d{1,3}:\d{2}(?:\.\d{2,3})?\]\s*", "", raw_line).strip()
        if text:
            lines.append({"text": text})
    if not lines:
        raise ValueError("LRCLIB record does not contain non-empty lyric lines")
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


def _has_complete_word_timings(document: dict[str, Any]) -> bool:
    lines = document.get("lines")
    if not isinstance(lines, list):
        return False
    lyric_lines = [line for line in lines if isinstance(line, dict) and str(line.get("text") or "").strip()]
    return bool(lyric_lines) and all(isinstance(line.get("words"), list) and line["words"] for line in lyric_lines)


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
    line_tokens = []
    for line in raw_lines:
        if not isinstance(line, dict) or not isinstance(line.get("text"), str):
            continue
        tokens = (
            [character for character in line["text"] if not character.isspace()]
            if character_alignment
            else line["text"].split()
        )
        if tokens:
            line_tokens.append(tokens)
    flat_tokens = [token for tokens in line_tokens for token in tokens]
    if not flat_tokens:
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
    alignment_text = "".join(flat_tokens) if character_alignment else " ".join(flat_tokens)
    tokens_starred, text_starred = preprocess_text(
        alignment_text,
        romanize=True,
        language=language,
        split_size="char" if character_alignment else "word",
        star_frequency="edges",
    )
    segments, scores, blank_token = get_alignments(emissions, tokens_starred, tokenizer)
    spans = get_spans(tokens_starred, segments, blank_token)
    aligned = postprocess_results(text_starred, spans, stride, scores)
    if len(aligned) != len(flat_tokens):
        raise ValueError(f"CTC aligned {len(aligned)} words but expected {len(flat_tokens)}")

    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    output_lines = []
    cursor = 0
    for tokens in line_tokens:
        aligned_line = aligned[cursor : cursor + len(tokens)]
        words = []
        for index, (token, timing) in enumerate(zip(tokens, aligned_line, strict=True)):
            confidence = max(0.0, min(1.0, math.exp(float(timing["score"]))))
            words.append(
                {
                    "text": token if character_alignment or index + 1 == len(tokens) else f"{token} ",
                    "start_ms": round(float(timing["start"]) * 1000),
                    "end_ms": round(float(timing["end"]) * 1000),
                    "confidence": round(confidence, 4),
                }
            )
        output_lines.append(
            {
                "text": "".join(tokens) if character_alignment else " ".join(tokens),
                "words": words,
                "start_ms": words[0]["start_ms"],
                "end_ms": words[-1]["end_ms"],
            }
        )
        cursor += len(tokens)
    lyrics = {"version": "1.0", "metadata": metadata, "lines": output_lines}
    return _load_lyrics_module().validate_lyrics_file(lyrics, require_words=True), aligned


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
        source_words = segment["words"]
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
    return _load_lyrics_module().validate_lyrics_file(
        {"version": "1.0", "metadata": metadata, "lines": lines}, require_words=True
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
