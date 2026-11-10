"""Read-only upload validation through the notebook engine's public JSON command."""

import hashlib
import json
import os
import subprocess
import sys
import wave
from pathlib import Path

import imageio_ffmpeg
import pytest


def invoke(paths, tmp_path):
    request, result = tmp_path / "request.json", tmp_path / "result.json"
    request.write_text(json.dumps({"paths": [str(path) for path in paths]}))
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths if path.is_file()}
    process = subprocess.run(
        [sys.executable, "-m", "karaoke_app.notebook_runner", "validate-input",
         "--request", str(request), "--result", str(result)], capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}, timeout=40,
    )
    assert before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths if path.is_file()}
    return process, result


@pytest.fixture
def audio(tmp_path):
    path = tmp_path / "song.wav"
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0\0" * 16000)
    return path


@pytest.mark.parametrize("with_lyrics", [False, True])
def test_validate_uploaded_audio_and_optional_reference(audio, tmp_path, with_lyrics):
    paths = [audio]
    if with_lyrics:
        lyrics = tmp_path / "reference.txt"
        lyrics.write_text("A supplied lyric line\n", encoding="utf-8")
        paths.append(lyrics)
    process, result = invoke(paths, tmp_path)
    assert (process.returncode, process.stdout, process.stderr) == (0, "", "")
    output = json.loads(result.read_text())
    assert output["source"] == str(audio)
    assert output["lyrics_text"] == (str(lyrics) if with_lyrics else None)
    assert output["media"]["duration_seconds"] == pytest.approx(1)
    assert output["media"]["format"] == "wav"
    assert output["media"]["audio_codec"] == "pcm_s16le"
    assert output["media"]["has_video"] is False


@pytest.mark.parametrize("kind", [
    "cancelled", "multiple", "multiple-txt", "unsupported", "empty", "corrupt", "empty-txt", "invalid-txt",
])
def test_invalid_upload_does_not_produce_a_result(audio, tmp_path, kind):
    paths = [audio]
    if kind == "cancelled":
        paths = []
    elif kind == "multiple":
        second = tmp_path / "second.wav"
        second.write_bytes(audio.read_bytes())
        paths.append(second)
    elif kind == "unsupported":
        extra = tmp_path / "document.pdf"
        extra.write_bytes(b"not media")
        paths.append(extra)
    elif kind == "multiple-txt":
        for name in ("first.txt", "second.txt"):
            lyrics = tmp_path / name
            lyrics.write_text("A supplied lyric line")
            paths.append(lyrics)
    elif kind in {"empty-txt", "invalid-txt"}:
        lyrics = tmp_path / "empty.txt"
        lyrics.write_bytes(b"" if kind == "empty-txt" else b"\xff\xff")
        paths.append(lyrics)
    else:
        audio.write_bytes(b"" if kind == "empty" else b"not an audio file")
    process, result = invoke(paths, tmp_path)
    assert process.returncode == 1
    assert process.stdout == ""
    assert not result.exists()
    assert "ValueError" in process.stderr


@pytest.mark.parametrize("with_audio", [False, True])
def test_video_requires_an_audio_stream(tmp_path, with_audio):
    path = tmp_path / "video.mp4"
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i", "color=s=64x64:d=1"]
    if with_audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "aac"]
    subprocess.run([*command, "-c:v", "libx264", "-t", "1", str(path)], check=True, capture_output=True)
    process, result = invoke([path], tmp_path)
    if with_audio:
        assert (process.returncode, process.stdout, process.stderr) == (0, "", "")
        output = json.loads(result.read_text())
        assert output["media"]["has_video"] is True
        assert output["media"]["audio_codec"] == "aac"
    else:
        assert process.returncode == 1
        assert "audio stream" in process.stderr
        assert not result.exists()
