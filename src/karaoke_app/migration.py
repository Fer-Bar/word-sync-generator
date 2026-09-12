"""Idempotent upgrades of prepared job configuration, with recoverable backups."""

import argparse
import hashlib
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from karaoke_app.branding import store_shared_logo
from karaoke_app.job_document import resolve_watermark_path, validate_job_document
from karaoke_app.themes import DEFAULT_THEME, THEMES, apply_render_theme

LOGGER = logging.getLogger(__name__)


def migrated_document(
    job_dir: Path, raw: dict[str, Any], *, theme: str = "auto", dry_run: bool = False
) -> dict[str, Any]:
    """Normalize a job while preserving custom cosmic settings and explicit disabled flags."""
    document = validate_job_document(raw)
    selected = "job" if theme == "auto" and document["background"]["kind"] == "cosmic" else theme
    document, _ = apply_render_theme(document, DEFAULT_THEME if selected == "auto" else selected)
    watermark = document["watermark"]
    if watermark.get("enabled"):
        logo = resolve_watermark_path(job_dir, watermark.get("path"))
        watermark["path"] = store_shared_logo(logo, dry_run=dry_run)
    intro = document.setdefault("intro", {"enabled": True})
    intro.pop("logo", None)
    if intro.get("enabled", True):
        intro.setdefault("duration", 5.0)
    return validate_job_document(document)


def migrate_job(job_dir: Path, *, theme: str = "auto", dry_run: bool = False) -> bool:
    """Back up and atomically replace an outdated job.json; return whether it changes."""
    root = job_dir.expanduser().resolve()
    path = root / "job.json"
    original = path.read_bytes()
    raw = json.loads(original)
    document = migrated_document(root, raw, theme=theme, dry_run=dry_run)
    if document == raw:
        return False
    if dry_run:
        return True
    backup = root / "backups" / f"job-{hashlib.sha256(original).hexdigest()[:12]}.json"
    backup.parent.mkdir(exist_ok=True)
    if backup.exists() and backup.read_bytes() != original:
        raise ValueError(f"Backup collision: {backup}")
    backup.write_bytes(original)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=root, suffix=".json", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(document, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    LOGGER.info("Updated %s (backup: %s)", path, backup)
    return True


def run_migration(argv: list[str]) -> None:
    """Upgrade one job or the immediate prepared jobs under an outputs directory."""
    parser = argparse.ArgumentParser(prog="karaoke migrate", description=__doc__)
    parser.add_argument("path", type=Path, help="Job directory, job.json, or directory containing prepared jobs")
    parser.add_argument(
        "--theme",
        choices=("auto", *THEMES, "job"),
        default="auto",
        help="auto preserves cosmic jobs and upgrades static jobs to aurora; job preserves all backgrounds",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing files")
    args = parser.parse_args(argv)
    root = args.path.expanduser().resolve()
    if root.is_file() and root.name == "job.json":
        jobs = [root.parent]
    elif (root / "job.json").is_file():
        jobs = [root]
    else:
        jobs = [path.parent for path in sorted(root.glob("*/job.json"))]
    if not jobs:
        raise ValueError(f"No prepared jobs found in {root}")
    changed = 0
    errors = []
    for job in jobs:
        try:
            result = migrate_job(job, theme=args.theme, dry_run=args.dry_run)
            changed += result
            if args.dry_run or not result:
                LOGGER.info("%s: %s", job.name, "needs migration" if result else "up to date")
        except (OSError, ValueError) as error:
            errors.append(f"{job.name}: {error}")
    LOGGER.info("%s: %s/%s jobs", "Would update" if args.dry_run else "Updated", changed, len(jobs))
    if errors:
        raise ValueError("Jobs not migrated: " + "; ".join(errors))
