import json
import os
import uuid
from pathlib import Path
from typing import Any

EDIT_SCHEMA_VERSION = 2
TRANSCRIPT_SCHEMA_VERSION = 2


class RevisionConflictError(ValueError):
    """Raised when an explicit save uses a stale revision."""


def load_edit_document(job_dir: Path) -> dict[str, Any]:
    """Load and validate a job's canonical edit document."""
    path = job_dir.expanduser().resolve() / "edit.json"
    if not path.is_file():
        raise FileNotFoundError(f"Missing canonical edit document: {path}")
    try:
        return validate_edit_document(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid edit.json: {error}") from error


def save_edit_document(job_dir: Path, document: dict[str, Any]) -> dict[str, Any]:
    """Validate and atomically save canonical edit state."""
    validated = validate_edit_document(document)
    _atomic_write_json(job_dir.expanduser().resolve() / "edit.json", validated)
    return validated


def save_edit_document_revision(job_dir: Path, document: dict[str, Any]) -> dict[str, Any]:
    """Save an edit only when its revision matches the canonical document."""
    current = load_edit_document(job_dir)
    revision = document.get("revision")
    if revision != current["revision"]:
        raise RevisionConflictError("edit.json changed since it was loaded")
    candidate = {**document, "revision": current["revision"] + 1}
    return save_edit_document(job_dir, candidate)


def validate_edit_document(document: Any) -> dict[str, Any]:
    """Validate the minimal durable edit contract."""
    if not isinstance(document, dict) or document.get("schema_version") not in {1, EDIT_SCHEMA_VERSION}:
        raise ValueError(f"edit.json schema_version must be 1 or {EDIT_SCHEMA_VERSION}")
    revision = document.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("edit.json revision must be a positive integer")
    transcript = _validate_transcript(document.get("transcript"))
    media = document.get("media")
    video = document.get("video")
    background = document.get("background")
    if background is None and document.get("schema_version") == 1:
        render = document.get("render")
        if isinstance(render, dict):
            background = render.get("background")
    if not isinstance(media, dict) or not isinstance(video, dict) or not isinstance(background, dict):
        raise ValueError("edit.json media, video, and background must be objects")
    normalized_media = {
        key: _relative_path(media.get(key), f"media.{key}")
        for key in ("original_audio", "instrumental_audio", "original_transcript")
    }
    normalized_video = {}
    for key in ("width", "height", "fps"):
        value = video.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"video.{key} must be a positive integer")
        normalized_video[key] = value
    kind = background.get("kind")
    if kind not in {"solid", "image"}:
        raise ValueError("background.kind must be solid or image")
    color = background.get("color")
    if not isinstance(color, str) or len(color.lstrip("#")) != 6:
        raise ValueError("background.color must use #RRGGBB")
    normalized_background: dict[str, Any] = {"kind": kind, "color": f"#{color.lstrip('#').upper()}"}
    if kind == "image":
        normalized_background["path"] = _relative_path(background.get("path"), "background.path")
    return {
        "schema_version": EDIT_SCHEMA_VERSION,
        "revision": revision,
        "transcript": transcript,
        "media": normalized_media,
        "video": normalized_video,
        "background": normalized_background,
    }


def resolve_job_asset(job_dir: Path, relative_path: str, label: str) -> Path:
    """Resolve a required asset without allowing traversal outside the job."""
    root = job_dir.expanduser().resolve()
    resolved = (root / _relative_path(relative_path, label)).resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise FileNotFoundError(f"Missing {label}: {resolved}")
    return resolved


def resolve_original_audio(job_dir: Path) -> tuple[str, Path]:
    """Resolve the canonical browser audio for a prepared job."""
    document = load_edit_document(job_dir)
    relative_path = document["media"]["original_audio"]
    return relative_path, resolve_job_asset(job_dir, relative_path, "original audio")


