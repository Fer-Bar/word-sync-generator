"""Resolve lyric references and compare their structure with independent ASR evidence."""

import copy
import importlib.util
import json
import logging
import math
import os
import re
import unicodedata
from array import array
from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

LOGGER = logging.getLogger(__name__)


def timing_quality(document: dict[str, Any], *, require_words: bool = True) -> dict[str, Any]:
    """Check recording bounds and impossible timing density without treating metadata as acoustic proof."""
    duration = document.get("metadata", {}).get("duration_ms")
    issues, timed, untimed = [], 0, []
    if not isinstance(duration, int | float) or not math.isfinite(duration) or duration <= 0:
        issues.append({"reason": "missing_or_invalid_audio_duration"})
        duration = None
    previous = -1
    channel_starts = {}
    for index, line in enumerate(document.get("lines", [])):
        if not str(line.get("text") or "").strip():
            continue
        start, end = line.get("start_ms"), line.get("end_ms")
        if start is None and end is None and not require_words:
            untimed.append(index)
            continue
        timed += 1
        if not all(isinstance(t, int | float) and math.isfinite(t) for t in (start, end)):
            issues.append({"line_index": index, "reason": "missing_or_nonfinite_timing"})
            continue
        words = line.get("words") or []
        if start < 0 or end <= start or (duration and end > duration + 80) or (not words and start < previous):
            issues.append({"line_index": index, "reason": "invalid_line_bounds"})
        previous = start
        if require_words and not words:
            issues.append({"line_index": index, "reason": "missing_words"})
        if len(words) >= 3 and all("confidence" in word for word in words):
            confidence = sum(word["confidence"] for word in words) / len(words)
            if confidence < 0.05:
                issues.append({"line_index": index, "reason": "insufficient_acoustic_support",
                               "mean_confidence": round(confidence, 4)})
        short = 0
        channels = {}
        for word in words:
            lo, hi = word.get("start_ms"), word.get("end_ms")
            if not all(isinstance(t, int | float) and math.isfinite(t) for t in (lo, hi)):
                issues.append({"line_index": index, "reason": "missing_or_nonfinite_word_timing"})
                continue
            channel = (word.get("agent") or line.get("agent") or "",
                       bool(word.get("isBackground") or line.get("isBackground")))
            if lo < start or hi > end or hi <= lo or lo < channel_starts.get(channel, -1):
                issues.append({"line_index": index, "reason": "invalid_word_bounds"})
            if 0 < hi - lo < 20:
                issues.append({"line_index": index, "reason": "sub_frame_word"})
            channel_starts[channel] = lo
            channels.setdefault(channel, []).append((lo, hi))
            short += hi - lo < 40
        for spans in channels.values():
            if len(spans) >= 3 and max(hi for _, hi in spans) - min(lo for lo, _ in spans) < len(spans) * 50:
                issues.append({"line_index": index, "reason": "collapsed_line"})
        if short >= 3 and short / len(words) >= 0.3:
            issues.append({"line_index": index, "reason": "collapsed_words"})
    if timed and untimed:
        issues.extend({"line_index": index, "reason": "incomplete_line_timing"} for index in untimed)
    return {"status": "rejected" if issues else "checked" if timed else "unavailable",
            "issues": issues, "timed_lines": timed}


def normalized_units(text: str) -> list[str]:
    """Normalize only for comparison, retaining the original display text separately."""
    text = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    text = text.replace("'", "")
    return re.findall(r"[\u3400-\u9fff\u3040-\u30ff]|[^\W_\u3400-\u9fff\u3040-\u30ff]+", text)


CYRILLIC_HOMOGLYPHS: dict[str, str] = {
    "а": "a",
    "с": "c",
    "е": "e",
    "і": "i",
    "ј": "j",
    "о": "o",
    "р": "p",
    "ѕ": "s",
    "х": "x",
    "у": "y",
    "ԁ": "d",
    "ԛ": "q",
    "ԝ": "w",
    "А": "A",
    "В": "B",
    "С": "C",
    "Е": "E",
    "Н": "H",
    "І": "I",
    "Ј": "J",
    "К": "K",
    "М": "M",
    "О": "O",
    "Р": "P",
    "Ѕ": "S",
    "Т": "T",
    "Х": "X",
    "Ү": "Y",
}

GREEK_HOMOGLYPHS: dict[str, str] = {
    "ο": "o",
    "ν": "v",
    "Α": "A",
    "Β": "B",
    "Ε": "E",
    "Ζ": "Z",
    "Η": "H",
    "Ι": "I",
    "Κ": "K",
    "Μ": "M",
    "Ν": "N",
    "Ο": "O",
    "Ρ": "P",
    "Τ": "T",
    "Υ": "Y",
    "Χ": "X",
}

INVISIBLE_CHARS: frozenset[str] = frozenset(
    {
        "\u200b",
        "\u200c",
        "\u200d",
        "\ufeff",
        "\u200e",
        "\u200f",
        "\u2060",
        "\u00ad",
    }
)

SPACES_TRANSLATION: dict[int, str] = {
    0x00A0: " ",
    0x2000: " ",
    0x2001: " ",
    0x2002: " ",
    0x2003: " ",
    0x2004: " ",
    0x2005: " ",
    0x2006: " ",
    0x2007: " ",
    0x2008: " ",
    0x2009: " ",
    0x200A: " ",
    0x202F: " ",
    0x205F: " ",
}


def _is_latin(c: str) -> bool:
    code = ord(c)
    return (0x0041 <= code <= 0x005A) or (0x0061 <= code <= 0x007A) or (0x00C0 <= code <= 0x024F)


def _is_distinctive_cyrillic(c: str) -> bool:
    code = ord(c)
    return (0x0400 <= code <= 0x04FF or 0x0500 <= code <= 0x052F) and (c not in CYRILLIC_HOMOGLYPHS)


def _is_distinctive_greek(c: str) -> bool:
    code = ord(c)
    return (0x0370 <= code <= 0x03FF) and (c not in GREEK_HOMOGLYPHS)


