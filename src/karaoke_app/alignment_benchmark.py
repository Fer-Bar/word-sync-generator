"""Compare provisional LyricsFile references without feeding them into inference."""

import argparse
import json
import math
import re
import statistics
from collections import Counter
from pathlib import Path

from karaoke_app.lyrics_file import load_lyrics_file


def _tokens(document: dict, include_background: bool) -> list[dict]:
    tokens = []
    for line_index, line in enumerate(document["lines"]):
        for word in line.get("words", []):
            background = bool(word.get("isBackground") or line.get("isBackground"))
            if background and not include_background:
                continue
            text = re.sub(r"[^\w']", "", word["text"].casefold().replace("’", "'"))
            if text:
                tokens.append({**word, "token": text, "line": line_index, "background": background,
                               "agent": word.get("agent", line.get("agent"))})
    return sorted(tokens, key=lambda word: word["start_ms"])


def _align(reference: list[dict], candidate: list[dict]) -> list[tuple[str, int | None, int | None]]:
    costs = [[0] * (len(candidate) + 1) for _ in range(len(reference) + 1)]
    for i in range(len(reference) + 1):
        costs[i][0] = i
    for j in range(len(candidate) + 1):
        costs[0][j] = j
    for i, ref in enumerate(reference, 1):
        for j, item in enumerate(candidate, 1):
            costs[i][j] = min(costs[i - 1][j] + 1, costs[i][j - 1] + 1,
                              costs[i - 1][j - 1] + (ref["token"] != item["token"]))
    operations = []
    i, j = len(reference), len(candidate)
    while i or j:
        same = bool(i and j and reference[i - 1]["token"] == candidate[j - 1]["token"])
        if i and j and costs[i][j] == costs[i - 1][j - 1] + (not same):
            operations.append(("match" if same else "substitution", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i and costs[i][j] == costs[i - 1][j] + 1:
            operations.append(("deletion", i - 1, None))
            i -= 1
        else:
            operations.append(("insertion", None, j - 1))
            j -= 1
    return list(reversed(operations))


def compare_alignment(reference: dict, candidate: dict, *, include_background: bool = False) -> dict:
    """Report token edits and raw timing differences on exact lexical matches only.

    Labels are not treated as speaker identities. No temporal offset is applied;
    repeated words can make minimum-edit alignment ambiguous.
    """
    ref = _tokens(reference, include_background)
    hyp = _tokens(candidate, include_background)
    operations = _align(ref, hyp)
    counts = Counter(op for op, _, _ in operations)
    differences = []
    text_differences = []
    background_matches = Counter()
    for op, i, j in operations:
        if op == "match":
            background_matches[ref[i]["background"], hyp[j]["background"]] += 1
            differences.append({"reference_index": i, "candidate_index": j,
                                "reference_start_ms": ref[i]["start_ms"],
                                "candidate_start_ms": hyp[j]["start_ms"],
                                "start_delta_ms": hyp[j]["start_ms"] - ref[i]["start_ms"],
                                "end_delta_ms": hyp[j]["end_ms"] - ref[i]["end_ms"]})
        else:
            text_differences.append({
                "operation": op,
                "reference": {k: ref[i][k] for k in ("text", "start_ms", "end_ms", "line")} if i is not None else None,
                "candidate": {k: hyp[j][k] for k in ("text", "start_ms", "end_ms", "line")} if j is not None else None,
            })
    starts = [abs(d["start_delta_ms"]) for d in differences]
    ends = [abs(d["end_delta_ms"]) for d in differences]
    true_positive = background_matches[True, True]
    false_positive = background_matches[False, True]
    false_negative = background_matches[True, False]
    return {
        "include_background": include_background,
        "reference_tokens": len(ref), "candidate_tokens": len(hyp),
        "operations": {key: counts[key] for key in ("match", "substitution", "deletion", "insertion")},
        "token_error_rate": (len(operations) - counts["match"]) / len(ref) if ref else None,
        "matched_reference_fraction": counts["match"] / len(ref) if ref else None,
        "background_on_exact_matches": {
            "true_positive": true_positive, "false_positive": false_positive, "false_negative": false_negative,
            "precision": true_positive / (true_positive + false_positive) if true_positive + false_positive else None,
            "recall": true_positive / (true_positive + false_negative) if true_positive + false_negative else None,
            "reference_background_tokens": sum(w["background"] for w in ref),
            "candidate_background_tokens": sum(w["background"] for w in hyp),
        } if include_background else None,
        "timing_on_exact_matches": {
            "count": len(differences),
            "start_mae_ms": statistics.mean(starts) if starts else None,
            "end_mae_ms": statistics.mean(ends) if ends else None,
            "median_signed_start_delta_ms": statistics.median(d["start_delta_ms"] for d in differences)
            if differences else None,
            "start_within_200_ms_fraction": sum(v <= 200 for v in starts) / len(starts) if starts else None,
        },
        "reference_agents": dict(Counter(w["agent"] or "unassigned" for w in ref)),
        "candidate_agents": dict(Counter(w["agent"] or "unassigned" for w in hyp)),
        "text_differences": text_differences,
        "largest_timing_differences": sorted(differences, key=lambda d: abs(d["start_delta_ms"]), reverse=True)[:20],
        "limitations": ["Reference audio/version and manual accuracy must be verified independently.",
                        "Tokenization differences (syllables, contractions) affect token error rate.",
                        "Repeated phrases and overlapping voices can make text alignment ambiguous.",
                        "Timing metrics exclude unmatched tokens; inspect match coverage too.",
                        "Background classification measures lexical matches, not acoustic voice separation.",
                        "Agent coverage is not speaker accuracy; IDs have no verified identity mapping.",
                        "Primary comparison excludes only marked background; unlabelled candidate chorus remains."],
    }



def load_benchmark_candidate(path: Path) -> dict:
    """Load YAML or saved ASR/alignment JSON without repairing the measured timings."""
    if path.suffix.lower() != ".json":
        return load_lyrics_file(path)
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Candidate JSON must be an object")
    segments = document.get("segments")
    if segments is None and isinstance(document.get("words"), list):
        segments = [{"words": document["words"]}]
    if not isinstance(segments, list) or not segments:
        raise ValueError("Candidate JSON must contain segments or words")
    lines = []
    for segment in segments:
        if not isinstance(segment, dict) or not isinstance(segment.get("words"), list):
            raise ValueError("Candidate segments must contain word lists")
        words = []
        for word in segment["words"]:
            if not isinstance(word, dict) or not isinstance(word.get("text"), str):
                raise ValueError("Candidate words must contain text")
            times = [word.get("start"), word.get("end")]
            if any(isinstance(t, bool) or not isinstance(t, int | float) or not math.isfinite(t) for t in times):
                raise ValueError("Candidate word times must be finite seconds")
            if times[0] < 0 or times[1] < times[0]:
                raise ValueError("Candidate word times must be ordered and non-negative")
            words.append({"text": word["text"], "start_ms": round(times[0] * 1000),
                          "end_ms": round(times[1] * 1000),
                          **{key: word[key] for key in ("agent", "isBackground") if key in word}})
        lines.append({"words": words, **{key: segment[key] for key in ("agent", "isBackground") if key in segment}})
    if not any(line["words"] for line in lines):
        raise ValueError("Candidate JSON contains no timed words")
    return {"metadata": document.get("song", {}), "lines": lines}


def report_destination(output: Path, inputs: list[Path]) -> Path:
    """Reject report paths that refer to an input, including symbolic and hard links."""
    destination = output.resolve()
    if any(destination == path.resolve() or (destination.exists() and path.exists() and destination.samefile(path))
           for path in inputs):
        raise ValueError("Output must not overwrite an input file")
    return destination


def main() -> None:
    """Write a comparison report without modifying either input file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        output = report_destination(args.output, [args.reference, args.candidate])
    except ValueError as error:
        parser.error(str(error))
    reference = load_lyrics_file(args.reference)
    candidate = load_benchmark_candidate(args.candidate)
    report = {"reference": str(args.reference), "candidate": str(args.candidate),
              "primary": compare_alignment(reference, candidate),
              "all_voices": compare_alignment(reference, candidate, include_background=True)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
