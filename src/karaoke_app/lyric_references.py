"""Resolve lyric references and compare their structure with independent ASR evidence."""

import copy
import os
import re
import unicodedata
from array import array
from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def normalized_units(text: str) -> list[str]:
    """Normalize only for comparison, retaining the original display text separately."""
    text = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    text = text.replace("'", "")
    return re.findall(r"[\u3400-\u9fff\u3040-\u30ff]|[^\W_\u3400-\u9fff\u3040-\u30ff]+", text)


def plain_lines(text: str) -> list[dict[str, Any]]:
    """Keep authored line breaks and vocals; omit standalone editorial section headers."""
    return [{"text": line.strip()} for line in text.splitlines()
            if line.strip() and not re.fullmatch(r"\s*\[[^\]]+\]\s*", line)]


def validate_genius_url(url: str) -> str:
    """Accept only direct HTTPS song pages on Genius."""
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname not in {"genius.com", "www.genius.com"}
            or parsed.username or parsed.password or parsed.port not in {None, 443}
            or not parsed.path.endswith("-lyrics") or parsed.query or parsed.fragment):
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
    metadata: dict[str, Any], *, url: str | None,
    candidate_is_safe: Callable[..., bool], client_factory: Callable[[], Any] | None = None,
) -> dict[str, Any] | None:
    """Fetch a metadata-checked song, rejecting ambiguous automatic search results."""
    from lyricsgenius import PublicAPI

    track = metadata.get("track") or metadata.get("title") or ""
    artist = metadata.get("artist")
    if not track or not artist:
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
    candidates = []
    for section in sections:
        for hit in section.get("hits", []):
            song = hit.get("result", {})
            candidate = {
                "trackName": song.get("title"),
                "artistName": (song.get("primary_artist") or {}).get("name"),
                "plainLyrics": "metadata check",
            }
            if not candidate_is_safe(candidate, track=track, artist=artist, duration=None):
                continue
            song_url = song.get("url", "")
            if url and song_url.rstrip("/").replace("www.", "") != url.rstrip("/").replace("www.", ""):
                continue
            if song.get("id") not in {item.get("id") for item in candidates}:
                candidates.append(song)
    if len(candidates) != 1:
        return None
    song = candidates[0]
    song_url = validate_genius_url(song["url"])
    text = client.lyrics(song_url=song_url, remove_section_headers=False)
    if not text or not plain_lines(text):
        return None
    return {
        "source": "genius", "id": song.get("id"), "url": song_url,
        "original_text": text, "lines": plain_lines(text),
        "metadata": {"title": song["title"], "artist": song["primary_artist"]["name"]},
    }


