"""Persisted CLI preferences remain consistent from preparation through rendering."""

import json

import pytest

from karaoke_app.cli import build_parser, build_render_parser
from karaoke_app.job_document import load_job_document
from karaoke_app.visual_config import apply_visual_options, configure_job, preparation_visuals

VIDEO = {"width": 1280, "height": 720, "fps": 24}


def test_preparation_defaults_and_background_switches():
    args = build_parser().parse_args(["song.wav"])
    result = preparation_visuals(VIDEO, args)
    assert result["render_style"]["lyrics_effect"] == "word-synced"
    assert result["render_style"]["font_family"] == "Switzer Semibold"
    assert result["render_background"]["appearance"] == "fluid"
    args.background_style = "cosmic-sand"
    sand = preparation_visuals(VIDEO, args)
    assert sand["render_background"]["appearance"] == "cosmic"
    assert sand["render_background"]["detail"] > 0
    assert result["render_style"] == sand["render_style"]
    assert build_render_parser().parse_args(["job"]).theme == "job"


def test_explicit_static_background_is_preserved_and_conflicts_fail():
    args = build_parser().parse_args(["song.wav", "--background-color", "#123456"])
    assert preparation_visuals(VIDEO, args)["render_background"] == {"kind": "solid", "color": "#123456"}
    args.background_style = "fluid"
    with pytest.raises(ValueError, match="Choose"):
        preparation_visuals(VIDEO, args)


def test_background_override_preserves_custom_typography():
    document = {"video": VIDEO, "style": {"font_family": "Custom", "font_size": 99},
                "background": {"kind": "solid", "color": "#000000"}}
    result = apply_visual_options(document, background_style="fluid")
    assert result["style"] == document["style"]
    assert document["background"]["kind"] == "solid"


def test_configure_is_persistent_and_idempotent(tmp_path):
    document = {"schema_version": 2, "title": "Test", "video": VIDEO,
        "background": {"kind": "solid", "color": "#000000"}, "watermark": {"enabled": False},
        "media": {"original_audio": "a.wav", "instrumental_audio": "i.wav",
                  "vocals_audio": "v.wav", "lyrics": "lyrics.yaml"}}
    original = json.dumps(document).encode()
    (tmp_path / ".karaoke").mkdir(exist_ok=True)
    (tmp_path / ".karaoke/project.json").write_bytes(original)
    configure_job(tmp_path, background_style="cosmic-sand")
    saved = load_job_document(tmp_path)
    assert saved["style"]["lyrics_effect"] == "classic"
    assert saved["background"]["appearance"] == "cosmic"
    assert not (tmp_path / "backups").exists()
    configure_job(tmp_path, background_style="cosmic-sand")
    assert not (tmp_path / "backups").exists()
    assert apply_visual_options(saved) == saved


@pytest.fixture
def prepared_job(tmp_path):
    document = {"schema_version": 2, "title": "Test", "video": VIDEO,
                "background": {"kind": "solid", "color": "#123456"}, "watermark": {"enabled": False},
                "media": {"original_audio": "a.wav", "instrumental_audio": "i.wav",
                          "vocals_audio": "v.wav", "lyrics": "lyrics.yaml"}}
    (tmp_path / ".karaoke").mkdir(exist_ok=True)
    (tmp_path / ".karaoke/project.json").write_text(json.dumps(document))
    for name in ("a.wav", "i.wav", "v.wav"):
        (tmp_path / name).write_bytes(b"audio")
    (tmp_path / "lyrics.yaml").write_text(json.dumps({
        "version": "1.0", "metadata": {"title": "Test", "duration_ms": 2000},
        "lines": [{"text": "Hello", "start_ms": 0, "end_ms": 1000,
                   "words": [{"text": "Hello", "start_ms": 0, "end_ms": 1000}]}],
    }))
    return tmp_path


