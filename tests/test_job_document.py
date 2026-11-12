import copy
from pathlib import Path

import pytest

from karaoke_app import job_document
from karaoke_app.job_document import resolve_job_asset, resolve_watermark_path, validate_job_document


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


@pytest.mark.parametrize("field,value", [("width", 1919), ("height", 1079), ("fps", 121)])
def test_video_settings_rejected_before_encoding(document, field, value):
    document["video"][field] = value
    with pytest.raises(ValueError, match=f"video.{field}"):
        validate_job_document(document)


def test_old_state_is_rejected_without_automatic_migration(document):
    document["schema_version"] = 1
    with pytest.raises(ValueError, match="Prepare a new project"):
        validate_job_document(document)


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


def test_solid_background_normalizes_without_irrelevant_opacity(document):
    document["background"] = {"kind": "solid", "color": "abcdef", "overlay_opacity": 0.5}
    normalized = validate_job_document(document)
    assert normalized["background"] == {"kind": "solid", "color": "#ABCDEF"}
    assert validate_job_document(normalized) == normalized


def test_image_color_is_validated_but_not_retained(document):
    document["background"].update(color="#123456", overlay_opacity=0.55)
    normalized = validate_job_document(document)
    assert normalized["background"] == {"kind": "image", "path": "background.png", "overlay_opacity": 0.55}
    assert document["background"]["color"] == "#123456"
    assert validate_job_document(normalized) == normalized


@pytest.mark.parametrize("bad", [None, True, "invalid", 123])
def test_image_color_must_still_be_valid(document, bad):
    document["background"]["color"] = bad
    with pytest.raises(ValueError, match="background.color"):
        validate_job_document(document)


@pytest.mark.parametrize("bad", [None, True, "0.5", -0.1, 1.1, float("nan"), float("inf")])
def test_solid_opacity_must_still_be_valid(document, bad):
    document["background"] = {"kind": "solid", "color": "#123456", "overlay_opacity": bad}
    with pytest.raises(ValueError, match="background.overlay_opacity"):
        validate_job_document(document)


def test_explicit_missing_watermark_never_uses_available_default(tmp_path, monkeypatch):
    monkeypatch.setattr(job_document, "PROJECT_ROOT", tmp_path)
    (tmp_path / "logos").mkdir()
    banner = tmp_path / "logos/banner.png"
    banner.write_bytes(b"image")
    with pytest.raises(ValueError, match="watermark.path"):
        resolve_watermark_path(tmp_path)
    assert resolve_watermark_path(tmp_path, "logos/banner.png") == banner
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


@pytest.mark.parametrize("align", ["start", "center", "end"])
def test_intro_alignment_survives_normalization(document, align):
    document["intro"] = {"align": align}
    result = validate_job_document(document)
    assert result["intro"]["align"] == align
    assert validate_job_document(result) == result


@pytest.mark.parametrize("align", ["left", "", None, [], True])
def test_invalid_intro_alignment(document, align):
    document["intro"] = {"align": align}
    with pytest.raises(ValueError, match="intro.align"):
        validate_job_document(document)