def sanitize_text(text: str) -> str:
    """Sanitize invisible control characters, non-standard spaces, and cross-script homoglyphs."""
    if not text:
        return text
    for inv in INVISIBLE_CHARS:
        if inv in text:
            text = text.replace(inv, "")
    text = text.translate(SPACES_TRANSLATION)

    has_latin = any(_is_latin(c) for c in text)
    has_dist_cyrillic = any(_is_distinctive_cyrillic(c) for c in text)
    has_dist_greek = any(_is_distinctive_greek(c) for c in text)

    if has_latin and not has_dist_cyrillic:
        for cyr, lat in CYRILLIC_HOMOGLYPHS.items():
            if cyr in text:
                text = text.replace(cyr, lat)

    if has_latin and not has_dist_greek:
        for grk, lat in GREEK_HOMOGLYPHS.items():
            if grk in text:
                text = text.replace(grk, lat)

    def _clean_token(match: re.Match[str]) -> str:
        token = match.group(0)
        if any(_is_latin(c) for c in token):
            for cyr, lat in CYRILLIC_HOMOGLYPHS.items():
                token = token.replace(cyr, lat)
            for grk, lat in GREEK_HOMOGLYPHS.items():
                token = token.replace(grk, lat)
        return token

    return re.sub(r"\S+", _clean_token, text)


def plain_lines(text: str) -> list[dict[str, Any]]:
    """Read section performers without treating standalone, possibly wrapped headers as vocals."""
    cleaned = sanitize_text(text)
    header = re.compile(r"(?m)^[ \t]*\[([^\[\]]+)\][ \t]*(?=\n|$)")
    lines = []
    agent = None
    cursor = 0
    for match in header.finditer(cleaned):
        for line in cleaned[cursor:match.start()].splitlines():
            if line.strip():
                lines.append({"text": line.strip(), **({"agent": agent} if agent else {})})
        label = " ".join(match.group(1).split())
        section, separator, performer = label.partition(":")
        # Multiple names identify a shared section, not a diarization of individual words.
        agent = performer.strip() if separator and performer.strip() else None
        cursor = match.end()
    for line in cleaned[cursor:].splitlines():
        if line.strip():
            lines.append({"text": line.strip(), **({"agent": agent} if agent else {})})
    return lines


def _reference_agent(line: dict[str, Any], target: dict[str, Any]) -> None:
    agent = target.get("agent")
    if agent:
        line["agent"] = agent
        for word in line.get("words", []):
            if word.get("agent") in (None, "v1"):
                word["agent"] = agent


def reference_vocal_tokens(
    lines: list[dict[str, Any]], *, character_alignment: bool = False,
) -> list[list[dict[str, Any]]]:
    """Read parenthesized background spans across lines, retaining reference typography."""
    result = []
    depth = 0
    for line in lines:
        tokens = []
        source_tokens = (
            [character for character in line["text"] if not character.isspace()]
            if character_alignment else re.findall(r"\S+\s*", line["text"])
        )
        for text in source_tokens:
            background = bool(line.get("isBackground"))
            for character in text:
                if character == "(":
                    depth += 1
                elif character == ")":
                    depth -= 1
                    if depth < 0:
                        raise ValueError("Unbalanced background-vocal parentheses in reference")
                elif not character.isspace() and depth:
                    background = True
            tokens.append({"text": text, "isBackground": background})
        result.append(tokens)
    if depth:
        raise ValueError("Unbalanced background-vocal parentheses in reference")
    return result


def _reference_backgrounds(document: dict[str, Any], desired: list[dict[str, Any]]) -> None:
    try:
        tokenized = reference_vocal_tokens(desired)
    except ValueError:
        # Incomplete provider punctuation is not evidence that the remaining song is a chorus.
        return
    tokenized = [tokens for target, tokens in zip(desired, tokenized, strict=True) if normalized_units(target["text"])]
    for line, tokens in zip(document["lines"], tokenized, strict=True):
        units = [(unit, token["isBackground"]) for token in tokens for unit in normalized_units(token["text"])]
        words = line.get("words", [])
        observed = [unit for word in words for unit in normalized_units(word["text"])]
        if observed != [unit for unit, _ in units]:
            continue
        cursor = 0
        for word in words:
            count = len(normalized_units(word["text"]))
            if count and all(background for _, background in units[cursor:cursor + count]):
                word["isBackground"] = True
            cursor += count


def _reference_word_annotations(document: dict[str, Any], desired: list[dict[str, Any]]) -> None:
    """Transfer native vocal annotations onto matching acoustic words, never provider times or confidence."""
    for line, target in zip(document["lines"], desired, strict=True):
        sources = target.get("words")
        if not isinstance(sources, list):
            continue
        units = [(unit, word) for word in sources if isinstance(word, dict) and isinstance(word.get("text"), str)
                 for unit in normalized_units(word["text"])]
        observed = [unit for word in line.get("words", []) for unit in normalized_units(word["text"])]
        if observed != [unit for unit, _ in units]:
            continue
        if isinstance(target.get("isBackground"), bool):
            line["isBackground"] = target["isBackground"]
        cursor = 0
        for word in line.get("words", []):
            count = len(normalized_units(word["text"]))
            span = [source for _, source in units[cursor:cursor + count]]
            for key in ("agent", "isBackground"):
                values = [source.get(key, target.get(key)) for source in span]
                if values and values[0] is not None and all(value == values[0] for value in values):
                    word[key] = values[0]
            cursor += count


def validate_genius_url(url: str) -> str:
    """Accept only direct HTTPS song pages on Genius."""
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"genius.com", "www.genius.com"}
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
        or not parsed.path.endswith("-lyrics")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Genius URL must be an HTTPS genius.com song URL ending in -lyrics")
    return f"https://genius.com{parsed.path}"


def _genius_client() -> Any:
    from lyricsgenius import Genius, PublicAPI

    class PublicLyricsClient(PublicAPI):
        """Reuse LyricsGenius HTML parsing without constructing its authenticated API client."""

        remove_section_headers = False

        def lyrics(self, *, song_url: str, remove_section_headers: bool = False) -> str | None:
            return Genius.lyrics(self, song_url=song_url, remove_section_headers=remove_section_headers)

    token = os.environ.get("GENIUS_CLIENT_ACCESS_TOKEN") or os.environ.get("GENIUS_ACCESS_TOKEN")
    if token:
        return Genius(access_token=token, timeout=10, retries=1, sleep_time=0.2)
    return PublicLyricsClient(access_token="", timeout=10, retries=1, sleep_time=0.2)


