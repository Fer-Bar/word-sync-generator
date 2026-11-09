"""Exercise cleanup through the real CLI and filesystem, using disposable exports."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
OLD = "20260101-000000-both"
NEW = "20260102-000000-lyrics-abcdef012345"


def make_render(root, name):
    directory = root / "renders" / name
    (directory / "subtitles").mkdir(parents=True)
    (directory / "Song_lyrics.mp4").write_bytes(b"synthetic export " + name.encode())
    (directory / "subtitles" / "Song.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
    (directory / "render-settings.json").write_text('{"theme": "chosen variant"}\n')
    return directory


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def cleanup(root, *args, leading_args=(), package_root=REPO):
    env = {**os.environ, "PYTHONPATH": str(package_root / "src"), "NO_COLOR": "1",
           "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-c", "from karaoke_app.cli import main; raise SystemExit(main())",
                           *leading_args, "cleanup", str(root), *args],
                          cwd=root, env=env, text=True, capture_output=True, timeout=30)


def succeeded(result):
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout + result.stderr


@pytest.mark.parametrize("leading_args", [(), ("--verbose",)], ids=["normal", "leading-verbose"])
def test_preview_preserves_project_and_actual_package_log_root(tmp_path, leading_args):
    """A different cwd must not hide writes to the imported package's log root."""
    package_root = tmp_path / "application"
    shutil.copytree(REPO / "src", package_root / "src", ignore=shutil.ignore_patterns("__pycache__"))
    project = tmp_path / "project"
    make_render(project, OLD)
    before = files(tmp_path)

    output = succeeded(cleanup(project, leading_args=leading_args, package_root=package_root))

    assert OLD in output
    assert "Preview only" in output
    assert "1 export(s)" in output
    assert files(tmp_path) == before
    assert not (package_root / ".karaoke").exists()
    assert not (project / ".trash").exists()


def test_inventory_and_preview_are_read_only_then_selected_export_round_trips(tmp_path):
    old = make_render(tmp_path, OLD)
    make_render(tmp_path, NEW)
    make_render(tmp_path, "favorites")
    (tmp_path / "original.flac").write_bytes(b"original media")
    before = files(tmp_path)
    old_files = files(old)
    new_files = files(tmp_path / "renders" / NEW)

    inventory = succeeded(cleanup(tmp_path))
    assert OLD in inventory and NEW in inventory
    preview = succeeded(cleanup(tmp_path, OLD))
    assert "Preview only" in preview
    assert f"{sum(map(len, old_files.values())):,} bytes" in preview
    assert files(tmp_path) == before
    assert not (tmp_path / ".trash").exists()

    succeeded(cleanup(tmp_path, OLD, "--apply"))
    trash = tmp_path / ".trash" / "renders" / OLD
    assert not old.exists()
    assert files(trash) == old_files
    assert files(tmp_path / "renders" / NEW) == new_files
    assert (tmp_path / "renders" / "favorites").is_dir()
    assert (tmp_path / "original.flac").read_bytes() == b"original media"
    assert OLD in succeeded(cleanup(tmp_path, "--restore"))
    succeeded(cleanup(tmp_path, OLD, "--restore", "--dry-run"))
    assert not old.exists()
    assert files(trash) == old_files
    succeeded(cleanup(tmp_path, OLD, "--restore", "--apply"))
    assert files(tmp_path) == before
    assert not trash.exists()


@pytest.mark.parametrize("ids", [[], ["../" + OLD], [OLD, "../" + NEW], ["favorites"], [OLD, OLD]])
def test_apply_requires_explicit_valid_unique_ids_and_changes_nothing_on_invalid_selection(tmp_path, ids):
    make_render(tmp_path, OLD)
    make_render(tmp_path, NEW)
    make_render(tmp_path, "favorites")
    before = files(tmp_path)
    result = cleanup(tmp_path, *ids, "--apply")
    assert result.returncode != 0
    assert files(tmp_path) == before
    assert not (tmp_path / ".trash").exists()


def test_restore_conflict_keeps_entire_selection_in_trash(tmp_path):
    make_render(tmp_path, OLD)
    make_render(tmp_path, NEW)
    succeeded(cleanup(tmp_path, OLD, NEW, "--apply"))
    replacement = make_render(tmp_path, NEW)
    (replacement / "do-not-overwrite.txt").write_text("new creative work")
    before = files(tmp_path)
    result = cleanup(tmp_path, OLD, NEW, "--restore", "--apply")
    assert result.returncode != 0
    assert "Refusing to overwrite" in result.stderr
    assert files(tmp_path) == before
    assert not (tmp_path / "renders" / OLD).exists()


def test_trash_collision_refuses_every_move_before_applying_selection(tmp_path):
    make_render(tmp_path, OLD)
    make_render(tmp_path, NEW)
    occupied = tmp_path / ".trash" / "renders" / NEW
    occupied.mkdir(parents=True)
    (occupied / "kept.txt").write_text("previously discarded variant")
    before = files(tmp_path)
    result = cleanup(tmp_path, OLD, NEW, "--apply")
    assert result.returncode != 0
    assert files(tmp_path) == before
    assert (tmp_path / "renders" / OLD).exists()


@pytest.mark.parametrize("link_location", ["renders", ".trash", ".trash/renders", f"renders/{OLD}",
                                           f"renders/{OLD}/linked", f".trash/renders/{OLD}"])
def test_symlinks_cannot_redirect_cleanup_outside_project(tmp_path, link_location):
    root = tmp_path / "project"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("external work")
    root.mkdir()
    link = root / link_location
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)
    if link_location != "renders" and not (root / "renders" / OLD).exists():
        make_render(root, OLD)
    result = cleanup(root, OLD, "--apply")
    assert result.returncode != 0
    assert (outside / "keep.txt").read_text() == "external work"
    if link_location != "renders":
        assert (root / "renders" / OLD).exists()
    assert link.is_symlink()


def test_dangling_target_symlink_is_not_replaced(tmp_path):
    old = make_render(tmp_path, OLD)
    target = tmp_path / ".trash" / "renders" / OLD
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "missing", target_is_directory=True)
    before = files(old)
    result = cleanup(tmp_path, OLD, "--apply")
    assert result.returncode != 0
    assert target.is_symlink()
    assert files(old) == before
