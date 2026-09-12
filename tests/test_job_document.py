import copy
import json
from pathlib import Path

import pytest

from karaoke_app import job_document
from karaoke_app.job_document import load_job_document, resolve_job_asset, resolve_watermark_path, validate_job_document


@pytest.fixture
def document():
    return {
        "schema_version": 2,
        "title": " Test Song ",
        "media": {
            "original_audio": "audio.flac", "vocals_audio": "vocals.flac",
            "instrumental_audio": "instrumental.flac", "lyrics": "lyrics.yaml",
        },
        "video": {"width": 1920, "height": 1080, "fps": 24},
        "background": {"kind": "image", "path": "background.png"},
    }


def test_v2_normalization_is_idempotent_and_does_not_mutate_input(document):
    original = copy.deepcopy(document)
    normalized = validate_job_document(document)
    assert document == original
    assert normalized["background"] == {"kind": "image", "path": "background.png", "overlay_opacity": 0}
    assert normalized["watermark"] == {"enabled": False}
    assert "overlay_opacity" not in normalized["style"]
    assert validate_job_document(normalized) == normalized


@pytest.mark.parametrize("opacity, expected", [(None, 0.38), (0, 0), (0.7, 0.7)])
def test_v1_migration_preserves_rendered_opacity_not_ignored_style(document, opacity, expected, tmp_path):
    document["schema_version"] = 1
    document["background"]["color"] = "0b1020"
    document["style"] = {"overlay_opacity": 0.92}
    if opacity is not None:
        document["background"]["overlay_opacity"] = opacity
    path = tmp_path / "job.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    original = path.read_bytes()
    normalized = load_job_document(tmp_path)
    assert path.read_bytes() == original
    assert normalized["schema_version"] == 2
    assert normalized["background"]["overlay_opacity"] == expected
    assert "color" not in normalized["background"]
    assert "overlay_opacity" not in normalized["style"]


@pytest.mark.parametrize("banner_exists", [True, False])
def test_v1_watermark_default_is_materialized_only_when_available(document, tmp_path, monkeypatch, banner_exists):
    monkeypatch.setattr(job_document, "PROJECT_ROOT", tmp_path)
    if banner_exists:
        (tmp_path / "logos").mkdir()
        (tmp_path / "logos/banner.png").write_bytes(b"image")
    document["schema_version"] = 1
    normalized = validate_job_document(document)
    assert normalized["watermark"]["enabled"] is banner_exists
    assert validate_job_document(normalized) == normalized
    document["watermark"] = {"enabled": False}
    assert validate_job_document(document)["watermark"] == {"enabled": False}


def test_extensible_provenance_and_two_state_lyrics_colors_are_retained(document):
    for key in ("source", "alignment", "metadata", "preparation"):
        document[key] = {"future": {"revision": [1, "custom"]}}
    document["lyrics_colors"] = {"inactive": "abcdef", "active": "123456"}
    normalized = validate_job_document(document)
    for key in ("source", "alignment", "metadata", "preparation"):
        assert normalized[key] == document[key]
        assert normalized[key] is not document[key]
    assert normalized["style"]["lyrics_colors"] == {"inactive": "#ABCDEF", "active": "#123456"}


@pytest.mark.parametrize("section", [None, "media", "video", "background", "style", "watermark", "intro"])
def test_unknown_configuration_keys_fail(document, section):
    target = document if section is None else document.setdefault(section, {})
    target["typo"] = True
    with pytest.raises(ValueError, match="unknown keys"):
        validate_job_document(document)


@pytest.mark.parametrize("section", ["media", "video", "background", "style", "watermark", "intro",
                                     "source", "alignment", "metadata", "preparation"])
def test_configuration_objects_do_not_silently_accept_null(document, section):
    document[section] = None
    with pytest.raises(ValueError, match="object"):
        validate_job_document(document)