def genius_reference(
    metadata: dict[str, Any],
    *,
    url: str | None,
    candidate_is_safe: Callable[..., bool],
    client_factory: Callable[[], Any] | None = None,
) -> dict[str, Any] | None:
    """Fetch a metadata-checked song, rejecting ambiguous automatic search results."""
    from lyricsgenius import PublicAPI

    track = metadata.get("track") or metadata.get("title") or ""
    artist = metadata.get("artist")
    if not track or not artist:
        LOGGER.debug("Genius search skipped: missing track or artist (track=%r artist=%r)", track, artist)
        return None
    if url:
        url = validate_genius_url(url)
    client = (client_factory or _genius_client)()
    # Public search is available without a developer token; lyrics still come from HTML.
    if getattr(client, "authorization_header", {}).get("authorization"):
        response = client.search_songs(f"{track} {artist}", per_page=10)
        sections = [{"hits": response.get("hits", [])}]
    else:
        response = PublicAPI.search_songs(client, f"{track} {artist}", per_page=10)
        sections = response.get("sections", [])
    LOGGER.debug("Genius search: track=%r artist=%r", track, artist)
    candidates = []
    seen_hits = 0
    for section in sections:
        for hit in section.get("hits", []):
            seen_hits += 1
            song = hit.get("result", {})
            candidate = {
                "trackName": song.get("title"),
                "artistName": (song.get("primary_artist") or {}).get("name"),
                "plainLyrics": "metadata check",
            }
            if not candidate_is_safe(candidate, track=track, artist=artist, duration=None):
                LOGGER.debug(
                    "Genius candidate rejected by metadata check: title=%r artist=%r id=%r",
                    candidate["trackName"], candidate["artistName"], song.get("id"),
                )
                continue
            song_url = song.get("url", "")
            if url and song_url.rstrip("/").replace("www.", "") != url.rstrip("/").replace("www.", ""):
                continue
            if song.get("id") not in {item.get("id") for item in candidates}:
                candidates.append(song)
    LOGGER.debug("Genius search returned %d hits; %d safe unique matches", seen_hits, len(candidates))
    if len(candidates) != 1:
        LOGGER.debug("Genius reference unavailable: expected one unambiguous match, got %d", len(candidates))
        return None
    song = candidates[0]
    song_url = validate_genius_url(song["url"])
    LOGGER.debug("Genius selected id=%s title=%r artist=%r url=%s", song.get("id"), song.get("title"),
                (song.get("primary_artist") or {}).get("name"), song_url)
    text = client.lyrics(song_url=song_url, remove_section_headers=False)
    if not text or not plain_lines(text):
        LOGGER.debug("Genius selected match returned no usable lyrics: id=%s", song.get("id"))
        return None
    LOGGER.debug("Genius lyrics retrieved: id=%s lines=%d", song.get("id"), len(plain_lines(text)))
    return {
        "source": "genius",
        "id": song.get("id"),
        "url": song_url,
        "original_text": text,
        "lines": plain_lines(text),
        "metadata": {"title": song["title"], "artist": song["primary_artist"]["name"]},
    }


