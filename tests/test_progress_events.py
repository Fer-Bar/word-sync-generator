"""Progress describes outcomes instead of exposing provider attempts and diagnostics."""

import json
import logging

import pytest

from colab import karaoke_job as job
from karaoke_app.cli import _report_lyrics_review


def events(caplog):
    return [record.user_event for record in caplog.records if hasattr(record, 'user_event')]


@pytest.mark.parametrize('reference_source', ['genius', 'txt', 'lrclib'])
def test_reference_recovery_has_no_premature_whisper_or_warning(monkeypatch, caplog, reference_source):
    def fail(*args):
        raise job.LyricsProviderUnavailable('provider is down')

    monkeypatch.setattr(job, '_fetch_lrclib', fail)
    monkeypatch.setattr(job, '_resolve_reference', lambda *args: ({'lines': [{}]}, {'source': reference_source}))
    with caplog.at_level(logging.DEBUG):
        job._prepare_reference({}, {'lyrics': {}}, None)
    messages = [e.get('message', '') for e in events(caplog)]
    assert messages == [f'Lyrics found: {reference_source.upper()} · 1 lines']
    assert not any(e['kind'] == 'warning' for e in events(caplog))


def test_whisper_only_after_reference_sources_are_exhausted(monkeypatch, caplog):
    monkeypatch.setattr(job, '_fetch_lrclib', lambda *args: None)
    monkeypatch.setattr(job, '_resolve_reference', lambda *args: (None, {'source': 'whisper'}))
    with caplog.at_level(logging.INFO):
        job._prepare_reference({}, {'lyrics': {}}, None)
    assert [e['message'] for e in events(caplog)] == ['No usable lyric reference. Using speech transcription.']


def test_review_summary_reflects_final_state(tmp_path, caplog):
    path = tmp_path / 'lyrics_validation.json'
    path.write_text(json.dumps({'needs_review': True, 'lines': [{'needs_review': True}, {'needs_review': False}]}))
    with caplog.at_level(logging.INFO):
        _report_lyrics_review(tmp_path)
    assert '1 flagged line' in caplog.text
    assert str(path) in caplog.text
    caplog.clear()
    path.write_text(json.dumps({'needs_review': False, 'lines': []}))
    _report_lyrics_review(tmp_path)
    assert not caplog.records


def test_remote_handler_serializes_only_semantic_events(capsys):
    handler = job.EventHandler()
    record = logging.LogRecord('remote', logging.INFO, '', 0, 'Running ffmpeg', (), None)
    handler.emit(record)
    assert capsys.readouterr().out == ''
    record.user_event = {'kind': 'stage', 'id': 'render', 'label': 'Rendering lyrics video'}
    handler.emit(record)
    line = capsys.readouterr().out
    assert json.loads(line.removeprefix('KARAOKE_EVENT ')) == {'version': 1, **record.user_event}


def test_stage_failure_does_not_report_completion(caplog):
    def fail():
        raise ValueError('alignment failed')

    with caplog.at_level(logging.INFO), pytest.raises(ValueError):
        job._timed_call({'stages': []}, 'ctc_alignment', fail)
    assert [e.get('state', 'running') for e in events(caplog)] == ['running', 'stopped']


def test_ffmpeg_progress_measures_real_encode(tmp_path, caplog):
    import imageio_ffmpeg

    output = tmp_path / 'encoded.mp4'
    with caplog.at_level(logging.INFO):
        job._encode_progress([imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-f', 'lavfi', '-i',
                              'color=s=64x64:r=10:d=1', '-c:v', 'libx264', str(output)], 1)
    progress = [e for e in events(caplog) if e.get('id') == 'encoding']
    assert output.stat().st_size > 0
    assert progress[0]['reset']
    assert any(0 < e.get('completed', 0) <= 1 for e in progress[1:])
    assert progress[-1]['state'] == 'done'


def test_failed_ffmpeg_never_reports_done(tmp_path, caplog):
    import subprocess

    import imageio_ffmpeg

    with caplog.at_level(logging.INFO), pytest.raises(subprocess.CalledProcessError):
        job._encode_progress([imageio_ffmpeg.get_ffmpeg_exe(), '-i', str(tmp_path / 'missing.wav'),
                              str(tmp_path / 'output.mp4')], 1)
    assert all(e.get('state') != 'done' for e in events(caplog))


def test_notebook_logging_streams_stages_before_render_finishes(tmp_path):
    import sys
    import time
    from pathlib import Path

    from karaoke_app.terminal import stream_process

    config = tmp_path / 'config.json'
    config.write_text('{"operation":"render"}')
    program = f'''
import logging, sys, time
from pathlib import Path
sys.path.insert(0, {str(Path(job.__file__).parent)!r})
import karaoke_job as job
logging.basicConfig(level=logging.WARNING)
job.CONFIG_PATH = Path({str(config)!r})
job.WORK_DIR = Path({str(tmp_path / 'work')!r})
job._require_commands = lambda *args: None

def render(config):
    job._event("Generating background", stage="background")
    logging.getLogger("uploaded_background").info("Frames", extra={{"user_event": {{
        "kind": "stage", "id": "background_frames", "label": "Drawing background frames",
        "completed": 1, "total": 10}}}})
    time.sleep(.3)
    job._event("Rendering karaoke video", stage="render_karaoke")
    time.sleep(.3)

job._render_existing_job = render
job.main()
'''
    received = []

    def collect(line):
        if line.startswith('KARAOKE_EVENT '):
            received.append((time.monotonic(), json.loads(line.removeprefix('KARAOKE_EVENT '))))

    result = stream_process([sys.executable, '-I', '-c', program], timeout=5, on_line=collect)
    ended = time.monotonic()
    assert result.returncode == 0, result.stderr
    assert [event['label'] for _, event in received] == [
        'Preparing runtime', 'Generating background', 'Drawing background frames', 'Rendering karaoke video',
    ]
    assert ended - received[0][0] >= .5
    assert received[2][1]['completed'] == 1


def test_runtime_progress_reinitialization_keeps_host_handlers_and_emits_once():
    import subprocess
    import sys
    from pathlib import Path

    program = f'''
import logging, sys
sys.path.insert(0, {str(Path(job.__file__).parent)!r})
import karaoke_job as job
logging.basicConfig(level=logging.WARNING)
host_handlers = list(logging.getLogger().handlers)
job.configure_runtime_logging()
job.configure_runtime_logging()
assert all(handler in logging.getLogger().handlers for handler in host_handlers)
job._event("Generating background", stage="background")
'''
    result = subprocess.run([sys.executable, '-I', '-c', program], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stdout.count('KARAOKE_EVENT ') == 1


def test_slow_frames_report_progress_before_a_second_of_video(monkeypatch, caplog):
    import io
    import itertools
    from unittest.mock import Mock

    from karaoke_app import browser_lyrics

    elapsed = itertools.count()
    monkeypatch.setattr(browser_lyrics.time, 'perf_counter', lambda: next(elapsed))
    page = Mock()
    page.screenshot.return_value = b'frame'
    with caplog.at_level(logging.INFO):
        browser_lyrics._write_browser_frames(page, {'fps': 24, 'mode': 'karaoke', 'groups': []},
                                             io.BytesIO(), duration=.125)
    progress = [event for event in events(caplog) if event.get('id') == 'frames']
    assert [event['completed'] for event in progress] == [1, 2, 3]
    assert progress[1]['detail'] == '2/3 frames'
    assert progress[-1]['state'] == 'done'