@pytest.mark.parametrize("bad", [True, "0.5", None, -0.1, 1.1, float("nan"), float("inf")])
def test_image_opacity_is_strict(document, bad):
    document["background"]["overlay_opacity"] = bad
    with pytest.raises(ValueError, match="background.overlay_opacity"):
        validate_job_document(document)


@pytest.mark.parametrize("section, key, bad", [
    ("watermark", "enabled", "false"), ("watermark", "scale", True),
    ("watermark", "margin", float("nan")), ("watermark", "opacity", "0.5"),
    ("intro", "enabled", 1), ("intro", "start", -1), ("intro", "duration", 0),
    ("intro", "duration", float("inf")), ("intro", "title", 42), ("intro", "end", 0),
])
def test_watermark_and_intro_values_are_strict_even_when_disabled(document, section, key, bad):
    document[section] = {"enabled": False, key: bad}
    with pytest.raises(ValueError, match=f"{section}.{key}"):
        validate_job_document(document)


def test_intro_bundle_timing_survives_normalization(document):
    document["intro"] = {"enabled": True, "start": 1, "duration": 4, "end": 5, "logo": "logo.png"}
    assert validate_job_document(document)["intro"] == document["intro"]


def test_v2_style_opacity_is_not_durable_configuration(document):
    document["style"] = {"overlay_opacity": 0.3}
    with pytest.raises(ValueError, match="background.overlay_opacity"):
        validate_job_document(document)


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_solid_background_normalizes_without_irrelevant_opacity(document, version):
    document["schema_version"] = version
    document["background"] = {"kind": "solid", "color": "abcdef", "overlay_opacity": 0.5}
    normalized = validate_job_document(document)
    assert normalized["background"] == {"kind": "solid", "color": "#ABCDEF"}
    assert validate_job_document(normalized) == normalized


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_image_color_is_validated_but_not_retained(document, version):
    document["schema_version"] = version
    document["background"].update(color="#123456", overlay_opacity=0.55)
    normalized = validate_job_document(document)
    assert normalized["background"] == {"kind": "image", "path": "background.png", "overlay_opacity": 0.55}
    assert document["background"]["color"] == "#123456"
    assert validate_job_document(normalized) == normalized


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("bad", [None, True, "invalid", 123])
def test_legacy_image_color_must_still_be_valid(document, version, bad):
    document["schema_version"] = version
    document["background"]["color"] = bad
    with pytest.raises(ValueError, match="background.color"):
        validate_job_document(document)


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("bad", [None, True, "0.5", -0.1, 1.1, float("nan"), float("inf")])
def test_legacy_solid_opacity_must_still_be_valid(document, version, bad):
    document["schema_version"] = version
    document["background"] = {"kind": "solid", "color": "#123456", "overlay_opacity": bad}
    with pytest.raises(ValueError, match="background.overlay_opacity"):
        validate_job_document(document)


def test_explicit_missing_watermark_never_uses_available_default(tmp_path, monkeypatch):
    monkeypatch.setattr(job_document, "PROJECT_ROOT", tmp_path)
    (tmp_path / "logos").mkdir()
    banner = tmp_path / "logos/banner.png"
    banner.write_bytes(b"image")
    assert resolve_watermark_path(tmp_path) == banner
    for path in ("missing.png", str(tmp_path / "missing.png")):
        with pytest.raises(FileNotFoundError):
            resolve_watermark_path(tmp_path, path)
    assert resolve_watermark_path(Path("/unrelated"), str(banner)) == banner


def test_relative_asset_and_watermark_symlinks_cannot_escape_root(tmp_path, monkeypatch):
    job = tmp_path / "job"
    job.mkdir()
    external = tmp_path / "external.png"
    external.write_bytes(b"image")
    (job / "escape.png").symlink_to(external)
    monkeypatch.setattr(job_document, "PROJECT_ROOT", job)
    with pytest.raises(FileNotFoundError):
        resolve_job_asset(job, "escape.png", "background")
    with pytest.raises(FileNotFoundError):
        resolve_watermark_path(job, "escape.png")
    with pytest.raises(ValueError):
        resolve_watermark_path(job, "../external.png")
