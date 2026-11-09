"""Render preparation is shared by frontends and never provisions a session."""

import pytest

from karaoke_app.rendering import prepare_render, render_subtitles


def test_render_preparation_validates_without_writes(prepared_project):
    before = {p.relative_to(prepared_project): p.read_bytes() for p in prepared_project.rglob("*") if p.is_file()}
    request = prepare_render(prepared_project, {"mode": "both", "align": "end"})
    assert request.root == prepared_project.resolve()
    assert request.mode == "both"
    assert request.document["intro"]["align"] == "end"
    subtitles = render_subtitles(request)
    assert set(subtitles.ass_by_mode) == {"lyrics", "karaoke"}
    assert all("[Events]" in text for text in subtitles.ass_by_mode.values())
    assert "-->" in subtitles.srt
    assert subtitles.transcript["segments"]
    after = {p.relative_to(prepared_project): p.read_bytes() for p in prepared_project.rglob("*") if p.is_file()}
    assert after == before


def test_render_preparation_rejects_missing_audio_without_writes(prepared_project):
    (prepared_project / "instrumental.wav").unlink()
    before = {p.relative_to(prepared_project): p.read_bytes() for p in prepared_project.rglob("*") if p.is_file()}
    with pytest.raises(FileNotFoundError, match="karaoke audio"):
        prepare_render(prepared_project, {"mode": "karaoke"})
    after = {p.relative_to(prepared_project): p.read_bytes() for p in prepared_project.rglob("*") if p.is_file()}
    assert after == before
