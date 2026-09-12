"""Reusable branding assets stored once in the project's logos directory."""

import hashlib
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGOS = PROJECT_ROOT / "logos"
THUMBNAIL_LOGO = LOGOS / "thumbnail.png"


def store_shared_logo(path: Path, *, dry_run: bool = False) -> str:
    """Return a project-relative path, deduplicating external logos by content."""
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Logo not found: {path}")
    if path.is_relative_to(LOGOS.resolve()):
        return path.relative_to(PROJECT_ROOT).as_posix()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    for candidate in sorted(LOGOS.glob(f"*{path.suffix.lower()}")):
        if hashlib.sha256(candidate.read_bytes()).hexdigest() == digest:
            return candidate.relative_to(PROJECT_ROOT).as_posix()
    destination = LOGOS / f"{path.stem}-{digest[:12]}{path.suffix.lower()}"
    if not dry_run:
        LOGOS.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    return destination.relative_to(PROJECT_ROOT).as_posix()
