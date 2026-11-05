import json

import pytest

from karaoke_app.migration import migrate_job


@pytest.fixture
def raw_job(tmp_path):
    document = {
        "schema_version": 1,
        "job_id": "old",
        "title": "Canción",
        "source": {"artist": "Artista", "source_url": "original-source"},
        "media": {
            "original_audio": "audio.wav",
            "instrumental_audio": "instrumental.wav",
            "vocals_audio": "vocals.wav",
            "lyrics": "lyrics.yaml",
        },
        "video": {"width": 1280, "height": 720, "fps": 24},
        "background": {"kind": "image", "path": "background.png", "overlay_opacity": 0.38},
        "watermark": {"enabled": False},
        "intro": {"enabled": True, "logo": "obsolete.png"},
    }
    path = tmp_path / "job.json"
    path.write_text(json.dumps(document, ensure_ascii=False))
    return path, document


def test_migration_is_atomic_and_idempotent(raw_job):
    path, original = raw_job
    assert migrate_job(path.parent)
    doc = json.loads(path.read_text())
    assert doc["schema_version"] == 2
    assert doc["background"]["kind"] == "cosmic"
    assert doc["background"]["color"] == "#1D4E89"
    assert doc["source"] == original["source"]
    assert doc["media"] == original["media"]
    assert doc["intro"] == {"enabled": True, "duration": 5}
    assert not (path.parent / "backups").exists()
    updated = path.read_bytes()
    assert not migrate_job(path.parent)
    assert path.read_bytes() == updated
    assert not (path.parent / "backups").exists()


def test_migration_preserves_custom_cosmic_and_disabled_flags(raw_job):
    path, doc = raw_job
    doc["background"] = {"kind": "cosmic", "color": "#123456", "seed": 23, "speed": 0.7}
    doc["intro"] = {"enabled": False}
    path.write_text(json.dumps(doc))
    migrate_job(path.parent)
    result = json.loads(path.read_text())
    assert result["background"]["color"] == "#123456"
    assert result["background"]["seed"] == 23
    assert result["background"]["speed"] == 0.7
    assert result["intro"] == {"enabled": False}
    assert not result["watermark"]["enabled"]


def test_migration_dry_run_does_not_write(raw_job):
    path, _ = raw_job
    before = path.read_bytes()
    assert migrate_job(path.parent, dry_run=True)
    assert path.read_bytes() == before
    assert not (path.parent / "backups").exists()


def test_keep_static_background_option(raw_job):
    path, _ = raw_job
    migrate_job(path.parent, theme="job")
    assert json.loads(path.read_text())["background"]["kind"] == "image"


def test_missing_logo_does_not_partially_rewrite_job(raw_job):
    path, doc = raw_job
    doc["watermark"] = {"enabled": True, "path": "missing.png"}
    path.write_text(json.dumps(doc))
    before = path.read_bytes()
    with pytest.raises(FileNotFoundError):
        migrate_job(path.parent)
    assert path.read_bytes() == before
    assert not (path.parent / "backups").exists()
