import os
import uuid
from pathlib import Path
from typing import Any

import yaml

LYRICS_FILENAME = "lyrics.lyricsfile.yaml"


class _IndentedSafeDumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> Any:
        return super().increase_indent(flow, indentless=False)


def load_lyrics_file(path: Path, *, require_words: bool = True) -> dict[str, Any]:
    """Load and validate a LyricsFile YAML document."""
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid LyricsFile YAML: {error}") from error
    return validate_lyrics_file(value, require_words=require_words)


def validate_lyrics_file(value: Any, *, require_words: bool = True) -> dict[str, Any]:
    """Normalize the LyricsFile subset used by the karaoke pipeline."""
    if not isinstance(value, dict) or str(value.get("version")) != "1.0":
        raise ValueError('LyricsFile version must be "1.0"')

    metadata = value.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("LyricsFile metadata must be an object")
    title = metadata.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("LyricsFile metadata.title is required")

    duration_ms = _optional_milliseconds(metadata.get("duration_ms"), "metadata.duration_ms")
    unspaced_language = _uses_unspaced_words(metadata.get("language"))
    raw_lines = value.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise ValueError("LyricsFile must contain lines")

    line_bounds = _resolve_line_bounds(raw_lines, duration_ms)
    lines = []
    previous_end = 0
    for line_index, (raw_line, (start_ms, end_ms)) in enumerate(zip(raw_lines, line_bounds, strict=True), start=1):
        if not isinstance(raw_line, dict):
            raise ValueError(f"LyricsFile line {line_index} must be an object")
        text = raw_line.get("text")
        if not isinstance(text, str):
            raise ValueError(f"LyricsFile line {line_index} text must be a string")
        if start_ms < previous_end and text.strip():
            raise ValueError(f"LyricsFile line {line_index} overlaps the previous lyric line")

        words = _normalize_words(raw_line.get("words"), line_index, start_ms, end_ms)
        if require_words and text.strip() and not words:
            raise ValueError(f"LyricsFile line {line_index} must contain word timings")
        joined_text = "".join(word["text"] for word in words)
        if words and _comparable_text(joined_text, unspaced_language) != _comparable_text(text, unspaced_language):
            raise ValueError(f"LyricsFile line {line_index} words do not reconstruct its text")

        normalized_line: dict[str, Any] = {"text": text, "start_ms": start_ms, "end_ms": end_ms}
        if words:
            normalized_line["words"] = words
        lines.append(normalized_line)
        if text.strip():
            previous_end = end_ms

    normalized_metadata = {"title": title.strip()}
    for key in ("artist", "album", "language", "by"):
        item = metadata.get(key)
        if isinstance(item, str) and item.strip():
            normalized_metadata[key] = item.strip()
    if duration_ms is not None:
        normalized_metadata["duration_ms"] = duration_ms

    return {
        "version": "1.0",
        "metadata": normalized_metadata,
        "lines": lines,
        "plain": "\n".join(line["text"] for line in lines),
    }


def dump_lyrics_file(value: Any, *, require_words: bool = True) -> str:
    """Serialize a normalized LyricsFile document."""
    document = validate_lyrics_file(value, require_words=require_words)
    return yaml.dump(document, Dumper=_IndentedSafeDumper, allow_unicode=True, sort_keys=False, width=120)


