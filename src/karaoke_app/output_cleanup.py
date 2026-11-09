"""Explicit, reversible management of render exports. Never delete creative work."""

import argparse
import logging
import re
import stat
from dataclasses import dataclass
from pathlib import Path

LOGGER = logging.getLogger(__name__)
_RENDER_NAME = re.compile(r"\d{8}-\d{6}-(?:both|lyrics|karaoke)(?:-[0-9a-f]{12})?")


@dataclass(frozen=True)
class RenderExport:
    """One complete directory selected by the user, including its sidecar files."""

    path: Path
    size_bytes: int


def _directory(path: Path) -> bool:
    if path.is_symlink():
        raise ValueError(f"Symbolic links are not allowed in cleanup paths: {path}")
    if not path.exists():
        return False
    if not path.is_dir():
        raise ValueError(f"Expected a directory: {path}")
    return True


def _locations(job_dir: Path, *, restore: bool) -> tuple[Path, Path]:
    root = job_dir.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Project directory not found: {root}")
    renders = root / "renders"
    trash = root / ".trash" / "renders"
    for directory in (renders, trash.parent, trash):
        _directory(directory)
    return (trash, renders) if restore else (renders, trash)


def _export(path: Path) -> RenderExport:
    if not _RENDER_NAME.fullmatch(path.name):
        raise ValueError(f"Not a render ID: {path.name}")
    if not _directory(path):
        raise ValueError(f"Render not found: {path.name}")
    size = 0
    pending = [path]
    while pending:
        for child in pending.pop().iterdir():
            mode = child.lstat().st_mode
            if stat.S_ISDIR(mode):
                pending.append(child)
            elif stat.S_ISREG(mode):
                size += child.stat().st_size
            else:
                raise ValueError(f"Cleanup refuses symbolic links or special files: {child}")
    return RenderExport(path, size)


def plan_cleanup(job_dir: Path, render_ids: list[str], *, restore: bool = False) -> list[RenderExport]:
    """Inspect explicit exports, or list all exports, without changing any files."""
    source, destination = _locations(job_dir, restore=restore)
    if len(render_ids) != len(set(render_ids)):
        raise ValueError("Select each render ID only once")
    if render_ids:
        for name in render_ids:
            if not _RENDER_NAME.fullmatch(name):
                raise ValueError(f"Use a render ID from the inventory, not a path: {name}")
        exports = [_export(source / name) for name in render_ids]
        for export in exports:
            target = destination / export.path.name
            if target.exists() or target.is_symlink():
                raise FileExistsError(f"Refusing to overwrite an existing render: {target}")
        return exports
    if not source.exists():
        return []
    exports = []
    for path in sorted(source.iterdir()):
        if _RENDER_NAME.fullmatch(path.name):
            exports.append(_export(path))
    return exports


def move_renders(job_dir: Path, render_ids: list[str], *, restore: bool = False) -> list[Path]:
    """Move only named exports to local trash, or restore them without overwriting."""
    if not render_ids:
        raise ValueError("Choose explicit render IDs before using --apply")
    exports = plan_cleanup(job_dir, render_ids, restore=restore)
    _, destination = _locations(job_dir, restore=restore)
    destination.mkdir(parents=True, exist_ok=True)
    moved = []
    for export in exports:
        # Recheck immediately before each move. A failed move leaves its source intact.
        source, target_root = _locations(job_dir, restore=restore)
        _export(source / export.path.name)
        target = target_root / export.path.name
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Refusing to overwrite an existing render: {target}")
        export.path.rename(target)
        moved.append(target)
        LOGGER.info("%s: %s", "Restored" if restore else "Moved to local trash", target)
    return moved


def run_cleanup(argv: list[str]) -> None:
    """Preview a selection; move it to recoverable local trash only with --apply."""
    parser = argparse.ArgumentParser(
        prog="karaoke cleanup",
        description="Keep every render by default. Explicitly move selected exports to recoverable local trash.",
    )
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("render_ids", nargs="*", metavar="RENDER_ID", help="Exact IDs shown by the inventory")
    parser.add_argument("--restore", action="store_true", help="Inspect or restore exports from .trash/renders")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true", help="Move only the named exports; never permanently delete")
    action.add_argument("--dry-run", action="store_true", help="Preview only (the default)")
    args = parser.parse_args(argv)
    if args.apply and not args.render_ids:
        raise ValueError("Choose explicit render IDs before using --apply")
    exports = plan_cleanup(args.job_dir, args.render_ids, restore=args.restore)
    for export in exports:
        LOGGER.info("%s · %s bytes", export.path.name, f"{export.size_bytes:,}")
    LOGGER.info("%s export(s) · %s bytes", len(exports), f"{sum(item.size_bytes for item in exports):,}")
    if args.apply:
        move_renders(args.job_dir, args.render_ids, restore=args.restore)
    else:
        LOGGER.info("Preview only. Select render IDs and add --apply to %s.", "restore them" if args.restore else
                    "move them to .trash/renders")
    LOGGER.info("Local trash is recoverable and still occupies disk space. No files are permanently deleted.")
