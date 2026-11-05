"""Assess local timing conflicts without treating missing evidence as successful verification."""

import hashlib
import json
import statistics
from collections.abc import Callable


def timing_fingerprint(document: dict) -> str:
    """Bind a timing assessment to the exact lyric content it evaluated."""
    payload = json.dumps(document["lines"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _word_units(line, normalize):
    owners = []
    for word in line.get("words", []):
        owners.extend([word] * len(normalize(word["text"])))
    return owners


def assess_timing(
    document: dict, reference: list[dict], validation: dict, *, normalize: Callable,
    reference_calibration: dict | None = None,
) -> dict:
    """Combine reference residuals, acoustic scores and independent word anchors by region.

    Reference offsets are estimated only from several consistent, strong CTC lines.
    Scores are evidence, not calibrated correctness probabilities. Long notes and absent
    ASR anchors alone never constitute a timing conflict.
    """
    desired = [(i, line) for i, line in enumerate(reference) if normalize(line.get("text", ""))]
    output = [line for line in document["lines"] if normalize(line.get("text", ""))]
    result = {"version": 1, "fingerprint": timing_fingerprint(document), "status": "unverified",
              "regions": [], "lines": [], "reference_offset_ms": None}
    if [normalize(line["text"]) for _, line in desired] != [normalize(line["text"]) for line in output]:
        return {**result, "reason": "reference_structure_differs"}
    diagnostics = {line["line_index"]: line for line in validation.get("lines", [])}
    calibration = []
    for index, ((raw_index, raw), line) in enumerate(zip(desired, output, strict=True)):
        words = line.get("words", [])
        scores = [word["confidence"] for word in words if "confidence" in word]
        confidence = statistics.mean(scores) if len(scores) == len(words) and words else None
        raw_start = raw.get("start_ms")
        reference_start = raw_start if isinstance(raw_start, int | float) and raw_start >= 0 else None
        row = {"line_index": index, "reference_index": raw_index, "start_ms": line["start_ms"],
               "end_ms": line["end_ms"], "confidence": confidence, "reference_start_ms": reference_start,
               "word_count": len(words), "anchor_words": [], "reasons": []}
        owners = _word_units(line, normalize)
        for span in diagnostics.get(raw_index, {}).get("anchor_spans", []):
            anchors = span.get("word_starts") or [{"unit": span["start_unit"], "start_ms": span["start_ms"]}]
            for anchor in anchors:
                if 0 <= anchor["unit"] < len(owners):
                    start = owners[anchor["unit"]]["start_ms"]
                    row["anchor_words"].append({"unit": anchor["unit"], "start_ms": start,
                                                "asr_start_ms": anchor["start_ms"],
                                                "deviation_ms": start - anchor["start_ms"]})
        deviations = [abs(anchor["deviation_ms"]) for anchor in row["anchor_words"]]
        if sum(delta > 1500 for delta in deviations) >= 2:
            row["reasons"].append("independent_word_disagreement")
        if reference_start is not None and confidence is not None and confidence >= .45:
            calibration.append(line["start_ms"] - reference_start)
        result["lines"].append(row)
    if reference_calibration is not None:
        result["reference_offset_ms"] = reference_calibration["reference_offset_ms"]
    elif len(calibration) >= 5:
        offset = statistics.median(calibration)
        spread = statistics.median(abs(value - offset) for value in calibration)
        if spread <= 500:
            result["reference_offset_ms"] = offset
    offset = result["reference_offset_ms"]
    rows = result["lines"]
    for row in rows:
        row["reference_residual_ms"] = (
            row["start_ms"] - row["reference_start_ms"] - offset
            if offset is not None and row["reference_start_ms"] is not None else None
        )
    for index, row in enumerate(rows):
        residual, confidence = row["reference_residual_ms"], row["confidence"]
        if residual is None or confidence is None:
            continue
        adjacent = rows[max(0, index - 1):index] + rows[index + 1:index + 2]
        neighbor_conflict = any(abs(other["reference_residual_ms"] or 0) > 1500 for other in adjacent)
        supported = len(row["anchor_words"]) >= 2 and all(
            abs(anchor["deviation_ms"]) <= 750 for anchor in row["anchor_words"]
        )
        if not supported and confidence < .20 and abs(residual) > 1500 and (neighbor_conflict or abs(residual) > 2500):
            row["reasons"].append("weak_ctc_reference_disagreement")
    for row, following in zip(rows, rows[1:], strict=False):
        if (following["reasons"] and offset is not None and following["reference_start_ms"] is not None
                and row["confidence"] is not None and row["confidence"] < .35
                and row["end_ms"] > following["reference_start_ms"] + offset + 1000):
            row["reasons"].append("stretched_before_conflict")
    flagged = [row["line_index"] for row in rows if row["reasons"]]
    for index in flagged:
        if result["regions"] and index <= result["regions"][-1]["last_line"] + 2:
            result["regions"][-1]["last_line"] = index
        else:
            result["regions"].append({"first_line": index, "last_line": index})
    for region in result["regions"]:
        selected = rows[region["first_line"]:region["last_line"] + 1]
        starts = [row["start_ms"] for row in selected]
        if offset is not None:
            starts.extend(row["reference_start_ms"] + offset for row in selected
                          if row["reference_start_ms"] is not None)
        region.update(start_ms=min(starts), end_ms=max(row["end_ms"] for row in selected))
    covered = sum(bool(row["anchor_words"]) for row in rows)
    covered_words = sum(len({anchor["unit"] for anchor in row["anchor_words"]}) for row in rows)
    total_words = sum(row["word_count"] for row in rows)
    result.update(status="conflict" if flagged else "checked" if covered_words == total_words and rows else "partial",
                  anchored_lines=covered, total_lines=len(rows), anchored_words=covered_words, total_words=total_words)
    return result


def recovery_windows(assessment: dict, *, duration_ms: int) -> list[dict]:
    """Bound conflicted regions with context; never use an inferred LRC end as a silence."""
    rows, windows = assessment["lines"], []
    offset = assessment["reference_offset_ms"]
    for region in assessment["regions"]:
        first, last = max(0, region["first_line"] - 1), min(len(rows) - 1, region["last_line"] + 1)
        if offset is not None and rows[first]["reference_start_ms"] is not None:
            start = rows[first]["reference_start_ms"] + offset
            end = (rows[last + 1]["reference_start_ms"] + offset
                   if last + 1 < len(rows) and rows[last + 1]["reference_start_ms"] is not None else duration_ms)
        else:
            before, after = rows[first]["anchor_words"], rows[last]["anchor_words"]
            if not before or not after:
                continue
            start, end = min(a["asr_start_ms"] for a in before), rows[last]["end_ms"]
        if end <= start or end - start > 30000:
            continue
        window = {"first_line": first, "last_line": last, "start_ms": max(0, round(start - 500)),
                  "end_ms": min(duration_ms, round(end + 500)),
                  "conflict_first": region["first_line"], "conflict_last": region["last_line"]}
        if windows and first <= windows[-1]["last_line"]:
            previous = windows[-1]
            if window["end_ms"] - previous["start_ms"] <= 30000:
                previous.update(last_line=last, end_ms=window["end_ms"], conflict_last=region["last_line"])
                continue
        windows.append(window)
    return windows


def require_timing_review(document: dict, assessment: dict | None, *, reviewed: bool = False) -> None:
    """Prevent unresolved severe conflicts from silently reaching a final render."""
    if not assessment or assessment.get("status") != "conflict" or reviewed:
        return
    ranges = ", ".join(f"{r['start_ms'] / 1000:.1f}–{r['end_ms'] / 1000:.1f}s"
                       for r in assessment.get("regions", []))
    changed = timing_fingerprint(document) != assessment.get("fingerprint")
    detail = ("Lyrics changed after the assessment; verify the corrected timings"
              if changed else "Timing conflicts remain")
    raise ValueError(f"{detail}: {ranges}. Review the preview, then use --accept-timing-review to render.")
