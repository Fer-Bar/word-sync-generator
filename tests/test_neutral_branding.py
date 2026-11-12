from pathlib import Path

import pytest
from PIL import Image

from karaoke_app.cli import build_parser
from karaoke_app.job_document import resolve_watermark_path
from karaoke_app.render_graphics import graphic_logo
from karaoke_app.thumbnail import create_thumbnail, run_thumbnail


def test_preparation_requires_explicit_logo_even_with_local_artwork():
    args = build_parser().parse_args(["song.wav"])
    assert args.logo is None
    assert build_parser().parse_args(["song.wav", "--logo", "custom.png"]).logo == Path("custom.png")


@pytest.mark.parametrize("watermark", [None, {}, {"enabled": False, "path": "missing.png"}])
def test_graphics_never_choose_an_implicit_logo(tmp_path, watermark):
    assert graphic_logo(tmp_path, {"watermark": watermark}) is None


def test_watermark_requires_explicit_selection(tmp_path):
    with pytest.raises(ValueError, match="watermark.path"):
        resolve_watermark_path(tmp_path)
    logo = tmp_path / "custom.png"
    Image.new("RGB", (32, 16), "red").save(logo)
    assert graphic_logo(tmp_path, {"watermark": {"enabled": True, "path": "custom.png"}}) == logo


def test_thumbnail_default_matches_explicit_no_logo(tmp_path):
    background = Image.new("RGB", (160, 90), "#183040")
    default = create_thumbnail("Song", "Artist", tmp_path / "default.png", background_path=background)
    neutral = create_thumbnail("Song", "Artist", tmp_path / "neutral.png", background_path=background, logo_path=None)
    assert default.read_bytes() == neutral.read_bytes()


@pytest.mark.parametrize("options,expected", [([], None), (["--logo", "custom.png"], Path("custom.png")),
                                          (["--logo", "custom.png", "--no-logo"], None)])
def test_thumbnail_cli_keeps_explicit_logo_controls(tmp_path, monkeypatch, options, expected):
    seen = []
    monkeypatch.setattr("karaoke_app.thumbnail.create_thumbnail", lambda *args, **kwargs: seen.append(kwargs))
    run_thumbnail(["--title", "Song", "--artist", "Artist", "--output-dir", str(tmp_path), *options])
    assert len(seen) == 2
    assert all(call["logo_path"] == expected for call in seen)
