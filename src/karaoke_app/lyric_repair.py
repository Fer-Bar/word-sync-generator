"""Recover reference-based line grouping locally after a Colab preparation."""

import importlib.util
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from karaoke_app.lyric_references import compare_reference, genius_reference, merge_reference_lines
from karaoke_app.lyrics_file import dump_lyrics_file, generate_srt, load_lyrics_file, lyrics_to_transcript


def repair_prepared_lyrics(job_dir: Path, pipeline_path: Path, *, genius_url: str | None = None) -> dict[str, Any]:
    """Recover missing reference lines, backing up changed artifacts and keeping every word timestamp."""
    job_path = job_dir / "job.json"
    document = json.loads(job_path.read_text(encoding="utf-8"))
    preparation = document.get("preparation", {})
    if preparation.get("disable_lrclib"):
        return {"status": "skipped", "reason": "forced_whisper"}
    reference_path = job_dir / "lyrics_reference.json"
    previous_reference = json.loads(reference_path.read_text(encoding="utf-8")) if reference_path.is_file() else {}
    if preparation.get("lrclib_id") is not None or previous_reference.get("source") == "txt":
        return {"status": "skipped", "reason": "explicit_reference_selection"}
    alignment_path = job_dir / "alignment.json"
    if not alignment_path.is_file():
        return {"status": "skipped", "reason": "no_alignment"}
    alignment = json.loads(alignment_path.read_text(encoding="utf-8"))
    if alignment.get("segmentation") != "heuristic":
        return {"status": "skipped", "reason": "reference_structure_already_applied"}
    spec = importlib.util.spec_from_file_location("karaoke_reference_matching", pipeline_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load pipeline metadata matching")
    pipeline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipeline)
    metadata = document.get("source") or {"title": document["title"]}
    cached_path = job_dir / "genius_reference.json"
    reference = json.loads(cached_path.read_text(encoding="utf-8")) if cached_path.is_file() else None
    if reference and genius_url and reference.get("url") != genius_url:
        reference = None
    if reference:
        candidate = {"trackName": reference["metadata"]["title"],
                     "artistName": reference["metadata"]["artist"], "plainLyrics": reference["original_text"]}
        if not pipeline._lrclib_candidate_is_safe(
            candidate, track=metadata.get("track") or metadata["title"], artist=metadata.get("artist"), duration=None,
        ):
            reference = None
    if reference is None:
        reference = genius_reference(metadata, url=genius_url, candidate_is_safe=pipeline._lrclib_candidate_is_safe)
    if reference is None:
        return {"status": "unavailable", "reason": "no_safe_local_genius_reference"}

    lyrics_path = (job_dir / document["media"]["lyrics"]).resolve()
    if not lyrics_path.is_relative_to(job_dir.resolve()):
        raise ValueError("Lyrics artifact must be inside the job directory")
    original = load_lyrics_file(lyrics_path)
    merged, grouping = merge_reference_lines(original, reference["lines"])
    serialized = dump_lyrics_file(merged)
    transcript_path = job_dir / "transcription.json"
    speech = json.loads(transcript_path.read_text(encoding="utf-8")) if transcript_path.is_file() else None
    validation = compare_reference(merged["lines"], speech) if speech else {"needs_review": True, "lines": []}
    validation.update(line_basis="output", grouping=grouping)
    validation["needs_review"] |= bool(grouping["unresolved_reference_boundaries"])
    before = [(w["text"].strip(), w["start_ms"], w["end_ms"])
              for line in original["lines"] for w in line["words"]]
    after = [(w["text"].strip(), w["start_ms"], w["end_ms"])
             for line in merged["lines"] for w in line["words"]]
    if before != after:
        raise ValueError("Line repair must preserve every word and timestamp")
    if "fallback_reason" in alignment:
        alignment["initial_fallback_reason"] = alignment.pop("fallback_reason")
    alignment.update(strategy="reference_grouped_asr", segmentation="reference", reference_source="genius",
                     needs_review=validation["needs_review"], grouping=grouping, local_reference_recovery=True,
                     reference_file="lyrics_reference.json", reference_text_file="reference.txt",
                     validation_file="lyrics_validation.json")
    alignment["words"] = [{**word, "text": word["text"].strip()}
                          for segment in lyrics_to_transcript(merged)["segments"] for word in segment["words"]]
    document["alignment"] = {key: value for key, value in alignment.items() if key != "words"}
    provenance = {key: value for key, value in reference.items() if key not in {"lines", "original_text"}}
    provenance.update(reference_text_file="reference.txt", line_count=len(reference["lines"]),
                      acquisition="local", grouping=grouping)
    payloads = {
        lyrics_path.relative_to(job_dir.resolve()).as_posix(): serialized,
        "lyrics.srt": generate_srt(merged),
        "reference.txt": "\n".join(line["text"] for line in reference["lines"]) + "\n",
        **{name: json.dumps(value, ensure_ascii=False, indent=2) + "\n" for name, value in (
            ("alignment.json", alignment), ("job.json", document),
            ("lyrics_reference.json", provenance), ("lyrics_validation.json", validation),
        )},
    }
    backup = job_dir / f"lyrics-backup-{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    backup.mkdir()
    existing = {name for name in payloads if (job_dir / name).is_file()}
    for name in existing:
        destination = backup / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(job_dir / name, destination)
    try:
        for name, content in payloads.items():
            target = job_dir / name
            temporary = target.with_name(f".{target.name}.repair")
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(target)
    except Exception:
        for name in payloads:
            if name in existing:
                shutil.copy2(backup / name, job_dir / name)
            else:
                (job_dir / name).unlink(missing_ok=True)
        raise
    return {"status": "repaired", "backup": str(backup), "words_preserved": len(before), **grouping}