def resolve_reference(
    options: dict[str, Any],
    metadata: dict[str, Any],
    record: dict[str, Any] | None,
    *,
    record_to_document: Callable[[], dict[str, Any]],
    candidate_is_safe: Callable[..., bool],
    fetch_genius: Callable[..., dict[str, Any] | None] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Resolve explicit TXT, LRCLIB, then Genius; keep failures and source evidence."""
    evidence: dict[str, Any] = {"attempts": []}
    if options.get("disable_lrclib"):
        LOGGER.debug("Lyric references disabled; using Whisper")
        evidence["source"] = "whisper"
        return None, evidence
    if options.get("text_path"):
        path = Path(options["text_path"])
        text = path.read_text(encoding="utf-8-sig")
        lines = plain_lines(text)
        if not lines:
            raise ValueError("Lyrics TXT contains no lyric lines")
        evidence.update(source="txt", filename=path.name, original_text=text, lines=lines)
        return {"version": "1.0", "metadata": dict(metadata), "lines": lines}, evidence
    if record:
        LOGGER.debug("Resolving LRCLIB record: id=%r track=%r artist=%r", record.get("id"),
                    record.get("trackName"), record.get("artistName"))
        evidence["lrclib_record"] = record
        try:
            document = record_to_document()
            evidence.update(source="lrclib", id=record.get("id"), lines=copy.deepcopy(document["lines"]))
            native_words = any(line.get("words") for line in document["lines"])
            if native_words:
                evidence["selected_variant"] = "lyricsfile_authoritative"
            text = record.get("plainLyrics")
            if isinstance(text, str) and plain_lines(text):
                evidence["original_text"] = text
                desired = plain_lines(text)
                current_units = normalized_units(" ".join(line["text"] for line in document["lines"]))
                desired_units = normalized_units(" ".join(line["text"] for line in desired))
                if current_units == desired_units and not native_words:
                    evidence["structure_lines"] = desired
                elif current_units != desired_units:
                    evidence["text_conflict"] = True
                    evidence["alternative_lines"] = desired
                    evidence["selected_variant"] = "lyricsfile_authoritative" if native_words else "plain_authoritative"
                    if not native_words:
                        document["lines"] = desired
                        evidence["lines"] = copy.deepcopy(desired)
            return document, evidence
        except (ValueError, KeyError, TypeError) as error:
            LOGGER.debug("LRCLIB record %r could not be converted to lyrics: %s", record.get("id"), error)
            evidence["attempts"].append({"source": "lrclib", "error": str(error)})
    if options.get("genius_reference_path"):
        try:
            reference = cached_genius_reference(
                Path(options["genius_reference_path"]), metadata,
                url=options.get("genius_url"), candidate_is_safe=candidate_is_safe,
            )
            evidence.update(reference)
            return {"version": "1.0", "metadata": dict(metadata), "lines": reference["lines"]}, evidence
        except (OSError, ValueError, KeyError, TypeError) as error:
            evidence["attempts"].append({"source": "genius", "acquisition": "local", "error": str(error)})
    try:
        reference = (fetch_genius or genius_reference)(
            metadata,
            url=options.get("genius_url"),
            candidate_is_safe=candidate_is_safe,
        )
        if reference:
            LOGGER.debug("Using Genius lyric reference: id=%r title=%r artist=%r", reference.get("id"),
                        (reference.get("metadata") or {}).get("title"), (reference.get("metadata") or {}).get("artist"))
            evidence.update(reference)
            return {"version": "1.0", "metadata": dict(metadata), "lines": reference["lines"]}, evidence
        evidence["attempts"].append({"source": "genius", "error": "no_unambiguous_metadata_match"})
    except Exception as error:
        # A provider failure must not discard the already acquired audio.
        evidence["attempts"].append({"source": "genius", "error": f"{type(error).__name__}: {error}"[:2000]})
    evidence["source"] = "whisper"
    LOGGER.debug("No usable LRCLIB or Genius reference; using Whisper")
    return None, evidence


def cached_genius_reference(
    path: Path, metadata: dict[str, Any], *, url: str | None, candidate_is_safe: Callable[..., bool],
) -> dict[str, Any]:
    """Validate a locally fetched text against actual source metadata before acoustic alignment."""
    cached = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cached, dict) or cached.get("source") != "genius":
        raise ValueError("Local reference must identify Genius as its provider")
    song = cached["metadata"]
    source_url = validate_genius_url(cached["url"])
    text = cached["original_text"]
    if not isinstance(text, str) or not plain_lines(text):
        raise ValueError("Local Genius reference has no lyric text")
    if url and source_url != validate_genius_url(url):
        raise ValueError("Local Genius reference does not match the requested URL")
    if not candidate_is_safe(
        {"trackName": song["title"], "artistName": song["artist"], "plainLyrics": text},
        track=metadata.get("track") or metadata.get("title"), artist=metadata.get("artist"), duration=None,
    ):
        raise ValueError("Local Genius reference does not match source metadata")
    # Only provider text is transported; cached word/line times must never enter inference.
    return {
        "source": "genius", "id": cached.get("id"), "url": source_url, "metadata": song,
        "original_text": text, "lines": plain_lines(text), "acquisition": "local_before_alignment",
    }


def prefetch_genius_reference(
    options: dict[str, Any], metadata: dict[str, Any], pipeline_path: Path,
) -> dict[str, Any] | None:
    """Fetch a local-network fallback before provisioning a GPU; keep LRCLIB priority remotely."""
    if (
        options.get("disable_lrclib") or options.get("text_path") or options.get("lrclib_id") is not None
        or not metadata.get("title") or not metadata.get("artist")
    ):
        return None
    try:
        spec = importlib.util.spec_from_file_location("karaoke_local_reference_matching", pipeline_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Cannot load reference metadata matching")
        pipeline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pipeline)
        return genius_reference(
            metadata, url=options.get("genius_url"), candidate_is_safe=pipeline._lrclib_candidate_is_safe,
        )
    except Exception as error:
        LOGGER.debug("Local Genius prefetch unavailable (%s); remote resolution remains enabled", type(error).__name__)
        return None


def _unambiguous_matches(expected: list[str], observed: list[str]) -> dict[int, int]:
    """Find mandatory, uniquely located matches across every optimal ordered alignment."""
    if expected == observed:
        return dict(enumerate(range(len(expected))))
    n, m = len(expected), len(observed)
    # Keep pathological inputs bounded; missing anchors are safer than greedy repeated-chorus matches.
    if n * m > 4_000_000:
        return {}
    prefix = [array("I", [0]) * (m + 1) for _ in range(n + 1)]
    suffix = [array("I", [0]) * (m + 1) for _ in range(n + 1)]
    for i in range(n):
        for j in range(m):
            prefix[i + 1][j + 1] = (
                prefix[i][j] + 1 if expected[i] == observed[j] else max(prefix[i][j + 1], prefix[i + 1][j])
            )
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            suffix[i][j] = (
                suffix[i + 1][j + 1] + 1 if expected[i] == observed[j] else max(suffix[i + 1][j], suffix[i][j + 1])
            )
    optimum = prefix[n][m]
    unique = {}
    for i in range(n):
        candidates = [
            j for j in range(m) if expected[i] == observed[j] and prefix[i][j] + 1 + suffix[i + 1][j + 1] == optimum
        ]
        can_skip = any(prefix[i][j] + suffix[i + 1][j] == optimum for j in range(m + 1))
        if len(candidates) == 1 and not can_skip:
            unique[i] = candidates[0]
    return unique


def compare_reference(lines: list[dict[str, Any]], transcript: dict[str, Any]) -> dict[str, Any]:
    """Compare ordered token sequences; only unambiguous complete lines provide ASR anchors."""
    words = [word for segment in transcript["segments"] for word in segment.get("words", [])]
    observed, owners = [], []
    for index, word in enumerate(words):
        units = normalized_units(word["text"])
        observed.extend(units)
        owners.extend([index] * len(units))
    line_units = [normalized_units(line["text"]) for line in lines]
    expected = [unit for units in line_units for unit in units]
    matcher = SequenceMatcher(None, expected, observed, autojunk=False)
    mapping: dict[int, int] = {}
    unique_matches = _unambiguous_matches(expected, observed)
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            mapping[block.a + offset] = block.b + offset
    reliable = {index for index, target in mapping.items() if unique_matches.get(index) == target}
    diagnostics = []
    cursor = 0
    for index, units in enumerate(line_units):
        indexes = list(range(cursor, cursor + len(units)))
        matched = [mapping[i] for i in indexes if i in mapping]
        contiguous = bool(matched) and matched == list(range(matched[0], matched[0] + len(units)))
        anchor_safe = bool(indexes) and all(i in reliable for i in indexes) and contiguous
        entry: dict[str, Any] = {
            "line_index": index,
            "text": lines[index]["text"],
            "matched_units": len(matched),
            "total_units": len(units),
            "missing_or_different": [expected[i] for i in indexes if i not in mapping],
            "needs_review": bool(units) and not anchor_safe,
            "differences": [
                {"operation": tag, "reference": expected[a:b], "asr": observed[c:d]}
                for tag, a, b, c, d in matcher.get_opcodes()
                if tag != "equal"
                and (
                    (a < cursor + len(units) and b > cursor)
                    or (a == b and cursor <= a < cursor + len(units))
                    or (index == len(lines) - 1 and a == b == len(expected))
                )
            ],
        }
        entry["needs_review"] |= bool(entry["differences"])
        spans, run = [], []
        for position in [*indexes, cursor + len(units)]:
            if (
                position == cursor + len(units) or position not in reliable
                or (run and mapping[position] != mapping[run[-1]] + 1)
            ):
                if len(run) >= 3 and _unique_phrase([expected[i] for i in run], expected):
                    selected = words[owners[mapping[run[0]]]:owners[mapping[run[-1]]] + 1]
                    if all(word.get("probability", 0) >= 0.5 and word["end"] > word["start"] for word in selected):
                        spans.append({
                            "start_unit": run[0] - cursor, "end_unit": run[-1] - cursor + 1,
                            "start_ms": round(selected[0]["start"] * 1000),
                            "end_ms": round(selected[-1]["end"] * 1000),
                        })
                run = []
            if position in reliable and position < cursor + len(units):
                run.append(position)
        entry["anchor_spans"] = spans
        if anchor_safe and len(units) >= 3 and _unique_phrase(units, expected):
            start_word, end_word = owners[matched[0]], owners[matched[-1]]
            selected = words[start_word : end_word + 1]
            if all(word.get("probability", 0) >= 0.5 and word["end"] > word["start"] for word in selected):
                entry["anchor"] = {
                    "start_ms": round(selected[0]["start"] * 1000),
                    "end_ms": round(selected[-1]["end"] * 1000),
                }
            else:
                entry["needs_review"] = True
        diagnostics.append(entry)
        cursor += len(units)
    matched_observed = set(mapping.values())
    return {
        "method": "ordered_sequence_comparison",
        "line_basis": "reference",
        "reference_coverage": len(mapping) / max(1, len(expected)),
        "asr_coverage": len(mapping) / max(1, len(observed)),
        "unmatched_asr": [unit for i, unit in enumerate(observed) if i not in matched_observed],
        "needs_review": any(line["needs_review"] for line in diagnostics) or len(mapping) != len(observed),
        "lines": diagnostics,
    }


def acoustic_word_anchors(tokens: list[dict[str, Any]], transcript: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Locate complete reference tokens inside mandatory, confident ASR phrases."""
    expected, token_units = [], []
    for token in tokens:
        units = normalized_units(token["text"])
        token_units.append(list(range(len(expected), len(expected) + len(units))))
        expected.extend(units)
    observed, owners = [], []
    words = [word for segment in transcript["segments"] for word in segment.get("words", [])]
    for index, word in enumerate(words):
        units = normalized_units(word["text"])
        observed.extend(units)
        owners.extend([index] * len(units))
    matches = _unambiguous_matches(expected, observed)
    supported, run = set(), []
    for index in range(len(expected) + 1):
        if index not in matches or (run and matches[index] != matches[run[-1]] + 1):
            if len(run) >= 3:
                supported.update(run)
            run = []
        if index in matches:
            run.append(index)
    anchors = {}
    for index, positions in enumerate(token_units):
        if not positions or not all(position in supported for position in positions):
            continue
        lo, hi = matches[positions[0]], matches[positions[-1]]
        if (lo and owners[lo - 1] == owners[lo]) or (hi + 1 < len(owners) and owners[hi + 1] == owners[hi]):
            continue
        selected = words[owners[lo]:owners[hi] + 1]
        if all(word.get("probability", 0) >= 0.5 and word["end"] > word["start"] for word in selected):
            anchors[index] = {"start_ms": round(selected[0]["start"] * 1000),
                              "end_ms": round(selected[-1]["end"] * 1000),
                              "confidence": min(word["probability"] for word in selected)}
    return anchors


def presence_windows(lines: list[dict], transcript: dict, duration_ms: int) -> list[dict]:
    """Locate poorly supported phrases between independent ASR anchors, ignoring provider times."""
    diagnostics = compare_reference(lines, transcript)["lines"]
    runs, current = [], []
    for index, diagnostic in enumerate(diagnostics):
        if diagnostic["total_units"] and diagnostic["matched_units"] / diagnostic["total_units"] < 0.5:
            current.append(index)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    windows = []
    for indexes in runs:
        # Isolated interjections cannot be distinguished reliably by lexical coverage alone.
        if sum(diagnostics[i]["total_units"] for i in indexes) < 2:
            continue
        before = [(span["end_ms"], i) for i, d in enumerate(diagnostics[:indexes[0]]) for span in d["anchor_spans"]]
        after = [(span["start_ms"], i) for i, d in enumerate(diagnostics)
                 if i > indexes[-1] for span in d["anchor_spans"]]
        lo, left = max(before, default=(0, -1))
        hi, right = min(after, default=(duration_ms, len(lines)))
        if not 0 <= lo < hi <= duration_ms:
            raise ValueError("Cannot locate unsupported reference phrases between ordered acoustic anchors")
        windows.append({"line_indexes": indexes, "context_line_indexes": list(range(left + 1, right)),
                        "start_ms": lo, "end_ms": hi})
    return windows


def _presence_coverage(lines: list[dict], words: list[dict]) -> list[float]:
    """Match occurrences once, allowing small ASR spelling errors in substantial words."""
    units = [normalized_units(line["text"]) for line in lines]
    expected = [unit for line in units for unit in line]
    observed = [unit for word in words for unit in normalized_units(word["text"])]
    substitutions = {
        (a, b): 0 if a == b else 1 if min(len(a), len(b)) >= 4
        and SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.65 else 4
        for a in set(expected) for b in set(observed)
    }
    n, m = len(expected), len(observed)
    costs = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n, -1, -1):
        for j in range(m, -1, -1):
            if i == n or j == m:
                costs[i][j] = 4 * (n - i + m - j)
            else:
                costs[i][j] = min(costs[i + 1][j] + 4, costs[i][j + 1] + 4,
                                  costs[i + 1][j + 1] + substitutions[expected[i], observed[j]])
    matched, i, j = set(), 0, 0
    # Traverse forwards so equally plausible repetitions consume the earliest occurrence first.
    while i < n and j < m:
        substitution = substitutions[expected[i], observed[j]]
        if costs[i][j] == costs[i + 1][j + 1] + substitution:
            if substitution < 4:
                matched.add(i)
            i, j = i + 1, j + 1
        elif costs[i][j] == costs[i + 1][j] + 4:
            i += 1
        else:
            j += 1
    coverage, cursor = [], 0
    for line in units:
        coverage.append(sum(i in matched for i in range(cursor, cursor + len(line))) / max(1, len(line)))
        cursor += len(line)
    return coverage


