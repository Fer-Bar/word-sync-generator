"""Remove superseded renders while retaining the latest video of each mode."""

import re
import shutil
from pathlib import Path

_RENDER_NAME = re.compile(r"\d{8}-\d{6}-(?:both|lyrics|karaoke)")


def obsolete_renders(job_dir: Path) -> list[Path]:
    """Select old render directories only when a newer video covers every mode."""
    renders = job_dir / "renders"
    if not renders.is_dir():
        return []
    covered = set()
    obsolete = []
    for directory in sorted(renders.iterdir(), reverse=True):
        if directory.is_symlink() or not directory.is_dir() or not _RENDER_NAME.fullmatch(directory.name):
            continue
        modes = {
            mode for mode in ("karaoke", "lyrics")
            if any(p.is_file() and p.stat().st_size > 0 for p in directory.glob(f"*_{mode}.mp4"))
        }
        if modes and modes <= covered:
            obsolete.append(directory)
        covered.update(modes)
    return obsolete


def prune_renders(job_dir: Path) -> None:
    """Delete superseded renders after a successful render has been downloaded."""
    for directory in obsolete_renders(job_dir):
        shutil.rmtree(directory)
