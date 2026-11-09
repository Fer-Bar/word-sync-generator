"""Apply authoritative reference text locally after a Colab preparation."""

import importlib.util
import json
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Any

from karaoke_app.job_document import STATE_FILENAME
from karaoke_app.lyric_references import (
    apply_reference_text,
    compare_reference,
    genius_reference,
    plain_lines,
)
from karaoke_app.lyrics_file import dump_lyrics_file, generate_srt, load_lyrics_file, lyrics_to_transcript


def _realign_hint(job_dir: Path, document: dict[str, Any]) -> str:
    """Suggest optional acoustic realignment of estimated fallback word timings."""
    source = document.get("source") or {}
    title = source.get("title") or document.get("title") or "Song"
    artist = source.get("artist") or ""
    album = source.get("album") or ""
    origin = source.get("source_url") or "<URL-o-audio-local>"
    parts = ["uv", "run", "karaoke", origin, "--title", title]
    if artist:
        parts.extend(["--artist", artist])
    if album:
        parts.extend(["--album", album])
    parts.extend(["--lyrics-text", str((job_dir / "reference.txt").resolve())])
    parts.extend(["--output-dir", str(job_dir.resolve().parent)])
    return shlex.join(parts)


def repair_prepared_lyrics(job_dir: Path, pipeline_path: Path, *, genius_url: str | None = None) -> dict[str, Any]:
    """Apply saved or recovered reference text, rolling back changes if writing fails."""
    job_path = job_dir / STATE_FILENAME
    document = json.loads(job_path.read_text(encoding="utf-8"))
    preparation = document.get("preparation", {})
    if preparation.get("disable_lrclib"):
        return {"status": "skipped", "reason": "forced_whisper"}
    reference_path = job_dir / "lyrics_reference.json"
    previous_reference = json.loads(reference_path.read_text(encoding="utf-8")) if reference_path.is_file() else {}
    alignment_path = job_dir / "alignment.json"
    if not alignment_path.is_file():
        return {"status": "skipped", "reason": "no_alignment"}
    alignment = json.loads(alignment_path.read_text(encoding="utf-8"))
    saved_text = job_dir / "reference.txt"
    reference = None
    if saved_text.is_file():
        reference = {**previous_reference, "source": previous_reference.get("source", "txt"),
                     "lines": plain_lines(saved_text.read_text(encoding="utf-8-sig"))}
    elif preparation.get("lrclib_id") is not None or previous_reference.get("source") == "txt":
        return {"status": "skipped", "reason": "missing_explicit_reference_text"}
    elif alignment.get("segmentation") != "heuristic":
        return {"status": "skipped", "reason": "no_local_reference"}
    if reference is None:
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
            candidate = {
                "trackName": reference["metadata"]["title"],
                "artistName": reference["metadata"]["artist"],
                "plainLyrics": reference["original_text"],
            }
            if not pipeline._lrclib_candidate_is_safe(
                candidate,
                track=metadata.get("track") or metadata["title"],
                artist=metadata.get("artist"),
                duration=None,
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
    merged, grouping = apply_reference_text(original, reference["lines"])
    serialized = dump_lyrics_file(merged)
    if serialized == dump_lyrics_file(original):
        return {"status": "skipped", "reason": "reference_text_already_applied"}
    text_summary = {"text_action": "reference_applied", "estimated_words": grouping["estimated_words"]}
    realign_command = _realign_hint(job_dir, document)
    transcript_path = job_dir / "transcription.json"
    speech = json.loads(transcript_path.read_text(encoding="utf-8")) if transcript_path.is_file() else None
    validation = compare_reference(reference["lines"], speech) if speech else {"needs_review": True, "lines": []}
    validation.update(line_basis="reference", grouping=grouping, **text_summary, realign_hint=realign_command)
    validation["needs_review"] |= bool(grouping["estimated_words"])
    if "fallback_reason" in alignment:
        alignment["initial_fallback_reason"] = alignment.pop("fallback_reason")
    alignment.update(
        strategy="reference_text_asr_timing",
        word_timing="estimated" if grouping["estimated_words"] else alignment.get("word_timing", "provided"),
        text_source=reference["source"],
        segmentation="reference",
        reference_source=reference["source"],
        needs_review=validation["needs_review"],
        grouping=grouping,
        local_reference_recovery=True,
        text_action=text_summary["text_action"],
        estimated_words=grouping["estimated_words"],
        realign_hint=realign_command,
        reference_file="lyrics_reference.json",
        reference_text_file="reference.txt",
        validation_file="lyrics_validation.json",
    )
    alignment["words"] = [
        {**word, "text": word["text"].strip()}
        for segment in lyrics_to_transcript(merged)["segments"]
        for word in segment["words"]
    ]
    document["alignment"] = {key: value for key, value in alignment.items() if key != "words"}
    provenance = {key: value for key, value in reference.items() if key not in {"lines", "original_text"}}
    provenance.update(
        reference_text_file="reference.txt",
        line_count=len(reference["lines"]),
        acquisition="local",
        grouping=grouping,
        text_action=text_summary["text_action"],
        estimated_words=grouping["estimated_words"],
        realign_hint=realign_command,
    )
    payloads = {
        lyrics_path.relative_to(job_dir.resolve()).as_posix(): serialized,
        "lyrics.srt": generate_srt(merged),
        "reference.txt": (
            saved_text.read_text(encoding="utf-8-sig")
            if saved_text.is_file()
            else reference.get("original_text") or "\n".join(line["text"] for line in reference["lines"]) + "\n"
        ),
        **{
            name: json.dumps(value, ensure_ascii=False, indent=2) + "\n"
            for name, value in (
                ("alignment.json", alignment),
                (STATE_FILENAME, document),
                ("lyrics_reference.json", provenance),
                ("lyrics_validation.json", validation),
            )
        },
    }
    with tempfile.TemporaryDirectory(prefix="lyrics-repair-") as directory:
        backup = Path(directory)
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
        finally:
            for name in payloads:
                target = job_dir / name
                target.with_name(f".{target.name}.repair").unlink(missing_ok=True)
    return {
        "status": "repaired",
        "reused_word_timings": grouping["reused_word_timings"],
        "realign_hint": realign_command,
        **grouping,
        **text_summary,
    }