def resolve_recording_reference(
    lines: list[dict], transcript: dict, duration_ms: int, *, inspect_window: Callable,
) -> tuple[list[dict], dict]:
    """Exclude unsupported phrases after local retries; preserve the original reference as evidence."""
    omitted, decisions, checks = set(), [], []
    windows = presence_windows(lines, transcript, duration_ms)
    for window in windows:
        observations = inspect_window(window["start_ms"], window["end_ms"])
        if not observations or any(item.get("status") != "checked" for item in observations):
            raise RuntimeError("Local lyric presence verification unavailable; refusing to force unsupported text")
        checks.append({**window, "observations": observations})
        indexes = window["line_indexes"]
        context = window["context_line_indexes"]
        candidates = [lines[i] for i in context]
        coverage = []
        for observation in observations:
            # Context outside the gap must not confirm a repeated phrase in the gap.
            words = [w for w in observation["words"] if w.get("probability", 0) >= 0.5
                     and window["start_ms"] <= (w["start"] + w["end"]) * 500 < window["end_ms"]]
            coverage.append(_presence_coverage(candidates, words))
        for index in indexes:
            position = context.index(index)
            corroborating_sources = {item["source"] for item, values in zip(observations, coverage, strict=True)
                                     if values[position] >= 0.4}
            corroborated = len(corroborating_sources) >= 2
            supported = max(values[position] for values in coverage) >= 0.5 or corroborated
            if not supported:
                omitted.add(index)
            quiet = any(item["source"] == "vocals" and item.get("active_ratio", 1) < 0.02
                        for item in observations) and all(not item["words"] for item in observations)
            decisions.append({
                "line_index": index, "text": lines[index]["text"],
                "action": "keep" if supported else "omit",
                "reason": ("corroborated_partial_phrase" if corroborated else "recognized_on_retry")
                if supported else "no_vocal_evidence" if quiet else "unconfirmed",
                "start_ms": window["start_ms"], "end_ms": window["end_ms"],
                "coverage_by_source": {item["source"]: round(values[position], 4)
                                       for item, values in zip(observations, coverage, strict=True)},
            })
    selected = copy.deepcopy(lines)
    if omitted:
        # Parentheses can span removed lines. Close vocal-role spans within each surviving line.
        try:
            roles = reference_vocal_tokens(lines)
        except ValueError:
            roles = [[] for _ in lines]
        for index, line in enumerate(selected):
            if line["text"].count("(") != line["text"].count(")") and roles[index]:
                parts, background = [], False
                for token in roles[index]:
                    text = token["text"].replace("(", "").replace(")", "").strip()
                    if not text:
                        continue
                    if token["isBackground"] != background:
                        parts.append("(" if token["isBackground"] else ")")
                        background = token["isBackground"]
                    parts.append(text)
                if background:
                    parts.append(")")
                line["text"] = " ".join(parts).replace("( ", "(").replace(" )", ")")
    selected = [line for index, line in enumerate(selected) if index not in omitted]
    return selected, {
        "policy": "audio_supported_v1", "status": "adapted" if omitted else "checked",
        "original_lines": copy.deepcopy(lines), "selected_lines": copy.deepcopy(selected),
        "omitted_lines": len(omitted), "decisions": decisions, "windows": checks,
    }


