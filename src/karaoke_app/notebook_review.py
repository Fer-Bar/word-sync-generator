"""Apply reviewed lyrics and export the current editable notebook project."""

import shutil
import unicodedata
import uuid
import zipfile
from pathlib import Path

from karaoke_app.job_document import load_job_document, resolve_job_asset
from karaoke_app.lyrics_file import dump_lyrics_file, load_lyrics_file
from karaoke_app.notebook_inputs import validate_inputs


def _identity_key(value: str) -> str:
    return "".join(character for character in unicodedata.normalize("NFKC", value).casefold() if character.isalnum())


def _validate_import(root: Path, project: dict, lyrics: dict) -> None:
    source = project.get("source") or {}
    expected = {
        "title": source.get("track") or source.get("title") or project["title"],
        "artist": source.get("artist"),
    }
    metadata = lyrics["metadata"]
    for field, value in expected.items():
        if value and _identity_key(value) != _identity_key(metadata.get(field, "")):
            raise ValueError(f"Lyrics {field} does not match this project. Import the YAML exported for this song.")
    audio = resolve_job_asset(root, project["media"]["original_audio"], "original audio")
    duration_ms = round(validate_inputs([audio])["media"]["duration_seconds"] * 1000)
    # Editors may round duration to whole seconds; timings must still fit the actual audio.
    tolerance_ms = 1000
    if "duration_ms" in metadata and abs(metadata["duration_ms"] - duration_ms) > tolerance_ms:
        raise ValueError("Lyrics duration does not match the project's audio. Check the song and recording version.")
    endpoints = [line["end_ms"] for line in lyrics["lines"]]
    endpoints.extend(word["end_ms"] for line in lyrics["lines"] for word in line.get("words", []))
    if max(endpoints) > duration_ms + tolerance_ms:
        raise ValueError("Lyrics timings extend beyond the project's audio. Correct the timings before importing.")


def import_lyrics(directory: Path, source: Path) -> dict:
    """Check song identity and audio bounds before replacing lyrics, keeping a backup."""
    root = directory.expanduser().resolve()
    project = load_job_document(root)
    target = resolve_job_asset(root, project["media"]["lyrics"], "lyrics")
    lyrics = load_lyrics_file(source)
    _validate_import(root, project, lyrics)
    content = dump_lyrics_file(lyrics).encode("utf-8")
    history = root / ".karaoke" / "lyrics-history"
    history.mkdir(parents=True, exist_ok=True)
    backup = history / f"{uuid.uuid4().hex}.yaml"
    shutil.copy2(target, backup)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return {"lyrics": str(target), "backup": str(backup)}


def export_project(directory: Path) -> dict:
    """Package current project inputs and edits, excluding renders and runtime diagnostics."""
    root = directory.expanduser().resolve()
    load_job_document(root)
    archive = root.with_name(f"{root.name}-editable-{uuid.uuid4().hex[:8]}.zip")
    excluded = {".runs", ".trash", "renders", "lyrics-history"}
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for path in sorted(root.rglob("*")):
                relative = path.relative_to(root)
                if excluded.intersection(relative.parts):
                    continue
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    raise ValueError(f"Cannot export linked project asset: {relative}")
                if path.is_file():
                    output.write(path, relative.as_posix())
    except BaseException:
        archive.unlink(missing_ok=True)
        raise
    return {"archive": str(archive)}
