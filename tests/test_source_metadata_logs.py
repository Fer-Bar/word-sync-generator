import json
import logging
from types import SimpleNamespace

import pytest

from colab import karaoke_job as job


@pytest.mark.parametrize("overrides", [{}, {"title": "Song", "artist": "Artist"}])
@pytest.mark.parametrize("video_title", ["Unstructured video title", "Artist - Song (Official Audio)"])
def test_missing_youtube_metadata_is_explained(tmp_path, monkeypatch, caplog, overrides, video_title):
    audio = tmp_path / "source.webm"
    audio.touch()
    monkeypatch.setattr(job, "WORK_DIR", tmp_path)
    monkeypatch.setattr(job, "_ensure_deno", lambda: None)
    monkeypatch.setattr(job, "_yt_dlp_base", lambda config: ["yt-dlp"])

    def download(*args, **kwargs):
        (tmp_path / "source.info.json").write_text(json.dumps({
            "title": video_title, "uploader": "Channel", "duration": 120,
        }))
        return SimpleNamespace(stdout=f"{audio}\n", stderr="")

    monkeypatch.setattr(job, "_run", download)
    with caplog.at_level(logging.INFO):
        _, metadata = job._acquire_source({
            "source": {"kind": "url", "value": "https://www.youtube.com/watch?v=example"}, "lyrics": overrides,
        })
    assert "YouTube metadata:" in caplog.text
    assert "uploader='Channel'" in caplog.text
    resolved = bool(overrides) or video_title.startswith("Artist -")
    assert ("Song name unavailable" in caplog.text) == (not resolved)
    assert ("Artist unavailable" in caplog.text) == (not resolved)
    assert metadata["artist"] == ("Artist" if resolved else None)
    assert metadata["track"] == ("Song" if resolved else video_title)
    assert metadata["title"] == metadata["track"]
    assert metadata["video_title"] == video_title