def _unique_phrase(phrase: list[str], expected: list[str]) -> bool:
    """A repeated refrain is not an independent location anchor, even if one LCS prefers it."""
    return sum(expected[index:index + len(phrase)] == phrase
               for index in range(len(expected) - len(phrase) + 1)) == 1


def likely_incomplete(validation: dict[str, Any]) -> bool:
    """Flag substantial ASR-only content, without treating ASR as ground truth."""
    return (
        validation.get("reference_coverage", 0) >= 0.9
        and validation.get("asr_coverage", 1) < 0.7
        and len(validation.get("unmatched_asr", [])) >= 5
    )


def alignment_anchor_check(
    document: dict[str, Any], desired: list[dict[str, Any]], validation: dict[str, Any],
) -> dict[str, Any]:
    """Reject multi-point drift against independent, complete ASR phrases; never shift word times."""
    words = [word for line in document["lines"] for word in line.get("words", [])]
    observed, owners = [], []
    for index, word in enumerate(words):
        units = normalized_units(word["text"])
        observed.extend(units)
        owners.extend([index] * len(units))
    expected = [unit for line in desired for unit in normalized_units(line["text"])]
    matches = _unambiguous_matches(expected, observed)
    cursor, checked = 0, []
    for line, diagnostic in zip(desired, validation.get("lines", []), strict=True):
        units = normalized_units(line["text"])
        anchors = diagnostic.get("anchor_spans")
        if anchors is None:
            anchor = diagnostic.get("anchor")
            anchors = [{**anchor, "start_unit": 0, "end_unit": len(units)}] if anchor and len(units) >= 3 else []
        for anchor in anchors:
            first, last = cursor + anchor["start_unit"], cursor + anchor["end_unit"] - 1
            if first not in matches or last not in matches:
                continue
            start = words[owners[matches[first]]]["start_ms"]
            end = words[owners[matches[last]]]["end_ms"]
            checked.append({"line_index": diagnostic["line_index"], "start_ms": start, "end_ms": end,
                            "asr_start_ms": anchor["start_ms"], "asr_end_ms": anchor["end_ms"],
                            "deviation_ms": abs(start - anchor["start_ms"])})
        cursor += len(units)
    severe = [item for item in checked if item["deviation_ms"] > 5000]
    drift = len({item["line_index"] for item in severe}) >= 2 or any(item["deviation_ms"] > 10000 for item in severe)
    return {"status": "drift" if drift else "checked" if len(checked) >= 2 else "insufficient_anchors",
            "checked": len(checked), "severe_deviations": severe}


def anchored_document(document: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any] | None:
    """Build complete ASR-derived recovery windows without inventing missing timestamps."""
    diagnostics = validation["lines"]
    if not diagnostics or not all("anchor" in line for line in diagnostics):
        return None
    if any(
        previous["anchor"]["end_ms"] > following["anchor"]["start_ms"]
        for previous, following in zip(diagnostics, diagnostics[1:], strict=False)
    ):
        return None
    result = copy.deepcopy(document)
    for line, diagnostic in zip(result["lines"], diagnostics, strict=True):
        line.update(diagnostic["anchor"])
    return result


def restore_structure(document: dict[str, Any], desired: list[dict[str, Any]]) -> dict[str, Any]:
    """Regroup existing timed words at exact reference boundaries; never interpolate times."""
    if [line["text"] for line in document["lines"]] == [line["text"] for line in desired]:
        result = copy.deepcopy(document)
        for line, target in zip(result["lines"], desired, strict=True):
            _reference_agent(line, target)
        return result
    words = []
    unspaced = str(document.get("metadata", {}).get("language", "")).split("-")[0] in {"zh", "chi", "ja", "jpn"}
    for line in document["lines"]:
        if words and not unspaced and not words[-1]["text"].endswith(" "):
            words[-1]["text"] += " "
        for original in line.get("words", []):
            word = copy.deepcopy(original)
            for key in ("agent", "isBackground"):
                if key in line:
                    word.setdefault(key, line[key])
            words.append(word)
    expected = [unit for line in desired for unit in normalized_units(line["text"])]
    actual = [unit for word in words for unit in normalized_units(word["text"])]
    if actual != expected:
        raise ValueError("Cannot restore reference lines: timed words differ from reference")
    result = copy.deepcopy(document)
    result["lines"] = []
    cursor = 0
    for target in desired:
        needed = len(normalized_units(target["text"]))
        group, count = [], 0
        while cursor < len(words) and count < needed:
            word = words[cursor]
            count += len(normalized_units(word["text"]))
            group.append(word)
            cursor += 1
        if not group or count != needed:
            raise ValueError("Reference boundary falls inside a timed word")
        # Keep timed spelling/punctuation and vocal markers; only transfer line boundaries.
        result["lines"].append(
            {
                "text": "".join(w["text"] for w in group).strip(),
                "words": group,
                "start_ms": min(w["start_ms"] for w in group),
                "end_ms": max(w["end_ms"] for w in group),
            }
        )
        _reference_agent(result["lines"][-1], target)
    if cursor != len(words):
        raise ValueError("Unassigned timed words after restoring reference structure")
    return result


