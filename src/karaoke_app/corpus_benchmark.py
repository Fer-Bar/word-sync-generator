"""Evaluate frozen, manually reviewed songs without changing their reference files."""

import argparse
import hashlib
import json
from pathlib import Path

from karaoke_app.alignment_benchmark import compare_alignment, load_benchmark_candidate, report_destination
from karaoke_app.lyrics_file import load_lyrics_file


def verified_file(root: Path, relative: str, expected_hash: str) -> Path:
    """Reject changed inputs rather than silently moving the benchmark baseline."""
    path = (root / relative).resolve()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected_hash:
        raise ValueError(f"Corpus input changed: {relative}")
    return path


def evaluate_corpus(manifest: Path, root: Path, candidates: Path | None = None) -> dict:
    """Compare historical evidence or supplied candidates to frozen references.

    Supplying a candidate folder does not attest that fresh inference was run.
    Provider simulation and acoustic accuracy must be evaluated separately.
    """
    corpus = json.loads(manifest.read_text(encoding="utf-8"))
    results = []
    for case in corpus["cases"]:
        reference_path = verified_file(root, case["reference"], case["reference_sha256"])
        for field in ("audio", "vocals"):
            verified_file(root, case[field], case[f"{field}_sha256"])
        reference = load_lyrics_file(reference_path)
        sources = case["baselines"] if candidates is None else [{
            "source": str((candidates / case["id"] / "lyrics.lyricsfile.yaml").resolve()),
            "strategy": "supplied_candidate",
        }]
        for source in sources:
            path = (root / source["source"]).resolve()
            if path in {reference_path, (root / case["original_reference"]).resolve()}:
                raise ValueError(f"Candidate is the corrected reference: {path}")
            if candidates is None:
                verified_file(root, source["source"], source["sha256"])
            candidate = load_benchmark_candidate(path)
            results.append({
                "case": case["id"], "reference_status": case["reference_status"],
                "candidate": str(path), "candidate_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "strategy": source.get("strategy"),
                "primary": compare_alignment(reference, candidate),
                "all_voices": compare_alignment(reference, candidate, include_background=True),
            })
    return {"mode": "historical_replay" if candidates is None else "supplied_candidates",
            "fresh_inference_verified": False, "held_out": False,
            "case_count": len(corpus["cases"]), "results": results}


def main() -> None:
    """Write corpus metrics; never overwrite the curated references or run cloud jobs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("reports/alignment-corpus/manifest.json"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = args.manifest.resolve()
    output = args.output.resolve()
    corpus = json.loads(manifest.read_text(encoding="utf-8"))
    protected = {manifest}
    for case in corpus["cases"]:
        protected.update(
            (root / case[field]).resolve() for field in ("reference", "original_reference", "audio", "vocals")
        )
        protected.update((root / source["source"]).resolve() for source in case["baselines"])
        if args.candidates is not None:
            protected.add((args.candidates / case["id"] / "lyrics.lyricsfile.yaml").resolve())
    try:
        output = report_destination(output, list(protected))
    except ValueError as error:
        parser.error(str(error))
    report = evaluate_corpus(manifest, root, args.candidates)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
