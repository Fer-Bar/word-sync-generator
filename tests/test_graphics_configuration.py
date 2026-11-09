"""Standard graphics stay available after album-specific styles are removed."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from karaoke_app.job_document import STATE_FILENAME, load_job_document
from karaoke_app.visual_config import configure_job


@pytest.mark.parametrize("command", ["configure", "render", "intro", "thumbnail"])
@pytest.mark.parametrize("flag,value", [
    ("--graphic-style", "fomo"), ("--graphic-style", "fomo-xerox"),
    ("--graphic-palette", "light"), ("--title-layout", "wide"),
])
def test_removed_album_styles_fail_without_changing_project(prepared_project, command, flag, value):
    before = {p.relative_to(prepared_project): p.read_bytes() for p in prepared_project.rglob("*") if p.is_file()}
    arguments = [sys.executable, "-m", "karaoke_app.cli", command, str(prepared_project), flag, value]
    if command == "render":
        arguments.append("--dry-run")
    result = subprocess.run(
        arguments, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    assert result.returncode == 2
    assert ("invalid choice" if flag == "--graphic-style" else "unrecognized arguments") in result.stderr
    assert not result.stdout
    after = {p.relative_to(prepared_project): p.read_bytes() for p in prepared_project.rglob("*") if p.is_file()}
    assert after == before


@pytest.mark.parametrize("command", ["configure", "render", "intro", "thumbnail", "status", "validate"])
@pytest.mark.parametrize("key,value", [
    ("graphic_style", "fomo"), ("graphic_style", "fomo-xerox"),
    ("graphic_palette", "light"), ("title_layout", "wide"),
])
def test_saved_removed_settings_fail_without_rewriting_project(prepared_project, command, key, value):
    state = prepared_project / STATE_FILENAME
    document = json.loads(state.read_text())
    document.setdefault("intro", {})[key] = value
    state.write_text(json.dumps(document))
    before = {p.relative_to(prepared_project): p.read_bytes() for p in prepared_project.rglob("*") if p.is_file()}
    arguments = [sys.executable, "-m", "karaoke_app.cli", command, str(prepared_project)]
    if command in {"configure", "render"}:
        arguments.append("--dry-run")
    result = subprocess.run(
        arguments, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    assert result.returncode == 1
    message = "intro.graphic_style must be default" if key == "graphic_style" else f"intro has unknown keys: {key}"
    assert result.stderr.splitlines()[0] == message
    after = {p.relative_to(prepared_project): p.read_bytes() for p in prepared_project.rglob("*") if p.is_file()}
    assert after == before


def test_standard_alignment_preserves_saved_background_and_colors(prepared_project):
    configure_job(prepared_project, graphic_style="default", align="end", background_color="#123456",
                  lyrics_active_color="#00FF00", lyrics_inactive_color="#0000FF")
    saved = load_job_document(prepared_project)
    assert saved["intro"]["align"] == "end"
    assert saved["background"] == {"kind": "solid", "color": "#123456"}
    assert saved["style"]["lyrics_colors"] == {"active": "#00FF00", "inactive": "#0000FF"}
    before = (prepared_project / STATE_FILENAME).read_bytes()
    configure_job(prepared_project, graphic_style="default", align="end")
    assert (prepared_project / STATE_FILENAME).read_bytes() == before
