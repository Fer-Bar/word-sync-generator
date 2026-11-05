import re
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

try:
    from karaoke_app.lyric_references import sanitize_text
except ModuleNotFoundError as error:
    if error.name != "karaoke_app":
        raise
    # Colab receives these services as standalone files, without the local package.
    from karaoke_lyric_references import sanitize_text

LYRICS_FILENAME = "lyrics.lyricsfile.yaml"


class _IndentedSafeDumper(yaml.SafeDumper):
    def represent_str(self, value: str) -> Any:
        style = "|" if "\n" in value else '"' if "'" in value else None
        return self.represent_scalar("tag:yaml.org,2002:str", value, style=style)

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> Any:
        return super().increase_indent(flow, indentless=False)


_IndentedSafeDumper.add_representer(str, _IndentedSafeDumper.represent_str)


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
    previous_end_by_channel: dict[tuple[str, bool], int] = {}
    for line_index, (raw_line, (start_ms, end_ms)) in enumerate(zip(raw_lines, line_bounds, strict=True), start=1):
        if not isinstance(raw_line, dict):
            raise ValueError(f"LyricsFile line {line_index} must be an object")
        text = raw_line.get("text")
        if not isinstance(text, str):
            raise ValueError(f"LyricsFile line {line_index} text must be a string")
        text = sanitize_text(text)

        line_agent = _optional_agent(raw_line.get("agent"), f"LyricsFile line {line_index} agent")
        line_is_background = _optional_background(
            raw_line.get("isBackground"), f"LyricsFile line {line_index} isBackground"
        )
        words = _normalize_words(
            raw_line.get("words"),
            line_index,
            start_ms,
            end_ms,
            line_agent=line_agent,
            line_is_background=line_is_background is True,
        )
        if require_words and text.strip() and not words:
            raise ValueError(f"LyricsFile line {line_index} must contain word timings")
        joined_text = "".join(word["text"] for word in words)
        channels = {_word_channel(word, line_agent, line_is_background is True) for word in words}
        is_multitrack = len(channels) > 1 or any(channel[1] for channel in channels)
        reconstructs_text = (
            _multitrack_word_parts(words, unspaced_language) == _multitrack_text_parts(text, unspaced_language)
            if is_multitrack
            else _comparable_text(joined_text, unspaced_language) == _comparable_text(text, unspaced_language)
        )
        if words and not reconstructs_text:
            raise ValueError(f"LyricsFile line {line_index} words do not reconstruct its text")

        normalized_line: dict[str, Any] = {"text": text, "start_ms": start_ms, "end_ms": end_ms}
        if words:
            normalized_line["words"] = words
        if line_agent is not None:
            normalized_line["agent"] = line_agent
        if line_is_background is not None:
            normalized_line["isBackground"] = line_is_background

        for channel, (channel_start, channel_end) in _line_channel_bounds(normalized_line).items():
            if channel_start < previous_end_by_channel.get(channel, 0) and text.strip():
                raise ValueError(f"LyricsFile line {line_index} overlaps the previous lyric line in the same channel")
            if text.strip():
                previous_end_by_channel[channel] = channel_end
        lines.append(normalized_line)

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
            agent = word.get("agent", line.get("agent"))
            if agent is not None:
                normalized_word["agent"] = agent
            if word.get("isBackground", False) or line.get("isBackground", False):
                normalized_word["isBackground"] = True
            words.append(normalized_word)
        segment = {
            "id": f"s{line_index}",
            "start": line["start_ms"] / 1000,
            "end": line["end_ms"] / 1000,
            "text": "".join(line["text"].split()) if unspaced_language else line["text"].strip(),
            "words": words,
        }
        if "agent" in line:
            segment["agent"] = line["agent"]
        if line.get("isBackground"):
            segment["isBackground"] = True
        segments.append(segment)
    if not segments:
        raise ValueError("LyricsFile does not contain renderable lyric lines")
    return {"schema_version": 2, "song": document["metadata"], "segments": segments}


