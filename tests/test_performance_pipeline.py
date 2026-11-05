"""Performance changes must preserve frame timing, recovery, and model inputs."""

import io
import json
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from colab import karaoke_job as job
from karaoke_app import browser_lyrics as browser


def test_blank_frames_are_reused_without_dropping_timestamps():
    scene = {"fps": 10, "mode": "lyrics", "groups": [{"start": 1, "end": 1.2}]}
    page = MagicMock()
    page.screenshot.return_value = b"png"
    stream = io.BytesIO()
    metrics = {}
    browser._write_browser_frames(page, scene, stream, duration=2, metrics=metrics)
    assert stream.getvalue() == b"png" * 20
    assert metrics["frames"] == 20
    assert metrics["captured_frames"] == 10
    assert metrics["reused_blank_frames"] == 10
    assert [call.args[1] for call in page.evaluate.call_args_list] == [0, *[i / 10 for i in range(7, 16)]]


def test_empty_scene_and_nonzero_start_keep_frame_count():
    metrics = {}
    page = MagicMock()
    page.screenshot.return_value = b"blank"
    browser._write_browser_frames(page, {"fps": 24, "mode": "lyrics", "groups": []}, io.BytesIO(),
                                  duration=.11, start=12, metrics=metrics)
    assert metrics["frames"] == 3
    assert page.screenshot.call_count == 1
    assert page.evaluate.call_args.args[1] == 12


def test_source_acquisition_extracts_once_and_preserves_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(job, "WORK_DIR", tmp_path)
    monkeypatch.setattr(job, "_ensure_deno", lambda: None)
    audio = tmp_path / "source.webm"

    def run(command, **kwargs):
        assert "--write-info-json" in command
        assert "--cookies" in command
        audio.write_bytes(b"audio")
        (tmp_path / "source.info.json").write_text(json.dumps({
            "title": "Video title", "track": "Song", "artist": "Artist", "duration": 201,
            "webpage_url": "https://example.test/song"}))
        return subprocess.CompletedProcess(command, 0, stdout=f"{audio}\n", stderr="")

    cookies = tmp_path / "cookies.txt"
    cookies.write_text("test")
    with patch.object(job, "_run", side_effect=run) as execute:
        path, metadata = job._acquire_source({"source": {"kind": "url", "value": "https://example.test/song"},
                                             "cookies_path": str(cookies), "lyrics": {"title": "Override"}})
    assert execute.call_count == 1
    assert path == audio
    assert metadata["title"] == metadata["track"] == "Override"
    assert metadata["artist"] == "Artist"
    assert metadata["duration"] == 201


def test_reference_lookup_overlaps_demucs_and_failure_keeps_stems(tmp_path, monkeypatch):
    config = {"source": {}, "lyrics": {}, "demucs_model": "htdemucs_ft", "whisper_model": "large-v3",
              "language": "en", "archive_path": str(tmp_path / "result.zip")}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    for name in ("source.wav", "vocals.wav", "instrumental.wav"):
        (tmp_path / name).write_bytes(b"audio")
    monkeypatch.setattr(job, "CONFIG_PATH", config_path)
    monkeypatch.setattr(job, "WORK_DIR", tmp_path)
    monkeypatch.setattr(job, "_require_commands", lambda *args: None)
    monkeypatch.setattr(job, "_configure_huggingface", lambda: None)
    monkeypatch.setattr(job, "_acquire_source", lambda config: (tmp_path / "source.wav", {"title": "Song"}))
    monkeypatch.setattr(job, "_prepare_mixture", lambda path: path)
    lookup_started, separation_finished = threading.Event(), threading.Event()

    def lookup(*args):
        lookup_started.set()
        assert separation_finished.wait(3), "Reference lookup blocked the start of Demucs"
        return {"id": 42}, (None, {"source": "whisper"})

    def separate(*args):
        assert lookup_started.wait(3)
        separation_finished.set()
        return tmp_path / "vocals.wav", tmp_path / "instrumental.wav"

    def lyrics(*args, **kwargs):
        assert kwargs["selected_record"] == {"id": 42}
        assert kwargs["resolved_reference"] == (None, {"source": "whisper"})
        raise RuntimeError("alignment failed")

    monkeypatch.setattr(job, "_prepare_reference", lookup)
    monkeypatch.setattr(job, "_separate_vocals", separate)
    monkeypatch.setattr(job, "_prepare_lyrics", lyrics)
    monkeypatch.setattr(job, "_run", lambda command: Path(command[-1]).write_bytes(b"flac"))
    with patch.object(job, "_ensure_system_fonts") as fonts, patch.object(job, "_ensure_bebas_font") as bebas:
        with pytest.raises(job.LyricsPreparationError) as raised:
            job.main()
    fonts.assert_not_called()
    bebas.assert_not_called()
    with zipfile.ZipFile(raised.value.recovery_archive_path) as archive:
        assert {"vocals.flac", "instrumental.flac", "original_audio.wav", "checkpoint.json"} <= set(archive.namelist())
        assert json.loads(archive.read("checkpoint.json"))["preparation"]["lrclib_id"] == 42


