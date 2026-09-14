from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from karaoke_app import cli
from karaoke_app.thumbnail import SIZE, _title_mask, create_thumbnail, run_thumbnail


@pytest.fixture
def assets(tmp_path):
    background = tmp_path / "background.png"
    logo = tmp_path / "logo.png"
    Image.new("RGB", (160, 90), (30, 40, 50)).save(background)
    Image.new("RGBA", (100, 30), (255, 0, 0, 255)).save(logo)
    return {"background_path": background, "logo_path": logo}


def test_modes_keep_background_and_logo_and_change_only_label(tmp_path, assets):
    images = []
    for mode in ("lyrics", "karaoke"):
        path = create_thumbnail("ALRIGHT", "Ashes to Amber", tmp_path / f"{mode}.png", mode=mode, **assets)
        with Image.open(path) as result:
            assert result.mode == "RGB"
            assert result.size == (1280, 720)
            assert result.getpixel((1270, 10)) == (30, 40, 50)
            assert result.getpixel((50, 660)) == (255, 0, 0)
            images.append(np.array(result))
    assert np.array_equal(images[0][:500], images[1][:500])
    assert not np.array_equal(images[0][520:575], images[1][520:575])


@pytest.mark.parametrize("title", ["ÁNGEL", "A", "W" * 100, "A very long song title with many words", "FIRST\nSECOND"])
def test_title_stays_inside_layout(title):
    from karaoke_app.thumbnail import FONTS

    mask = _title_mask(title, FONTS / "Anton-Regular.ttf")
    assert 0 < mask.width <= 1100 < SIZE[0]
    assert mask.height == 344
    assert mask.getbbox() is not None


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": " "},
        {"artist": ""},
        {"mode": "invalid"},
        {"width": 641},
        {"width": True},
        {"title": "a" * 201},
        {"title": "first\n\nlast"},
    ],
)
def test_rejects_invalid_input(tmp_path, assets, overrides):
    kwargs = {"title": "Song", "artist": "Artist", "output_path": tmp_path / "result.png", **assets, **overrides}
    with pytest.raises(ValueError):
        create_thumbnail(**kwargs)
    assert not (tmp_path / "result.png").exists()


def test_source_cannot_be_overwritten(assets):
    with pytest.raises(ValueError, match="source asset"):
        create_thumbnail("Song", "Artist", assets["background_path"], **assets)


def test_cli_dispatch(monkeypatch):
    seen = []
    monkeypatch.setattr("karaoke_app.thumbnail.run_thumbnail", seen.append)
    monkeypatch.setattr("sys.argv", ["karaoke", "thumbnail", "--title", "Song"])
    assert cli.main() == 0
    assert seen == [["--title", "Song"]]


def test_job_metadata_and_overrides(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "karaoke_app.job_document.load_job_document",
        lambda _: {
            "title": "From job",
            "metadata": {"artist": "Job artist"},
        },
    )
    seen = []
    monkeypatch.setattr("karaoke_app.thumbnail.create_thumbnail", lambda *args, **kwargs: seen.append((args, kwargs)))
    run_thumbnail([str(tmp_path), "--title", "Override", "--no-logo"])
    assert [item[1]["mode"] for item in seen] == ["lyrics", "karaoke"]
    assert all(item[0][:2] == ("Override", "Job artist") for item in seen)
    assert seen[0][0][2] == Path(tmp_path) / "thumbnails" / "thumbnail_lyrics.png"
    assert seen[0][1]["logo_path"] is None


def test_create_thumbnail_with_in_memory_image(tmp_path, assets):
    mem_img = Image.new("RGB", (320, 180), (10, 20, 30))
    out = tmp_path / "result.png"
    result = create_thumbnail("Song", "Artist", out, background_path=mem_img, logo_path=assets["logo_path"])
    assert result.is_file()
    with Image.open(result) as img:
        assert img.size == (1280, 720)


def test_run_thumbnail_with_background_style(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr("karaoke_app.thumbnail.create_thumbnail", lambda *args, **kwargs: seen.append((args, kwargs)))
    run_thumbnail([
        "--title", "Cosmic Song", "--artist", "Artist",
        "--background-style", "cosmic-sand", "--output-dir", str(tmp_path),
    ])
    assert len(seen) == 2
    assert isinstance(seen[0][1]["background_path"], Image.Image)


def test_run_thumbnail_inherits_cosmic_background(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "karaoke_app.job_document.load_job_document",
        lambda _: {
            "title": "Cosmic Job",
            "metadata": {"artist": "Artist"},
            "background": {"kind": "cosmic", "appearance": "cosmic", "seed": 42},
            "video": {"width": 1280, "height": 720, "fps": 24},
        },
    )
    seen = []
    monkeypatch.setattr("karaoke_app.thumbnail.create_thumbnail", lambda *args, **kwargs: seen.append((args, kwargs)))
    run_thumbnail([str(tmp_path), "--mode", "lyrics"])
    assert len(seen) == 1
    assert isinstance(seen[0][1]["background_path"], Image.Image)

