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


def test_modes_keep_background_and_logo_with_distinct_layouts(tmp_path, assets):
    images = []
    for mode in ("lyrics", "karaoke"):
        path = create_thumbnail("ALRIGHT", "Ashes to Amber", tmp_path / f"{mode}.png", mode=mode, **assets)
        with Image.open(path) as result:
            assert result.mode == "RGB"
            assert result.size == (1280, 720)
            assert result.getpixel((1270, 10)) == (30, 40, 50)
            assert result.getpixel((50, 660)) == (255, 0, 0)
            images.append(np.array(result))
    assert not np.array_equal(images[0][:500], images[1][:500])
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



@pytest.mark.parametrize("title", ["Ángel", "A", "W" * 100, "A very long song title with many words", "First\nSecond"])
@pytest.mark.parametrize("artist", [None, "Jhené Aiko", "Artist " * 40])
def test_lyrics_overlay_preserves_transparent_edges(title, artist):
    from karaoke_app.thumbnail import create_title_overlay

    overlay = create_title_overlay(title, artist)
    alpha = np.asarray(overlay.getchannel("A"))
    assert alpha.max() == 255
    assert not alpha[0].any()
    assert not alpha[-1].any()
    assert not alpha[:, -1].any()
    ink_y, ink_x = np.where(alpha == 255)
    assert ink_x.min() >= round(SIZE[0] * .08)
    assert ink_x.max() <= round(SIZE[0] * .78)
    assert ink_y.min() > 0


def test_fonts_resolve_per_mode_and_lyrics_title_uses_uppercase():
    from karaoke_app.thumbnail import FONTS, create_title_overlay

    for mode, font in (("lyrics", "BarlowCondensed-BlackItalic.ttf"), ("karaoke", "Anton-Regular.ttf")):
        default = create_title_overlay("Song", "Artist", mode=mode)
        explicit = create_title_overlay("Song", "Artist", mode=mode, title_font=FONTS / font)
        assert default.tobytes() == explicit.tobytes()
    assert create_title_overlay("Song", None).tobytes() == create_title_overlay("SONG", None).tobytes()


@pytest.mark.parametrize("align", ["start", "center", "end"])
def test_video_job_thumbnail_matches_render_graphics(tmp_path, monkeypatch, align):
    import subprocess

    import imageio_ffmpeg

    from karaoke_app.render_graphics import generate_render_graphics

    source = tmp_path / "scene.png"
    picture = Image.new("RGB", (320, 180), (100, 150, 200))
    picture.paste((255, 0, 0), (280, 0, 320, 180))
    picture.save(source)
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-loop", "1", "-i", str(source),
                    "-t", "0.2", "-pix_fmt", "yuv420p", str(tmp_path / "scene.mp4")], check=True)
    document = {"title": "Scene", "source": {"artist": "Artist"},
                "video": {"width": 1672, "height": 941, "fps": 24},
                "background": {"kind": "video", "path": "scene.mp4", "crop_right": .15, "overlay_opacity": .25},
                "watermark": {"enabled": False}, "intro": {"align": align}}
    monkeypatch.setattr("karaoke_app.job_document.load_job_document", lambda _: document)
    run_thumbnail([str(tmp_path), "--mode", "lyrics", "--no-logo"])
    generate_render_graphics(tmp_path, document, ("lyrics",), tmp_path / "render", None)
    with Image.open(tmp_path / "thumbnails/thumbnail_lyrics.png") as standalone, Image.open(
        tmp_path / "render/thumbnails/thumbnail_lyrics.png"
    ) as automatic:
        assert standalone.tobytes() == automatic.tobytes()
        red, green, blue = standalone.getpixel((1270, 10))
        assert red < green < blue
        assert 140 < blue < 160


@pytest.mark.parametrize("align", ["start", "center", "end"])
def test_lyrics_alignment_moves_each_line_and_artist(align):
    from karaoke_app.thumbnail import create_title_overlay

    alpha = np.asarray(create_title_overlay("Like,\nWhatever", "Artist", align=align).getchannel("A"))
    rows = np.flatnonzero((alpha == 255).any(axis=1))
    groups = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
    assert len(groups) == 3
    for group in groups:
        columns = np.flatnonzero((alpha[group] == 255).any(axis=0))
        if align == "start":
            assert abs(columns.min() - round(SIZE[0] * .08)) <= 2
        elif align == "end":
            assert abs(columns.max() - (SIZE[0] - round(SIZE[0] * .08) - 1)) <= 2
        else:
            assert abs((columns.min() + columns.max()) / 2 - (SIZE[0] - 1) / 2) <= 1


def test_alignment_does_not_change_karaoke():
    from karaoke_app.thumbnail import create_title_overlay

    images = [create_title_overlay("Song", "Artist", mode="karaoke", align=a).tobytes()
              for a in ("start", "center", "end")]
    assert images[0] == images[1] == images[2]


def test_invalid_alignment_rejected():
    from karaoke_app.thumbnail import create_title_overlay

    with pytest.raises(ValueError, match="Align"):
        create_title_overlay("Song", "Artist", align="left")
