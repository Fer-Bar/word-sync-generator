"""FOMO compositions keep arbitrary titles, branding and video colors within bounds."""

import json

import pytest
from PIL import Image

from karaoke_app.fomo import apply_graphic_options, title_rows
from karaoke_app.job_document import load_job_document
from karaoke_app.render_graphics import generate_render_graphics
from karaoke_app.thumbnail import create_title_overlay, run_thumbnail
from karaoke_app.visual_config import configure_job


@pytest.mark.parametrize("title", ["A", "FEAR OF MISSING OUT", "W" * 200,
                                   "A much longer song title with many more words than the album name", "ONE\nTWO"])
@pytest.mark.parametrize("layout", ["stacked", "wide"])
@pytest.mark.parametrize("align", ["start", "center", "end"])
def test_titles_fit_without_losing_words(title, layout, align):
    rows = title_rows(title, layout)
    assert " ".join(rows) == " ".join(title.upper().split())
    overlay = create_title_overlay(title, "DRAKE", graphic_style="fomo", title_layout=layout,
                                   align=align, size=(1280, 720))
    x0, y0, x1, y1 = overlay.getbbox()
    assert 70 <= x0 < x1 <= 1210
    assert 75 <= y0 < y1 <= 590
    assert overlay.getpixel((0, 0))[3] == 0


def test_saved_fomo_produces_matching_intro_background_and_thumbnail(tmp_path):
    document = {"schema_version": 2, "title": "A long song title", "source": {"artist": "Drake"},
                "video": {"width": 1280, "height": 720, "fps": 24},
                "background": {"kind": "solid", "color": "#123456"}, "watermark": {"enabled": False},
                "media": {"original_audio": "a.wav", "instrumental_audio": "i.wav",
                          "vocals_audio": "v.wav", "lyrics": "lyrics.yaml"}}
    (tmp_path / "job.json").write_text(json.dumps(document))
    configure_job(tmp_path, graphic_style="fomo", title_layout="wide", align="end")
    saved = load_job_document(tmp_path)
    assert saved["background"] == {"kind": "solid", "color": "#FFFFFF"}
    assert saved["style"]["lyrics_colors"]["active"] == "#111111"
    assert apply_graphic_options(saved) == saved
    destination = tmp_path / "graphics"
    timing = generate_render_graphics(tmp_path, saved, ("lyrics",), destination,
                                     {"segments": [{"words": [{"start": 4}]}]})
    assert timing["end"] == 3.2
    with Image.open(destination / "intro/intro_lyrics.png") as overlay:
        with Image.open(destination / "background.png") as background:
            composed = Image.alpha_composite(background.convert("RGBA"), overlay).convert("RGB")
        with Image.open(destination / "thumbnails/thumbnail_lyrics.png") as thumbnail:
            assert composed.tobytes() == thumbnail.tobytes()
    run_thumbnail([str(tmp_path), "--mode", "lyrics", "--no-logo"])
    with Image.open(tmp_path / "thumbnails/thumbnail_lyrics.png") as thumbnail:
        assert thumbnail.getpixel((0, 0)) == (255, 255, 255)


@pytest.mark.parametrize("title", [" ", "one\n\ntwo", "1\n2\n3\n4\n5", "a" * 201])
def test_invalid_fomo_titles_fail(title):
    with pytest.raises(ValueError):
        title_rows(title, "stacked")


