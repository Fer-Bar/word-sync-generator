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
    assert "render_background" not in preparation_visuals(VIDEO, args)
    args.background_style = "fluid"
    with pytest.raises(ValueError, match="Choose"):
        preparation_visuals(VIDEO, args)


def test_background_override_preserves_custom_typography():
    document = {"video": VIDEO, "style": {"font_family": "Custom", "font_size": 99},
                "background": {"kind": "solid", "color": "#000000"}}
    result = apply_visual_options(document, background_style="fluid")
    assert result["style"] == document["style"]
    assert document["background"]["kind"] == "solid"


def test_configure_is_persistent_idempotent_and_backed_up(tmp_path):
    document = {"schema_version": 2, "title": "Test", "video": VIDEO,
        "background": {"kind": "solid", "color": "#000000"}, "watermark": {"enabled": False},
        "media": {"original_audio": "a.wav", "instrumental_audio": "i.wav",
                  "vocals_audio": "v.wav", "lyrics": "lyrics.yaml"}}
    original = json.dumps(document).encode()
    (tmp_path / "job.json").write_bytes(original)
    configure_job(tmp_path, background_style="cosmic-sand")
    saved = load_job_document(tmp_path)
    assert saved["style"]["lyrics_effect"] == "word-synced"
    assert saved["background"]["appearance"] == "cosmic"
    assert next((tmp_path / "backups").iterdir()).read_bytes() == original
    configure_job(tmp_path, background_style="cosmic-sand")
    assert len(list((tmp_path / "backups").iterdir())) == 1
    assert apply_visual_options(saved) == saved