def _edit_costs(expected: list[str], observed: list[str]) -> list[list[float]]:
    costs = [[float(i + j) for j in range(len(observed) + 1)] for i in range(len(expected) + 1)]
    for i, left in enumerate(expected, 1):
        for j, right in enumerate(observed, 1):
            similarity = SequenceMatcher(None, left, right, autojunk=False).ratio()
            substitution = 0 if left == right else 0.5 if similarity >= 0.65 else 1
            costs[i][j] = min(costs[i - 1][j] + 1, costs[i][j - 1] + 1, costs[i - 1][j - 1] + substitution)
    return costs


def _boundary_position(expected: list[str], observed: list[str], boundary: int, matches: dict[int, int]) -> int | None:
    if boundary in matches:
        return matches[boundary]
    if boundary - 1 in matches:
        return matches[boundary - 1] + 1
    left = max((index for index in matches if index < boundary), default=-1)
    right = min((index for index in matches if index >= boundary), default=len(expected))
    start = matches[left] + 1 if left >= 0 else 0
    end = matches[right] if right < len(expected) else len(observed)
    if boundary - left > 6 or right - boundary > 6 or end - start > 12:
        return None
    reference_gap, observed_gap = expected[left + 1 : right], observed[start:end]
    forward = _edit_costs(reference_gap, observed_gap)
    backward = _edit_costs(reference_gap[::-1], observed_gap[::-1])
    row = boundary - left - 1
    candidates = [
        j
        for j in range(len(observed_gap) + 1)
        if forward[row][j] + backward[len(reference_gap) - row][len(observed_gap) - j] == forward[-1][-1]
    ]
    return start + candidates[0] if len(candidates) == 1 else None


def _apply_reference_typography(words: list[dict[str, Any]], text: str) -> bool:
    """Copy authored spelling only when each existing word has the same normalized units."""
    tokens = re.findall(r"\S+\s*", text)
    if len(tokens) != len(words) or any(
        normalized_units(token) != normalized_units(word["text"]) for token, word in zip(tokens, words, strict=True)
    ):
        return False
    for token, word in zip(tokens, words, strict=True):
        trailing = word["text"][len(word["text"].rstrip()) :]
        word["text"] = token.rstrip() + (token[len(token.rstrip()) :] or trailing)
    return True