def resolve_reference(
    options: dict[str, Any], metadata: dict[str, Any], record: dict[str, Any] | None,
    *, record_to_document: Callable[[], dict[str, Any]], candidate_is_safe: Callable[..., bool],
    fetch_genius: Callable[..., dict[str, Any] | None] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Resolve explicit TXT, LRCLIB, then Genius; keep failures and source evidence."""
    evidence: dict[str, Any] = {"attempts": []}
    if options.get("disable_lrclib"):
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
        evidence["lrclib_record"] = record
        try:
            document = record_to_document()
            evidence.update(source="lrclib", id=record.get("id"), lines=copy.deepcopy(document["lines"]))
            text = record.get("plainLyrics")
            if isinstance(text, str) and plain_lines(text):
                evidence["original_text"] = text
                desired = plain_lines(text)
                current_units = normalized_units(" ".join(line["text"] for line in document["lines"]))
                desired_units = normalized_units(" ".join(line["text"] for line in desired))
                if current_units == desired_units:
                    evidence["structure_lines"] = desired
                else:
                    evidence["text_conflict"] = True
                    evidence["alternative_lines"] = desired
            return document, evidence
        except (ValueError, KeyError, TypeError) as error:
            evidence["attempts"].append({"source": "lrclib", "error": str(error)})
    try:
        reference = (fetch_genius or genius_reference)(
            metadata, url=options.get("genius_url"), candidate_is_safe=candidate_is_safe,
        )
        if reference:
            evidence.update(reference)
            return {"version": "1.0", "metadata": dict(metadata), "lines": reference["lines"]}, evidence
        evidence["attempts"].append({"source": "genius", "error": "no_unambiguous_metadata_match"})
    except Exception as error:
        # A provider failure must not discard the already acquired audio.
        evidence["attempts"].append({"source": "genius", "error": f"{type(error).__name__}: {error}"[:2000]})
    evidence["source"] = "whisper"
    return None, evidence


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
            prefix[i + 1][j + 1] = (prefix[i][j] + 1 if expected[i] == observed[j]
                                     else max(prefix[i][j + 1], prefix[i + 1][j]))
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            suffix[i][j] = (suffix[i + 1][j + 1] + 1 if expected[i] == observed[j]
                            else max(suffix[i + 1][j], suffix[i][j + 1]))
    optimum = prefix[n][m]
    unique = {}
    for i in range(n):
        candidates = [j for j in range(m) if expected[i] == observed[j]
                      and prefix[i][j] + 1 + suffix[i + 1][j + 1] == optimum]
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
            "line_index": index, "text": lines[index]["text"], "matched_units": len(matched),
            "total_units": len(units), "missing_or_different": [expected[i] for i in indexes if i not in mapping],
            "needs_review": not anchor_safe,
            "differences": [
                {"operation": tag, "reference": expected[a:b], "asr": observed[c:d]}
                for tag, a, b, c, d in matcher.get_opcodes()
                if tag != "equal" and (
                    (a < cursor + len(units) and b > cursor)
                    or (a == b and cursor <= a < cursor + len(units))
                    or (index == len(lines) - 1 and a == b == len(expected))
                )
            ],
        }
        entry["needs_review"] |= bool(entry["differences"])
        if anchor_safe:
            start_word, end_word = owners[matched[0]], owners[matched[-1]]
            selected = words[start_word:end_word + 1]
            if all(word.get("probability", 0) >= 0.5 and word["end"] > word["start"] for word in selected):
                entry["anchor"] = {"start_ms": round(selected[0]["start"] * 1000),
                                   "end_ms": round(selected[-1]["end"] * 1000)}
            else:
                entry["needs_review"] = True
        diagnostics.append(entry)
        cursor += len(units)
    matched_observed = set(mapping.values())
    return {
        "method": "ordered_sequence_comparison", "line_basis": "reference",
        "reference_coverage": len(mapping) / max(1, len(expected)),
        "asr_coverage": len(mapping) / max(1, len(observed)),
        "unmatched_asr": [unit for i, unit in enumerate(observed) if i not in matched_observed],
        "needs_review": any(line["needs_review"] for line in diagnostics) or len(mapping) != len(observed),
        "lines": diagnostics,
    }


def likely_incomplete(validation: dict[str, Any]) -> bool:
    """Flag substantial ASR-only content, without treating ASR as ground truth."""
    return (validation.get("reference_coverage", 0) >= 0.9
            and validation.get("asr_coverage", 1) < 0.7
            and len(validation.get("unmatched_asr", [])) >= 5)


def anchored_document(document: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any] | None:
    """Build complete ASR-derived recovery windows without inventing missing timestamps."""
    diagnostics = validation["lines"]
    if not diagnostics or not all("anchor" in line for line in diagnostics):
        return None
    if any(previous["anchor"]["end_ms"] > following["anchor"]["start_ms"]
           for previous, following in zip(diagnostics, diagnostics[1:], strict=False)):
        return None
    result = copy.deepcopy(document)
    for line, diagnostic in zip(result["lines"], diagnostics, strict=True):
        line.update(diagnostic["anchor"])
    return result


def restore_structure(document: dict[str, Any], desired: list[dict[str, Any]]) -> dict[str, Any]:
    """Regroup existing timed words at exact reference boundaries; never interpolate times."""
    if [line["text"] for line in document["lines"]] == [line["text"] for line in desired]:
        return document
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
        result["lines"].append({"text": "".join(w["text"] for w in group).strip(), "words": group,
                                "start_ms": min(w["start_ms"] for w in group),
                                "end_ms": max(w["end_ms"] for w in group)})
    if cursor != len(words):
        raise ValueError("Unassigned timed words after restoring reference structure")
    return result


def _edit_costs(expected: list[str], observed: list[str]) -> list[list[float]]:
    costs = [[float(i + j) for j in range(len(observed) + 1)] for i in range(len(expected) + 1)]
    for i, left in enumerate(expected, 1):
        for j, right in enumerate(observed, 1):
            similarity = SequenceMatcher(None, left, right, autojunk=False).ratio()
            substitution = 0 if left == right else 0.5 if similarity >= 0.65 else 1
            costs[i][j] = min(costs[i - 1][j] + 1, costs[i][j - 1] + 1,
                              costs[i - 1][j - 1] + substitution)
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
    reference_gap, observed_gap = expected[left + 1:right], observed[start:end]
    forward = _edit_costs(reference_gap, observed_gap)
    backward = _edit_costs(reference_gap[::-1], observed_gap[::-1])
    row = boundary - left - 1
    candidates = [j for j in range(len(observed_gap) + 1)
                  if forward[row][j] + backward[len(reference_gap) - row][len(observed_gap) - j]
                  == forward[-1][-1]]
    return start + candidates[0] if len(candidates) == 1 else None


def merge_reference_lines(
    document: dict[str, Any], desired: list[dict[str, Any]],
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
        if (position is None or position <= 0 or position >= len(observed)
                or owners[position] == owners[position - 1]
                or owners[position] <= max(value for index, value in accepted.items() if index < line_index)):
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
    for start, end in zip(ordered_cuts, ordered_cuts[1:], strict=False):
        group = words[start:end]
        result["lines"].append({"text": "".join(word["text"] for word in group).strip(), "words": group,
                                "start_ms": min(word["start_ms"] for word in group),
                                "end_ms": max(word["end_ms"] for word in group)})
    return result, {
        "method": "fuzzy_reference_boundaries", "text_replaced": False, "word_timings_preserved": True,
        "text_similarity": round(coverage, 4), "reference_lines": len(desired), "output_lines": len(result["lines"]),
        "mapped_boundaries": len(accepted) - 2, "unresolved_reference_boundaries": unresolved,
    }