def test_alignment_context_loads_once_and_retries_failed_loading():
    aligner, hf, torch = MagicMock(), MagicMock(), MagicMock()
    model, tokenizer, waveform = MagicMock(), object(), object()
    aligner.load_alignment_model.return_value = model, tokenizer
    aligner.load_audio.side_effect = [RuntimeError("decode failed"), waveform]
    with patch.dict(sys.modules, {"torch": torch, "ctc_forced_aligner": aligner, "huggingface_hub": hf}):
        context = job.AlignmentContext(Path("vocals.wav"))
        with pytest.raises(RuntimeError, match="decode failed"):
            context.load()
        first = context.load()
        assert context.load() is first
    assert first == (model, tokenizer, waveform)
    assert aligner.load_alignment_model.call_count == 2
    assert aligner.load_audio.call_count == 2


def test_streaming_encoder_failure_replays_from_start(tmp_path, monkeypatch):
    output = tmp_path / "video.mp4"
    attempts = []

    def frames(command, duration):
        attempts.append(command)
        assert duration == 3
        assert "image2pipe" in command and "pipe:0" in command
        if "h264_nvenc" in command:
            output.write_bytes(b"incomplete")
            raise subprocess.CalledProcessError(1, command)
        assert not output.exists()
        output.write_bytes(b"complete")

    monkeypatch.setattr(job, "_probe_duration", lambda path: 3)
    monkeypatch.setattr(job, "_nvenc_available", lambda: True)
    metrics = {}
    job._render_video(Path("audio.wav"), output, {
        "video": {"width": 320, "height": 180, "fps": 24},
        "background": {"kind": "solid", "value": "#000000"}, "lyrics_overlay": "pipe:0"},
        frame_writer=frames, metrics=metrics)
    assert len(attempts) == 2
    assert metrics == {"encoder": "libx264", "nvenc_fallback": True}
    assert output.read_bytes() == b"complete"


def test_streaming_error_removes_partial_output(tmp_path, monkeypatch):
    output = tmp_path / "video.mp4"

    def frames(*args):
        output.write_bytes(b"partial")
        raise RuntimeError("browser crashed")

    monkeypatch.setattr(job, "_probe_duration", lambda path: 3)
    monkeypatch.setattr(job, "_nvenc_available", lambda: False)
    with pytest.raises(RuntimeError, match="browser crashed"):
        job._render_video(Path("audio.wav"), output, {
            "video": {"width": 320, "height": 180, "fps": 24},
            "background": {"kind": "solid", "value": "#000000"}, "lyrics_overlay": "pipe:0"}, frame_writer=frames)
    assert not output.exists()


@pytest.mark.parametrize("mode", ["lyrics", "karaoke"])
def test_visibility_keeps_boundary_frames_and_karaoke_context(mode):
    scene = {"mode": mode, "groups": [{"start": 1, "end": 2}, {"start": 5, "end": 6}]}
    assert not browser.frame_has_lyrics(scene, .64)
    assert browser.frame_has_lyrics(scene, .65)
    assert browser.frame_has_lyrics(scene, 2.35)
    assert browser.frame_has_lyrics(scene, 3) is (mode == "karaoke")
    assert browser.frame_has_lyrics(scene, 4.65)
    assert browser.frame_has_lyrics(scene, 6.35)
    assert browser.frame_has_lyrics(scene, 6.85) is (mode == "karaoke")
    assert not browser.frame_has_lyrics(scene, 6.86)


def test_ctc_recovery_uses_same_job_context(tmp_path):
    lyrics = {"version": "1.0", "metadata": {"title": "Song", "language": "en", "duration_ms": 5000},
              "lines": [{"text": "Hello", "start_ms": 1000, "end_ms": 1500,
                         "words": [{"text": "Hello", "start_ms": 1000, "end_ms": 1500}]}]}
    reference = {"version": "1.0", "metadata": {"title": "Song"}, "lines": [{"text": "Hello"}]}
    transcript = {"transcription": {"language": "en"}, "segments": [{"words": [
        {"text": "Hello", "start": 1, "end": 1.5, "probability": .99}]}]}
    with patch.object(job, "_transcribe", return_value=transcript), \
         patch.object(job, "_align_known_lyrics", side_effect=[RuntimeError("collapse"), (lyrics, [])]) as align, \
         patch.object(job, "_check_vocal_boundaries", return_value={"status": "checked"}):
        job._prepare_lyrics(tmp_path / "vocals.wav", {"duration": 5}, {"language": "en"},
                            selected_record=None, resolved_reference=(reference, {"source": "txt"}))
    assert align.call_count == 2
    assert align.call_args_list[0].kwargs["context"] is align.call_args_list[1].kwargs["context"]
    assert align.call_args_list[1].kwargs["recovery_only"]


def test_browser_failure_kills_encoder_and_preserves_exception():
    process = MagicMock()
    process.poll.return_value = None
    with patch.object(browser, "browser_scene") as scene, \
         patch.object(browser.subprocess, "Popen", return_value=process):
        scene.return_value.__enter__.return_value.evaluate.side_effect = RuntimeError("capture failed")
        with pytest.raises(RuntimeError, match="capture failed"):
            browser._encode_browser_video_sync({"fps": 24, "mode": "lyrics", "groups": []}, Path("font"),
                                               ["ffmpeg"], duration=.1)
    process.kill.assert_called_once()
    process.wait.assert_called_once()
    process.stdin.close.assert_called_once()


def test_nvenc_probe_checks_encoding_not_encoder_listing():
    with patch.object(job, "_run", side_effect=subprocess.CalledProcessError(1, ["ffmpeg"])) as execute:
        assert not job._nvenc_available()
    command = execute.call_args.args[0]
    assert "-frames:v" in command
    assert command[command.index("-c:v") + 1] == "h264_nvenc"