def sanitize_lyrics_lines(
    lines: list[dict[str, Any]],
    *,
    min_word_duration_ms: int = 20,
    min_line_duration_ms: int = 20,
) -> list[dict[str, Any]]:
    """Repair invalid model timings without collapsing gaps or independent vocal channels."""
    sanitized_lines: list[dict[str, Any]] = []
    previous_word_by_channel: dict[tuple[str, bool], dict[str, Any]] = {}

    for line in lines:
        if not isinstance(line, dict):
            continue
        text = line.get("text", "")
        raw_words = line.get("words")
        line_agent = line.get("agent") if isinstance(line.get("agent"), str) and line["agent"].strip() else None
        line_is_background = line.get("isBackground") is True

        if isinstance(raw_words, list) and raw_words:
            sanitized_words: list[dict[str, Any]] = []
            for word in raw_words:
                if not isinstance(word, dict):
                    continue
                word_text = word.get("text", "")
                if not isinstance(word_text, str) or not word_text.strip():
                    continue
                word_text = sanitize_text(word_text)

                raw_start = word.get("start_ms", 0)
                raw_end = word.get("end_ms")
                start_ms = max(0, int(raw_start) if isinstance(raw_start, int | float) else 0)
                if isinstance(raw_end, int | float):
                    end_ms = max(start_ms + min_word_duration_ms, int(raw_end))
                else:
                    end_ms = start_ms + min_word_duration_ms

                word_agent = word.get("agent") if isinstance(word.get("agent"), str) and word["agent"].strip() else None
                word_is_background = word.get("isBackground") is True
                channel = (word_agent or line_agent or "", word_is_background or line_is_background)
                prev_word = previous_word_by_channel.get(channel)
                if prev_word is not None:
                    prev_end = prev_word["end_ms"]
                    if start_ms < prev_end:
                        if start_ms >= prev_word["start_ms"] + min_word_duration_ms:
                            prev_word["end_ms"] = start_ms
                        else:
                            start_ms = prev_end
                            end_ms = max(end_ms, start_ms + min_word_duration_ms)

                new_word: dict[str, Any] = {"text": word_text, "start_ms": start_ms, "end_ms": end_ms}
                for extra in ("confidence", "score"):
                    if extra in word and isinstance(word[extra], int | float):
                        new_word["confidence"] = round(float(word[extra]), 4)
                        break
                if word_agent is not None:
                    new_word["agent"] = word_agent
                if "isBackground" in word and isinstance(word["isBackground"], bool):
                    new_word["isBackground"] = word["isBackground"]
                sanitized_words.append(new_word)
                previous_word_by_channel[channel] = new_word

            if sanitized_words:
                word_start = min(word["start_ms"] for word in sanitized_words)
                word_end = max(word["end_ms"] for word in sanitized_words)
                sanitized_line = {
                    "text": text,
                    "words": sanitized_words,
                    "start_ms": word_start,
                    "end_ms": word_end,
                }
                if line_agent is not None:
                    sanitized_line["agent"] = line_agent
                if "isBackground" in line and isinstance(line["isBackground"], bool):
                    sanitized_line["isBackground"] = line["isBackground"]
                sanitized_lines.append(sanitized_line)
            else:
                raw_start = line.get("start_ms", 0)
                raw_end = line.get("end_ms")
                start_ms = max(0, int(raw_start) if isinstance(raw_start, int | float) else 0)
                end_ms = (
                    max(start_ms + min_line_duration_ms, int(raw_end))
                    if isinstance(raw_end, int | float)
                    else start_ms + min_line_duration_ms
                )
                sanitized_lines.append(_sanitized_line_without_words(line, text, start_ms, end_ms))
        else:
            raw_start = line.get("start_ms", 0)
            raw_end = line.get("end_ms")
            start_ms = max(0, int(raw_start) if isinstance(raw_start, int | float) else 0)
            end_ms = (
                max(start_ms + min_line_duration_ms, int(raw_end))
                if isinstance(raw_end, int | float)
                else start_ms + min_line_duration_ms
            )
            sanitized_lines.append(_sanitized_line_without_words(line, text, start_ms, end_ms))

    for line in sanitized_lines:
        words = line.get("words", [])
        if words:
            line["start_ms"] = min(word["start_ms"] for word in words)
            line["end_ms"] = max(word["end_ms"] for word in words)

    return sanitized_lines


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


def _normalize_words(
    value: Any,
    line_index: int,
    line_start: int,
    line_end: int,
    *,
    line_agent: str | None,
    line_is_background: bool,
) -> list[dict[str, Any]]:
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
    previous_end_by_channel: dict[tuple[str, bool], int] = {}
    for index, word in enumerate(value):
        text = word.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        text = sanitize_text(text)
        start_ms = starts[index]
        end_ms = _optional_milliseconds(word.get("end_ms"), f"line {line_index} word {index + 1} end_ms")
        if end_ms is None:
            end_ms = starts[index + 1] if index + 1 < len(starts) else line_end
        if end_ms <= start_ms:
            raise ValueError(f"LyricsFile line {line_index} word {index + 1} must have a positive duration")
        if start_ms < line_start or end_ms > line_end:
            raise ValueError(f"LyricsFile line {line_index} word {index + 1} is outside its line bounds")
        agent = _optional_agent(word.get("agent"), f"LyricsFile line {line_index} word {index + 1} agent")
        is_background = _optional_background(
            word.get("isBackground"), f"LyricsFile line {line_index} word {index + 1} isBackground"
        )
        channel = (agent or line_agent or "", is_background is True or line_is_background)
        if start_ms < previous_end_by_channel.get(channel, line_start):
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
        if agent is not None:
            normalized_word["agent"] = agent
        if is_background is not None:
            normalized_word["isBackground"] = is_background
        words.append(normalized_word)
        previous_end_by_channel[channel] = end_ms
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


