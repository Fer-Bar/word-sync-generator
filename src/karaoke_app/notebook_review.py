"""Apply reviewed lyrics and export the current editable notebook project."""

import shutil
import uuid
import zipfile
from pathlib import Path

from karaoke_app.job_document import load_job_document, resolve_job_asset
from karaoke_app.lyrics_file import dump_lyrics_file, load_lyrics_file


def import_lyrics(directory: Path, source: Path) -> dict:
    """Validate edited word timings before atomically replacing lyrics, keeping a backup."""
    root = directory.expanduser().resolve()
    project = load_job_document(root)
    target = resolve_job_asset(root, project["media"]["lyrics"], "lyrics")
    content = dump_lyrics_file(load_lyrics_file(source)).encode("utf-8")
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