def merge_reference_lines(
    document: dict[str, Any],
    desired: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Transfer reliable reference boundaries despite text differences, preserving every timed word."""
    words, old_cuts = [], set()
    unspaced = str(document.get("metadata", {}).get("language", "")).split("-")[0] in {"zh", "chi", "ja", "jpn"}
    for line in document["lines"]:
        old_cuts.add(len(words))
        if words and not unspaced and not words[-1]["text"].endswith(" "):
            words[-1]["text"] += " "
        for source in line.get("words", []):
            word = copy.deepcopy(source)
            for key in ("agent", "isBackground"):
                if key in line:
                    word.setdefault(key, line[key])
            words.append(word)
    observed, owners = [], []
    for index, word in enumerate(words):
        units = normalized_units(word["text"])
        observed.extend(units)
        owners.extend([index] * len(units))
    expected, boundaries = [], []
    for line in desired:
        boundaries.append(len(expected))
        expected.extend(normalized_units(line["text"]))
    matches = _unambiguous_matches(expected, observed)
    coverage = SequenceMatcher(None, expected, observed, autojunk=False).ratio()
    if not words or not expected or coverage < 0.65:
        raise ValueError("Reference differs too much from timed lyrics to reorganize lines safely")
    accepted = {0: 0, len(desired): len(words)}
    unresolved = []
    for line_index, boundary in enumerate(boundaries[1:], 1):
        position = _boundary_position(expected, observed, boundary, matches)
        if (
            position is None
            or position <= 0
            or position >= len(observed)
            or owners[position] == owners[position - 1]
            or owners[position] <= max(value for index, value in accepted.items() if index < line_index)
        ):
            unresolved.append(line_index)
        else:
            accepted[line_index] = owners[position]
    cuts = set(accepted.values())
    for line_index in unresolved:
        left = accepted[max(index for index in accepted if index < line_index)]
        right = accepted[min(index for index in accepted if index > line_index)]
        cuts.update(cut for cut in old_cuts if left < cut < right)
    result = copy.deepcopy(document)
    result["lines"] = []
    ordered_cuts = sorted(cuts)
    reference_spans = {
        (accepted[index], accepted[index + 1]): desired[index]
        for index in range(len(desired))
        if index in accepted and index + 1 in accepted
    }
    typography_applied = 0
    for start, end in zip(ordered_cuts, ordered_cuts[1:], strict=False):
        group = words[start:end]
        target = reference_spans.get((start, end))
        if target is not None and _apply_reference_typography(group, target["text"]):
            typography_applied += 1
        result["lines"].append(
            {
                "text": "".join(word["text"] for word in group).strip(),
                "words": group,
                "start_ms": min(word["start_ms"] for word in group),
                "end_ms": max(word["end_ms"] for word in group),
            }
        )
        if target is not None:
            _reference_agent(result["lines"][-1], target)
    return result, {
        "method": "fuzzy_reference_boundaries",
        "text_replaced": False,
        "word_timings_preserved": True,
        "typography_applied_lines": typography_applied,
        "text_similarity": round(coverage, 4),
        "reference_lines": len(desired),
        "output_lines": len(result["lines"]),
        "mapped_boundaries": len(accepted) - 2,
        "unresolved_reference_boundaries": unresolved,
    }


def refine_estimated_timings(
    document: dict[str, Any], grouping: dict[str, Any], candidates: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Use acoustic timings only for estimated gaps bounded by unchanged ASR words on both sides."""
    result, report = copy.deepcopy(document), copy.deepcopy(grouping)
    words = [word for line in result["lines"] for word in line.get("words", [])]
    lexical = [(index, word) for index, word in enumerate(words) if normalized_units(word["text"])]
    expected = [normalized_units(word["text"]) for _, word in lexical]
    estimated = set(report.get("estimated_word_indexes", []))
    gaps, gap = [], []
    for position, (index, _) in enumerate(lexical):
        if index in estimated:
            gap.append(position)
        else:
            if gap:
                gaps.append(gap)
            gap = []
    refined = []
    # Leading/trailing gaps lack two trustworthy bounds and intentionally remain estimated.
    for candidate in reversed(candidates):
        acoustic = [word for line in candidate["lines"] for word in line.get("words", [])
                    if normalized_units(word["text"])]
        if [normalized_units(word["text"]) for word in acoustic] != expected:
            continue
        for gap in gaps:
            indexes = [lexical[position][0] for position in gap]
            if gap[0] == 0 or not all(index in estimated for index in indexes):
                continue
            lower = lexical[gap[0] - 1][1]["end_ms"]
            upper = lexical[gap[-1] + 1][1]["start_ms"]
            proposed = [acoustic[position] for position in gap]
            if (
                proposed[0]["start_ms"] < lower or proposed[-1]["end_ms"] > upper
                or any(word["end_ms"] <= word["start_ms"] for word in proposed)
                or any(left["end_ms"] > right["start_ms"] for left, right in zip(proposed, proposed[1:], strict=False))
                or (len(gap) >= 3 and proposed[-1]["end_ms"] - proposed[0]["start_ms"] < len(gap) * 50)
            ):
                continue
            for index, source in zip(indexes, proposed, strict=True):
                words[index].update(start_ms=source["start_ms"], end_ms=source["end_ms"])
                if "confidence" in source:
                    words[index]["confidence"] = source["confidence"]
                estimated.remove(index)
                refined.append(index)
    if refined:
        for line in result["lines"]:
            line["start_ms"] = min(word["start_ms"] for word in line["words"])
            line["end_ms"] = max(word["end_ms"] for word in line["words"])
        report.update(estimated_word_indexes=sorted(estimated), estimated_words=len(estimated),
                      acoustic_refined_word_indexes=sorted(refined), acoustic_refined_words=len(refined))
    return result, report


def apply_reference_text(
    document: dict[str, Any],
    desired: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keep reference text authoritative, reusing matched times and estimating unmatched spans.

    This is a text-based fallback, not acoustic alignment. Estimated word indexes are
    reported separately so ASR confidence is never attributed to replacement words.
    """
    annotated_structure = desired
    desired = [line for line in desired if normalized_units(line["text"])]
    words = []
    for line in document["lines"]:
        for source in line.get("words", []):
            word = copy.deepcopy(source)
            for key in ("agent", "isBackground"):
                if key in line:
                    word.setdefault(key, line[key])
            words.append(word)
    if len(document["lines"]) == len(desired) and all(
        normalized_units("".join(word["text"] for word in line.get("words", []))) == normalized_units(target["text"])
        for line, target in zip(document["lines"], desired, strict=True)
    ):
        result = copy.deepcopy(document)
        for line, target in zip(result["lines"], desired, strict=True):
            # Cross-line parentheses describe vocal roles; they are not missing sung words.
            if target["text"].count("(") == target["text"].count(")"):
                if _apply_reference_typography(line["words"], target["text"]):
                    line["text"] = target["text"]
            _reference_agent(line, target)
        _reference_backgrounds(result, annotated_structure)
        _reference_word_annotations(result, desired)
        return result, {
            "method": "existing_reference_timings",
            "text_action": "reference_applied",
            "text_replaced": False,
            "reference_lines": len(desired),
            "output_lines": len(desired),
            "estimated_word_indexes": [],
            "estimated_words": 0,
            "reused_word_timings": len(words),
            "word_timings_preserved": True,
        }
    tokens_by_line = [re.findall(r"\S+\s*", line["text"]) for line in desired]
    tokens = [token for line in tokens_by_line for token in line]
    if not words or not tokens or any(not line for line in tokens_by_line):
        raise ValueError("Reference timing fallback requires nonempty lines and timed words")
    expected = [" ".join(normalized_units(token)) for token in tokens]
    observed = [" ".join(normalized_units(word["text"])) for word in words]
    anchors = _unambiguous_matches(expected, observed)
    start = min(word["start_ms"] for word in words)
    end = max(word["end_ms"] for word in words)
    if end - start < len(tokens):
        raise ValueError("Audio timing span is too short for reference words")

    # Text repair may estimate a small typo, never an omitted verse or a repeated chorus.
    if len(tokens) - len(anchors) > max(3, len(tokens) * 0.1):
        raise ValueError("Reference needs acoustic recovery: too many unmatched words")

    output: list[dict[str, Any] | None] = [None] * len(tokens)
    for index, source_index in anchors.items():
        output[index] = {**words[source_index], "text": tokens[index]}
    estimated = []
    positions = [-1, *sorted(anchors), len(tokens)]
    for left, right in zip(positions, positions[1:], strict=False):
        count = right - left - 1
        if not count:
            continue
        if count > 3:
            raise ValueError("Reference needs acoustic recovery: unmatched phrase")
        source_start = anchors[left] + 1 if left >= 0 else 0
        source_end = anchors[right] if right < len(tokens) else len(words)
        lo = words[anchors[left]]["end_ms"] if left >= 0 else start
        hi = words[anchors[right]]["start_ms"] if right < len(tokens) else end
        if source_start < source_end:
            lo, hi = words[source_start]["start_ms"], words[source_end - 1]["end_ms"]
        # ASR can omit a verse and leave only a few words near the next chorus.
        # A 1ms validity check alone would pack the missing verse into those words.
        if hi - lo < count or (count >= 3 and hi - lo < count * 50):
            lo = words[anchors[left]]["end_ms"] if left >= 0 else start
            hi = words[anchors[right]]["start_ms"] if right < len(tokens) else end
        if hi - lo < count * 80 or hi - lo > 3000:
            raise ValueError("Reference needs acoustic recovery: insufficient bounded timing evidence")
        for offset in range(count):
            index = left + 1 + offset
            output[index] = {
                "text": tokens[index],
                "start_ms": lo + (hi - lo) * offset // count,
                "end_ms": lo + (hi - lo) * (offset + 1) // count,
            }
            estimated.append(index)
    result = copy.deepcopy(document)
    result["lines"] = []
    cursor = 0
    for target, line_tokens in zip(desired, tokens_by_line, strict=True):
        group = output[cursor : cursor + len(line_tokens)]
        result["lines"].append(
            {
                **copy.deepcopy(target),
                "text": target["text"],
                "words": group,
                "start_ms": min(word["start_ms"] for word in group),
                "end_ms": max(word["end_ms"] for word in group),
            }
        )
        _reference_agent(result["lines"][-1], target)
        cursor += len(line_tokens)
    result["plain"] = "\n".join(line["text"] for line in desired)
    _reference_backgrounds(result, annotated_structure)
    _reference_word_annotations(result, desired)
    return result, {
        "method": "reference_text_with_asr_timing_fallback",
        "text_action": "reference_applied",
        "text_replaced": True,
        "reference_lines": len(desired),
        "output_lines": len(desired),
        "estimated_word_indexes": estimated,
        "estimated_words": len(estimated),
        "reused_word_timings": len(anchors),
        "word_timings_preserved": not estimated and len(words) == len(tokens),
    }