def write_lyrics_file(path: Path, value: Any, *, require_words: bool = True) -> None:
    """Atomically write a validated LyricsFile document."""
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as file:
            file.write(dump_lyrics_file(value, require_words=require_words))
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def lyrics_to_transcript(value: Any) -> dict[str, Any]:
    """Adapt validated word-timed lyrics to the existing ASS renderer contract."""
    document = validate_lyrics_file(value, require_words=True)
    unspaced_language = _uses_unspaced_words(document["metadata"].get("language"))
    segments = []
    for line_index, line in enumerate(document["lines"]):
        if not line["text"].strip():
            continue
        words = []
        for word_index, word in enumerate(line["words"]):
            text = "".join(word["text"].split()) if unspaced_language else word["text"]
            normalized_word = {
                "id": f"s{line_index}-w{word_index}",
                "start": word["start_ms"] / 1000,
                "end": word["end_ms"] / 1000,
                "text": text,
            }
            if "confidence" in word:
                normalized_word["probability"] = word["confidence"]
            words.append(normalized_word)
        segments.append(
            {
                "id": f"s{line_index}",
                "start": line["start_ms"] / 1000,
                "end": line["end_ms"] / 1000,
                "text": "".join(line["text"].split()) if unspaced_language else line["text"].strip(),
                "words": words,
            }
        )
    if not segments:
        raise ValueError("LyricsFile does not contain renderable lyric lines")
    return {"schema_version": 2, "song": document["metadata"], "segments": segments}


def _resolve_line_bounds(lines: list[Any], duration_ms: int | None) -> list[tuple[int, int]]:
    starts = []
    for line_index, line in enumerate(lines, start=1):
        if not isinstance(line, dict):
            raise ValueError(f"LyricsFile line {line_index} must be an object")
        starts.append(_milliseconds(line.get("start_ms"), f"line {line_index} start_ms"))

    bounds = []
    for index, line in enumerate(lines):
        end_ms = _optional_milliseconds(line.get("end_ms"), f"line {index + 1} end_ms")
        if end_ms is None:
            end_ms = starts[index + 1] if index + 1 < len(starts) else duration_ms
        if end_ms is None or end_ms <= starts[index]:
            raise ValueError(f"LyricsFile line {index + 1} must have a positive duration")
        bounds.append((starts[index], end_ms))
    return bounds


def _normalize_words(value: Any, line_index: int, line_start: int, line_end: int) -> list[dict[str, Any]]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise ValueError(f"LyricsFile line {line_index} words must be an array")

    starts = []
    for word_index, word in enumerate(value, start=1):
        if not isinstance(word, dict):
            raise ValueError(f"LyricsFile line {line_index} word {word_index} must be an object")
        starts.append(_milliseconds(word.get("start_ms"), f"line {line_index} word {word_index} start_ms"))

    words = []
    previous_end = line_start
    for index, word in enumerate(value):
        text = word.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        start_ms = starts[index]
        end_ms = _optional_milliseconds(word.get("end_ms"), f"line {line_index} word {index + 1} end_ms")
        if end_ms is None:
            end_ms = starts[index + 1] if index + 1 < len(starts) else line_end
        if start_ms < line_start or end_ms > line_end or end_ms <= start_ms:
            raise ValueError(f"LyricsFile line {line_index} word {index + 1} is outside its line bounds")
        if start_ms < previous_end:
            raise ValueError(f"LyricsFile line {line_index} word {index + 1} overlaps the previous word")
        normalized_word: dict[str, Any] = {"text": text, "start_ms": start_ms, "end_ms": end_ms}
        confidence = word.get("confidence", word.get("score"))
        if confidence is not None:
            if not isinstance(confidence, int | float) or isinstance(confidence, bool):
                raise ValueError(f"LyricsFile line {line_index} word {index + 1} confidence must be numeric")
            confidence = float(confidence)
            if not 0 <= confidence <= 1:
                raise ValueError(f"LyricsFile line {line_index} word {index + 1} confidence must be between 0 and 1")
            normalized_word["confidence"] = round(confidence, 4)
        words.append(normalized_word)
        previous_end = end_ms
    return words


def _milliseconds(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _optional_milliseconds(value: Any, label: str) -> int | None:
    if value is None:
        return None
    return _milliseconds(value, label)


def _uses_unspaced_words(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return value.split("-", maxsplit=1)[0].lower() in {"chi", "ja", "jpn", "zh"}


def _comparable_text(value: str, unspaced_language: bool) -> str:
    return "".join(value.split()) if unspaced_language else value.strip()
