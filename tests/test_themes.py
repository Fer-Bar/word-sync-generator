import copy

import pytest

from karaoke_app.cli import build_render_parser
from karaoke_app.themes import THEMES, apply_render_theme


def test_default_render_preserves_saved_background():
    original = {"background": {"kind": "image", "path": "old.png"}}
    before = copy.deepcopy(original)
    args = build_render_parser().parse_args(["job", "--mode", "both"])
    themed, chosen = apply_render_theme(original, args.theme, args.seed)
    assert chosen == "job"
    assert themed == original
    assert original == before


@pytest.mark.parametrize("theme", THEMES)
def test_named_palette_keeps_motion_settings(theme):
    original = {"background": {"kind": "cosmic", "speed": 0.7, "detail": 0.8, "seed": 31}}
    result, chosen = apply_render_theme(original, theme)
    assert chosen == theme
    assert {key: result["background"][key] for key in THEMES[theme]} == THEMES[theme]
    assert result["background"]["speed"] == 0.7
    assert result["background"]["detail"] == 0.8
    assert result["background"]["seed"] == 31


def test_random_theme_and_seed_are_resolved_once(monkeypatch):
    calls = []
    monkeypatch.setattr("karaoke_app.themes.secrets.choice", lambda names: calls.append(names) or "sunset")
    monkeypatch.setattr("karaoke_app.themes.secrets.randbelow", lambda upper: 125)
    result, chosen = apply_render_theme({"background": {"kind": "solid", "color": "#000000"}}, "random")
    assert len(calls) == 1
    assert chosen == "sunset"
    assert result["background"]["seed"] == 125
    assert result["background"]["color"] == "#B83B5E"
    repeated, _ = apply_render_theme({"background": {"kind": "solid"}}, chosen, 125)
    assert repeated == result


def test_job_option_preserves_custom_background():
    doc = {"background": {"kind": "image", "path": "bg.png", "overlay_opacity": 0.2}}
    assert apply_render_theme(doc, "job")[0] == doc
    with pytest.raises(ValueError, match="cosmic"):
        apply_render_theme(doc, "job", 5)


@pytest.mark.parametrize("seed", [-1, 2**32, True])
def test_invalid_seed(seed):
    with pytest.raises(ValueError, match="Seed"):
        apply_render_theme({"background": {"kind": "solid"}}, seed=seed)
