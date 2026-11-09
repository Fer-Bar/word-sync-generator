"""Read-only project summaries and preflight validation."""

import argparse
from pathlib import Path

from rich.console import Console

from karaoke_app.job_document import load_job_document
from karaoke_app.visual_config import show_appearance


def run_project_status(command: str, argv: list[str]) -> None:
    """Inspect a project without provisioning compute or changing its files."""
    from karaoke_app.cli import build_render_parser, render_colab

    if command == "validate":
        parser = build_render_parser()
        parser.prog = "karaoke validate"
        parser.description = "Validate project settings, required audio and timed lyrics without starting Colab."
        args = parser.parse_args(argv)
        args.dry_run = True
        render_colab(args)
        return
    parser = argparse.ArgumentParser(prog="karaoke status", description="Show saved settings and project files.")
    parser.add_argument("project", type=Path)
    root = parser.parse_args(argv).project.expanduser().resolve()
    document = load_job_document(root)
    console = Console()
    console.print(f"Project: {root}", markup=False)
    show_appearance(document, console=console)
    for label, relative in document["media"].items():
        path = (root / relative).resolve()
        exists = path.is_relative_to(root) and path.is_file()
        console.print(f"{label.replace('_', ' ').title()}: {'available' if exists else 'missing'}", markup=False)
    exports = sorted(path for path in (root / "renders").glob("*/*.mp4") if path.is_file())
    console.print(f"Video exports: {len(exports)}")
    for path in exports:
        console.print(f"  {path.relative_to(root)}", markup=False)
    console.print("Next: karaoke validate PROJECT, then karaoke render PROJECT.")