def _validate_transcript(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") not in {1, TRANSCRIPT_SCHEMA_VERSION}:
        raise ValueError("Canonical transcript schema_version must be 1 or 2")
    song = value.get("song")
    segments = value.get("segments")
    if not isinstance(song, dict) or not isinstance(song.get("title"), str) or not song["title"].strip():
        raise ValueError("Transcript song.title is required")
    if not isinstance(segments, list) or not segments:
        raise ValueError("Transcript must contain at least one segment")
    normalized_segments = []
    seen_ids: set[str] = set()
    for segment_index, segment in enumerate(segments):
        if not isinstance(segment, dict) or not isinstance(segment.get("words"), list) or not segment["words"]:
            raise ValueError(f"Segment {segment_index + 1} must contain words")
        segment_id = str(segment.get("id") or f"s{segment_index}")
        words = []
        for word_index, word in enumerate(segment["words"]):
            if not isinstance(word, dict):
                raise ValueError(f"Word {word_index + 1} in {segment_id} must be an object")
            word_id = str(word.get("id") or f"{segment_id}-w{word_index}")
            if word_id in seen_ids:
                raise ValueError(f"Duplicate word id: {word_id}")
            seen_ids.add(word_id)
            start = _number(word.get("start"), f"Word {word_id} start")
            end = _number(word.get("end"), f"Word {word_id} end")
            text = word.get("text")
            if start < 0 or end <= start or not isinstance(text, str) or not text:
                raise ValueError(f"Word {word_id} must have text and a positive duration")
            normalized_word: dict[str, Any] = {
                "id": word_id,
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
            }
            if isinstance(word.get("probability"), int | float) and not isinstance(word["probability"], bool):
                normalized_word["probability"] = float(word["probability"])
            if "timing" in word:
                normalized_word["timing"] = _validate_timing(word_id, text, start, end, word["timing"])
            words.append(normalized_word)
        normalized_segments.append(
            {
                "id": segment_id,
                "start": min(word["start"] for word in words),
                "end": max(word["end"] for word in words),
                "text": " ".join(word["text"] for word in words),
                "words": words,
            }
        )
    normalized = {
        "schema_version": TRANSCRIPT_SCHEMA_VERSION,
        "song": song,
        "segments": normalized_segments,
    }
    if isinstance(value.get("transcription"), dict):
        normalized["transcription"] = value["transcription"]
    return normalized


def _validate_timing(word_id: str, text: str, start: float, end: float, value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"Word {word_id} timing must be a non-empty array")
    fragments = []
    for index, fragment in enumerate(value):
        if not isinstance(fragment, dict) or not isinstance(fragment.get("text"), str) or not fragment["text"]:
            raise ValueError(f"Word {word_id} timing fragment {index + 1} must contain text")
        fragment_start = _number(fragment.get("start"), "Fragment start")
        fragment_end = _number(fragment.get("end"), "Fragment end")
        if fragment_end <= fragment_start:
            raise ValueError(f"Word {word_id} timing fragments must have positive durations")
        if fragments and abs(fragment_start - fragments[-1]["end"]) > 0.001:
            raise ValueError(f"Word {word_id} timing fragments must be contiguous")
        fragments.append(
            {
                "id": str(fragment.get("id") or f"{word_id}-f{index}"),
                "text": fragment["text"],
                "start": round(fragment_start, 3),
                "end": round(fragment_end, 3),
            }
        )
    if "".join(fragment["text"] for fragment in fragments) != text:
        raise ValueError(f"Word {word_id} timing text must concatenate to word text")
    if abs(fragments[0]["start"] - start) > 0.001 or abs(fragments[-1]["end"] - end) > 0.001:
        raise ValueError(f"Word {word_id} timing must match word bounds")
    return fragments


def _number(value: Any, label: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    number = float(value)
    if not float("-inf") < number < float("inf"):
        raise ValueError(f"{label} must be finite")
    return number


def _relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a relative job path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be a relative job path")
    return path.as_posix()


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
