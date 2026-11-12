import json
import subprocess
from unittest.mock import Mock

import pytest

from colab import karaoke_job
from karaoke_app import youtube_source


def test_cookie_retry_and_metadata_filter(tmp_path, monkeypatch):
    audio = tmp_path / "source.webm"
    audio.write_bytes(b"audio")
    audio.with_suffix(".info.json").write_text(json.dumps({"title": "Song", "http_headers": {"secret": "x"}}))
    responses = iter([
        subprocess.CompletedProcess([], 1, "", "sign in"),
        subprocess.CompletedProcess([], 0, "", ""),
    ])

    def stream(command, *, on_line, **kwargs):
        result = next(responses)
        if result.returncode == 0:
            on_line('KARAOKE_VIDEO {"title":"Song","uploader":"Channel","duration":120}\n')
            on_line('KARAOKE_DOWNLOAD {"downloaded_bytes":5,"total_bytes":5}\n')
            on_line('KARAOKE_FILE ' + json.dumps(str(audio)) + '\n')
        return result

    runner = Mock(side_effect=stream)
    monkeypatch.setattr(youtube_source.shutil, "which", lambda _: "/bin/deno")
    monkeypatch.setattr(youtube_source, "stream_process", runner)
    path, metadata = youtube_source.download_youtube("https://youtu.be/test", tmp_path, tmp_path / "cookies.txt")
    assert path == audio
    assert "http_headers" not in metadata
    assert "--cookies" not in runner.call_args_list[0].args[0]
    assert "--cookies" in runner.call_args_list[1].args[0]


def test_download_failure_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(youtube_source.shutil, "which", lambda _: "/bin/deno")
    runner = Mock(return_value=subprocess.CompletedProcess([], 1, "", "ERROR: Sign in to confirm you're not a bot"))
    monkeypatch.setattr(youtube_source, "stream_process", runner)
    with pytest.raises(RuntimeError, match="YouTube download failed.*Sign in"):
        youtube_source.download_youtube("https://youtu.be/test", tmp_path)


def test_uploaded_youtube_preserves_identity(tmp_path, monkeypatch):
    audio = tmp_path / "audio.webm"
    audio.touch()
    monkeypatch.setattr(karaoke_job, "_probe_duration", lambda _: 234)
    _, metadata = karaoke_job._acquire_source({
        "source": {"kind": "file", "value": str(audio), "metadata": {
            "title": "Artist - Song (Lyric Video)", "artist": "Artist", "track": "Song",
            "webpage_url": "https://youtu.be/test", "album": "Album",
        }}, "lyrics": {"title": "Override"},
    })
    assert metadata["title"] == "Override"
    assert metadata["artist"] == "Artist"
    assert metadata["source_url"] == "https://youtu.be/test"
    assert metadata["album"] == "Album"


def test_hosts():
    assert youtube_source.is_youtube_url("https://music.youtube.com/watch?v=test")
    assert youtube_source.is_youtube_url("https://youtu.be/test")
    assert not youtube_source.is_youtube_url("https://youtube.com.evil.example/test")


def test_metadata_template_handles_missing_artist_and_quotes():
    from yt_dlp import YoutubeDL

    with YoutubeDL({'quiet': True}) as downloader:
        result = downloader.evaluate_outtmpl('%(.{title,artist,uploader,duration})j', {
            'title': 'Song "name"', 'uploader': 'Channel', 'duration': 120, 'http_headers': {'secret': 'private'},
        })
    assert json.loads(result) == {'title': 'Song "name"', 'uploader': 'Channel', 'duration': 120}