def test_dry_run_validates_without_writes_or_colab(prepared_job, monkeypatch):
    from karaoke_app import cli

    before = {p.relative_to(prepared_job).as_posix(): p.read_bytes() for p in prepared_job.rglob("*") if p.is_file()}

    def forbidden(*args, **kwargs):
        pytest.fail("Dry run must not start subprocesses, copy logos, or build bundles")

    monkeypatch.setattr(cli, "_validate_installation", forbidden)
    monkeypatch.setattr(cli, "_create_render_bundle", forbidden)
    monkeypatch.setattr(cli, "_run", forbidden)
    monkeypatch.setattr("karaoke_app.branding.store_shared_logo", forbidden)
    args = build_render_parser().parse_args([str(prepared_job), "--dry-run", "--background-style", "fluid"])
    cli.render_colab(args)
    after = {p.relative_to(prepared_job).as_posix(): p.read_bytes() for p in prepared_job.rglob("*") if p.is_file()}
    assert after == before
    (prepared_job / "a.wav").unlink()
    with pytest.raises(FileNotFoundError, match="lyrics audio"):
        cli.render_colab(args)


def test_omitted_options_preserve_custom_style_and_zero_opacity(prepared_job):
    from karaoke_app.visual_config import resolve_options

    document = load_job_document(prepared_job)
    document["style"]["font_size"] = 83
    (prepared_job / ".karaoke").mkdir(exist_ok=True)
    (prepared_job / ".karaoke/project.json").write_text(json.dumps(document))
    configure_job(prepared_job, background_style="fluid")
    resolved, _ = resolve_options(prepared_job, {"graphic_style": "default"})
    assert resolved["style"]["font_size"] == 83
    assert load_job_document(prepared_job)["style"]["font_size"] == 83


def test_interactive_non_tty_rejects_without_writes(prepared_job):
    import io

    from rich.console import Console

    from karaoke_app.visual_config import interactive_configuration

    original = (prepared_job / ".karaoke/project.json").read_bytes()
    with pytest.raises(ValueError, match="explicit flags"):
        interactive_configuration(prepared_job, {}, console=Console(file=io.StringIO(), force_terminal=False))
    assert (prepared_job / ".karaoke/project.json").read_bytes() == original


def test_atomic_save_failure_preserves_original(prepared_job, monkeypatch):
    from pathlib import Path

    from karaoke_app.visual_config import save_configuration

    original = (prepared_job / ".karaoke/project.json").read_bytes()
    document = load_job_document(prepared_job)
    document["background"]["color"] = "#ABCDEF"

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        save_configuration(prepared_job, document)
    assert (prepared_job / ".karaoke/project.json").read_bytes() == original
    assert len(list(prepared_job.iterdir())) == 5


def test_named_palette_survives_background_selection(prepared_job):
    from karaoke_app.themes import THEMES
    from karaoke_app.visual_config import resolve_options

    document, _ = resolve_options(prepared_job, {'background_style': 'fluid', 'theme': 'sunset'})
    assert document['background']['appearance'] == 'fluid'
    assert document['background']['color'] == THEMES['sunset']['color']


def test_watermark_zero_opacity_is_preserved(prepared_job):
    from PIL import Image

    from karaoke_app.visual_config import resolve_options

    logo = prepared_job / 'logo.png'
    Image.new('RGB', (16, 16)).save(logo)
    document, _ = resolve_options(prepared_job, {'logo': logo, 'logo_opacity': 0})
    assert document['watermark']['opacity'] == 0


@pytest.mark.parametrize('width', [48, 120])
def test_configuration_fits_terminal_and_preserves_literal_text(prepared_job, width):
    import io

    from rich.console import Console

    from karaoke_app.visual_config import show_appearance

    console = Console(file=io.StringIO(), record=True, width=width, height=30, force_terminal=True)
    document = load_job_document(prepared_job)
    document['background'] = {'kind': 'image', 'path': '[artwork].png'}
    show_appearance(document, before=document, console=console)
    text = console.export_text()
    assert all(len(line) <= width for line in text.splitlines())
    assert 'artwork' in text