def _optional_agent(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _optional_background(value: Any, label: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def _word_channel(word: dict[str, Any], line_agent: str | None, line_is_background: bool) -> tuple[str, bool]:
    return (
        str(word.get("agent") or line_agent or ""),
        bool(word.get("isBackground", False) or line_is_background),
    )


def _line_channel_bounds(line: dict[str, Any]) -> dict[tuple[str, bool], tuple[int, int]]:
    words = line.get("words")
    if not isinstance(words, list) or not words:
        channel = (str(line.get("agent") or ""), bool(line.get("isBackground", False)))
        return {channel: (line["start_ms"], line["end_ms"])}

    bounds: dict[tuple[str, bool], tuple[int, int]] = {}
    for word in words:
        channel = _word_channel(word, line.get("agent"), bool(line.get("isBackground", False)))
        previous = bounds.get(channel)
        if previous is None:
            bounds[channel] = (word["start_ms"], word["end_ms"])
        else:
            bounds[channel] = (min(previous[0], word["start_ms"]), max(previous[1], word["end_ms"]))
    return bounds


def _multitrack_text_parts(value: str, unspaced_language: bool) -> Counter[str]:
    without_grouping = value.replace("(", " ").replace(")", " ")
    if unspaced_language:
        return Counter(character for character in without_grouping if not character.isspace())
    return Counter(re.findall(r"[\w]+(?:['’-][\w]+)*|[^\w\s()]", without_grouping, flags=re.UNICODE))


def _multitrack_word_parts(words: list[dict[str, Any]], unspaced_language: bool) -> Counter[str]:
    parts: Counter[str] = Counter()
    for word in words:
        parts.update(_multitrack_text_parts(word["text"], unspaced_language))
    return parts


def _sanitized_line_without_words(line: dict[str, Any], text: Any, start_ms: int, end_ms: int) -> dict[str, Any]:
    sanitized_line = {"text": text, "start_ms": start_ms, "end_ms": end_ms}
    agent = line.get("agent")
    if isinstance(agent, str) and agent.strip():
        sanitized_line["agent"] = agent.strip()
    if "isBackground" in line and isinstance(line["isBackground"], bool):
        sanitized_line["isBackground"] = line["isBackground"]
    return sanitized_line


def format_srt_timestamp(seconds: float) -> str:
    """Format seconds into SRT timestamp string (HH:MM:SS,mmm)."""
    total_ms = max(0, round(float(seconds) * 1000))
    ms = total_ms % 1000
    total_seconds = total_ms // 1000
    s = total_seconds % 60
    total_minutes = total_seconds // 60
    m = total_minutes % 60
    h = total_minutes // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def generate_srt(transcript_or_lyrics: dict[str, Any]) -> str:
    """Generate SubRip (.srt) subtitles from a canonical transcript or LyricsFile dictionary.

    YouTube and standard video players require sequential cues with timestamps in
    HH:MM:SS,mmm format. Background vocals are rendered inside parentheses.
    """
    if "lines" in transcript_or_lyrics and "segments" not in transcript_or_lyrics:
        segments = []
        for line in transcript_or_lyrics.get("lines", []):
            text = str(line.get("text", "")).strip()
            if not text:
                continue
            start = line.get("start_ms", 0) / 1000.0
            end = line.get("end_ms", line.get("start_ms", 0) + 500) / 1000.0
            segments.append(
                {
                    "start": start,
                    "end": end,
                    "text": text,
                    "isBackground": bool(line.get("isBackground", False)),
                }
            )
    else:
        segments = transcript_or_lyrics.get("segments", [])

    srt_entries: list[str] = []
    counter = 1
    for segment in segments:
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", start + 0.5))
        if end <= start:
            end = start + 0.5
        if segment.get("isBackground") and not (text.startswith("(") and text.endswith(")")):
            text = f"({text})"

        start_ts = format_srt_timestamp(start)
        end_ts = format_srt_timestamp(end)
        srt_entries.append(f"{counter}\n{start_ts} --> {end_ts}\n{text}")
        counter += 1

    if not srt_entries:
        return ""
    return "\n\n".join(srt_entries) + "\n"