@pytest.mark.parametrize("graphic_style", ["fomo", "fomo-xerox"])
def test_fomo_bundle_contains_white_background_and_monochrome_watermark(tmp_path, graphic_style):
    import io
    import zipfile

    from karaoke_app.cli import _create_render_bundle

    logo = tmp_path / "logo.png"
    Image.new("RGBA", (90, 30), (250, 240, 210, 255)).save(logo)
    (tmp_path / "audio.wav").write_bytes(b"placeholder audio")
    document = apply_graphic_options({
        "title": "Song", "source": {"artist": "Drake"},
        "video": {"width": 1280, "height": 720, "fps": 24},
        "style": {"lyrics_effect": "classic"},
        "background": {"kind": "solid", "color": "#123456"},
        "watermark": {"enabled": True, "path": str(logo), "position": "top_left"},
        "media": {"original_audio": "audio.wav", "instrumental_audio": "audio.wav"},
    }, graphic_style=graphic_style)
    bundle = tmp_path / "bundle.zip"
    _create_render_bundle(tmp_path, document, "lyrics", {"lyrics": "ASS"}, bundle,
                          transcript={"segments": [{"words": [{"start": 5}]}]})
    with zipfile.ZipFile(bundle) as archive:
        saved = json.loads(archive.read("job.json"))
        if graphic_style == "fomo-xerox":
            assert saved["background"]["kind"] == "image"
            assert saved["background"]["path"] == "graphics/background.png"
            with Image.open(io.BytesIO(archive.read(saved["background"]["path"]))) as paper:
                assert paper.convert("L").getextrema()[0] < 240
        else:
            assert saved["background"]["color"] == "#FFFFFF"
        assert saved["watermark"]["position"] == "bottom_left"
        with Image.open(io.BytesIO(archive.read(saved["watermark"]["path"]))) as image:
            r, g, b, a = image.getpixel((0, 0))
            assert r == g == b < 50
            assert a == 255
        assert "graphics/intro/intro_lyrics.png" in archive.namelist()


def test_xerox_is_repeatable_and_preserves_transparent_intro_margins():
    import numpy as np

    from karaoke_app.fomo import fomo_paper

    arguments = {"size": (1280, 720), "align": "center"}
    clean = create_title_overlay("FEAR OF MISSING OUT", "DRAKE", graphic_style="fomo", **arguments)
    textured = create_title_overlay("FEAR OF MISSING OUT", "DRAKE", graphic_style="fomo-xerox", **arguments)
    again = create_title_overlay("FEAR OF MISSING OUT", "DRAKE", graphic_style="fomo-xerox", **arguments)
    assert textured.tobytes() == again.tobytes()
    assert textured.tobytes() != clean.tobytes()
    assert textured.getpixel((0, 0))[3] == 0
    ink = np.array(textured.getchannel("A"))
    original = np.array(clean.getchannel("A"))
    assert (ink[original > 250] > 100).mean() > .9
    paper = fomo_paper((1280, 720), xerox=True)
    assert paper.tobytes() == fomo_paper((1280, 720), xerox=True).tobytes()
    pixels = np.array(paper)
    assert np.array_equal(pixels[:, :, 0], pixels[:, :, 1])
    assert pixels.std() > 2
    assert pixels.mean() > 245


def test_fomo_dark_palette_inversion():
    import numpy as np

    from karaoke_app.fomo import fomo_paper

    paper_clean = fomo_paper((1280, 720), xerox=False, palette="dark")
    assert paper_clean.getpixel((0, 0)) == (0, 0, 0)

    paper_xerox = fomo_paper((1280, 720), xerox=True, palette="dark")
    pixels = np.array(paper_xerox)
    assert np.array_equal(pixels[:, :, 0], pixels[:, :, 1])
    assert pixels.mean() < 15
    assert pixels.std() > 2

    clean = create_title_overlay("FEAR OF MISSING OUT", "DRAKE", graphic_style="fomo",
                                 graphic_palette="dark", size=(1280, 720), align="center")
    textured = create_title_overlay("FEAR OF MISSING OUT", "DRAKE", graphic_style="fomo-xerox",
                                    graphic_palette="dark", size=(1280, 720), align="center")
    clean_pix = np.array(clean)
    textured_pix = np.array(textured)
    assert clean_pix[clean_pix[:, :, 3] > 200][:, :3].mean() > 235
    assert textured_pix[textured_pix[:, :, 3] > 200][:, :3].mean() > 230
