import io
import json
import logging
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest
from rich.console import Console

from karaoke_app import terminal
from karaoke_app.cli import build_parser, build_render_parser
from karaoke_app.terminal import ProgressHandler, configure_logging, redact, remote_event, run_process, stream_process


def test_help_groups_and_compatible_arguments():
    parser = build_render_parser()
    assert 'Appearance' in parser.format_help()
    assert parser.parse_args(['job', '--background-style', 'fluid']).background_style == 'fluid'
    assert build_parser().parse_args(['song.wav', '--verbose']).verbose


def test_failure_is_one_contextual_error(monkeypatch, caplog):
    result = subprocess.CompletedProcess([], 1, '', 'raw ffmpeg')
    monkeypatch.setattr(terminal, 'stream_process', Mock(return_value=result))
    with pytest.raises(RuntimeError, match='Uploading project failed'):
        run_process(['colab', '--auth=oauth2', 'upload'])
    assert 'raw ffmpeg' not in caplog.text
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


def test_streaming_fragmented_events_and_large_stderr():
    lines = []
    program = '''import sys, time
sys.stdout.write('KARAOKE_'); sys.stdout.flush()
time.sleep(.05)
sys.stdout.write('EVENT {"version":1,"kind":"message","message":"Ready"}\\n'); sys.stdout.flush()
for i in range(5000):
    sys.stderr.write('technical detail ' * 30 + '\\n')
sys.stderr.flush()
'''
    result = stream_process([sys.executable, '-c', program], timeout=5, on_line=lines.append)
    assert result.returncode == 0
    events = [line for line in lines if line.startswith('KARAOKE_EVENT ')]
    assert len(events) == 1 and json.loads(events[0].removeprefix('KARAOKE_EVENT '))['message'] == 'Ready'
    assert len(result.stderr.splitlines()) == 200
    assert len(lines) == 5001


def test_stream_is_delivered_before_process_finishes():
    began = time.monotonic()
    arrivals = []
    result = stream_process([sys.executable, '-c', 'import time; print("ready", flush=True); time.sleep(.3)'],
                            timeout=3, on_line=lambda line: arrivals.append(time.monotonic() - began))
    assert result.returncode == 0
    assert arrivals[0] < time.monotonic() - began - .15


def test_timeout_and_callback_cancellation_stop_children(tmp_path):
    marker = tmp_path / 'should-not-exist'
    program = ('import time; from pathlib import Path; print("ready", flush=True); '
               f'time.sleep(1); Path({str(marker)!r}).touch()')
    with pytest.raises(subprocess.TimeoutExpired):
        stream_process([sys.executable, '-c', program], timeout=.1)

    def cancel(line):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        stream_process([sys.executable, '-c', program], on_line=cancel)
    assert not marker.exists()


def test_oauth_prompt_without_newline_is_forwarded():
    lines = []
    stream_process([sys.executable, '-c',
                    'import sys,time; sys.stdout.write("Enter the authorization code: "); '
                    'sys.stdout.flush(); time.sleep(.1)'], on_line=lines.append)
    assert lines == ['Enter the authorization code: ']


def test_plain_output_is_semantic_and_deduplicated():
    output = io.StringIO()
    presenter = ProgressHandler(Console(file=output, width=120, force_terminal=False))
    logger = logging.getLogger('karaoke_app.test_output')
    logger.addHandler(presenter)
    logger.setLevel(logging.DEBUG)
    try:
        logger.debug('LRCLIB candidates / ffmpeg command')
        for completed in range(101):
            logger.info('internal label', extra={'user_event': {
                'kind': 'stage', 'id': 'download', 'label': 'Downloading audio', 'total': 100, 'completed': completed,
            }})
        for _ in range(2):
            logger.info('metadata', extra={'user_event': {'kind': 'metadata', 'values': {'Video': '[red]Song'}}})
        logger.info('metadata', extra={'user_event': {'kind': 'metadata', 'values': {'Artist': 'Artist'}}})
    finally:
        logger.removeHandler(presenter)
        presenter.close()
    text = output.getvalue()
    assert text.count('Downloading audio') == 1
    assert text.count('Video: [red]Song') == 1
    assert 'Artist: Artist' in text
    assert 'LRCLIB' not in text and 'ffmpeg' not in text and '\x1b' not in text


def test_remote_noise_is_not_user_output(caplog):
    with caplog.at_level(logging.INFO):
        remote_event('Running ffmpeg -y ...\n')
        remote_event('KARAOKE_EVENT invalid\n')
        remote_event('KARAOKE_EVENT []\n')
        event = {'version': 1, 'kind': 'message', 'message': 'Lyrics found: GENIUS'}
        remote_event('KARAOKE_EVENT ' + json.dumps(event))
    events = [record.user_event for record in caplog.records if hasattr(record, 'user_event')]
    assert events == [{'version': 1, 'kind': 'message', 'message': 'Lyrics found: GENIUS'}]


def test_redacted_diagnostic_file(tmp_path):
    root = logging.getLogger()
    old_handlers, old_level = root.handlers[:], root.level
    root.handlers = []
    try:
        path = configure_logging(log_dir=tmp_path)
        logging.getLogger('karaoke_app.test').debug('token=private Authorization: Bearer secret hf_abc123')
        for handler in root.handlers:
            handler.flush()
        text = path.read_text()
        assert 'private' not in text and 'Bearer secret' not in text and 'hf_abc123' not in text
        assert path.stat().st_mode & 0o777 == 0o600
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers, root.level = old_handlers, old_level


def test_secrets_from_environment_are_redacted(monkeypatch):
    monkeypatch.setenv('GENIUS_ACCESS_TOKEN', 'some-arbitrary-secret-value')
    assert 'some-arbitrary-secret-value' not in redact('failed some-arbitrary-secret-value')


def test_rich_chained_exception_exposes_colab_cause():
    output = '''╭──── Traceback (most recent call last) ────╮
│ client.py:237 in assign                  │
╰─────────────────────────────────────────╯
ColabRequestError: Failed to issue request POST
https://colab.research.google.com/tun/m/assign?nbh=private&accelerator=
T4: Precondition Failed

During handling of the above exception, another exception occurred:
╭──── Traceback (most recent call last) ────╮
│ client.py:242 in assign                  │
╰─────────────────────────────────────────╯
TooManyAssignmentsError: Failed to issue request POST
https://colab.research.google.com/tun/m/assign?nbh=private&accelerator=
T4: Precondition Failed
'''
    result = subprocess.CompletedProcess([], 1, '', output)
    error = terminal.ProcessFailure('Connecting to Colab', result)
    assert 'TooManyAssignmentsError' in str(error)
    assert 'HTTP 412' in str(error) and 'Stop an unused Colab session' in str(error)
    assert 'client.py' not in str(error) and 'private' not in str(error)


@pytest.mark.parametrize(('output', 'expected'), [
    ('Traceback (most recent call last):\n  File "x.py", line 12\nValueError: Unsupported audio format',
     'ValueError: Unsupported audio format'),
    ('\x1b[31mPermissionError: Permission denied\x1b[0m', 'PermissionError: Permission denied'),
    ('ERROR: [youtube] Video unavailable', 'ERROR: [youtube] Video unavailable'),
    ('Error opening input file song.wav.', 'Error opening input file song.wav.'),
    ('', 'No error details were returned.'),
])
def test_failure_summary_handles_external_errors(output, expected):
    assert terminal.failure_summary(output) == expected


def test_failure_summary_redacts_secret():
    assert 'private' not in terminal.failure_summary('ValueError: token=private')


def test_retry_resets_unknown_progress_total():
    presenter = ProgressHandler(Console(file=io.StringIO(), force_terminal=True, force_interactive=True))
    try:
        presenter.event({'kind': 'stage', 'id': 'download', 'label': 'Downloading audio',
                         'total': 100, 'completed': 80})
        presenter.event({'kind': 'stage', 'id': 'download', 'label': 'Downloading audio', 'reset': True})
        task = presenter.progress.tasks[0]
        assert task.total is None and task.completed == 0
    finally:
        presenter.close()


def test_structured_remote_failure_takes_priority_over_wrapper_traceback():
    event = {'version': 1, 'kind': 'failure', 'message': 'Error opening input file: missing.wav'}
    output = 'KARAOKE_EVENT ' + json.dumps(event) + '\nCalledProcessError: Command ffmpeg exited with status 1\n'
    assert terminal.failure_summary(output) == event['message']


def test_no_color_keeps_progress_without_ansi_color(monkeypatch):
    monkeypatch.setenv('NO_COLOR', '1')
    console = Console(file=io.StringIO(), force_terminal=True, force_interactive=True, width=48, height=30, record=True)
    assert console.no_color
    presenter = ProgressHandler(console)
    presenter.event({'kind': 'message', 'message': 'Lyrics found: LRCLIB'})
    presenter.close()
    assert console.export_text() == 'Lyrics found: LRCLIB\n'


def test_colab_stages_replace_startup_and_report_silence_once(caplog):
    now = [0]
    progress = terminal.RemoteProgress('Starting pipeline on Colab', clock=lambda: now[0])
    with caplog.at_level(logging.INFO):
        now[0] = 60
        progress.check_silence()
        progress.check_silence()
        assert caplog.text.count('No stage reported yet') == 1
        event = {'version': 1, 'kind': 'stage', 'id': 'background', 'label': 'Generating background'}
        progress.feed('KARAOKE_EVENT ' + json.dumps(event))
        now[0] = 121
        progress.check_silence()
        progress.check_silence()
        assert caplog.text.count('Last reported stage: Generating background.') == 1
        progress.feed('KARAOKE_EVENT ' + json.dumps({**event, 'completed': 10, 'total': 100}))
        now[0] = 122
        progress.check_silence()
    stops = [record.user_event for record in caplog.records if hasattr(record, 'user_event')
             and record.user_event.get('id') == 'colab']
    assert len(stops) == 1 and stops[0]['state'] == 'stopped'
    assert progress.last_stage == 'Generating background'
    assert not progress.silence_reported


def test_silent_child_still_checks_for_progress_updates():
    ticks = []
    result = stream_process([sys.executable, '-c', 'import time; time.sleep(1.2)'], timeout=3,
                            on_tick=lambda: ticks.append(time.monotonic()))
    assert result.returncode == 0 and ticks


def test_colab_failure_names_last_reported_stage(monkeypatch):
    def fake_process(command, *, on_line, **kwargs):
        on_line('KARAOKE_EVENT ' + json.dumps({
            'version': 1, 'kind': 'stage', 'id': 'background', 'label': 'Generating background',
        }))
        return subprocess.CompletedProcess(command, 1, '', 'ValueError: Invalid dimensions')

    monkeypatch.setattr(terminal, 'stream_process', fake_process)
    with pytest.raises(terminal.ProcessFailure, match='Generating background failed'):
        run_process(['colab', '--auth=oauth2', 'exec'])


def test_colab_failure_is_not_attributed_to_a_completed_stage(monkeypatch):
    def fake_process(command, *, on_line, **kwargs):
        event = {'version': 1, 'kind': 'stage', 'id': 'background', 'label': 'Generating background'}
        on_line('KARAOKE_EVENT ' + json.dumps(event))
        on_line('KARAOKE_EVENT ' + json.dumps({**event, 'state': 'done'}))
        return subprocess.CompletedProcess(command, 1, '', 'FileNotFoundError: Missing audio')

    monkeypatch.setattr(terminal, 'stream_process', fake_process)
    with pytest.raises(terminal.ProcessFailure) as error:
        run_process(['colab', '--auth=oauth2', 'exec'])
    assert 'Generating background failed' not in str(error.value)
    assert 'Missing audio' in str(error.value)


def test_terminal_keeps_live_progress_and_only_one_completed_summary(monkeypatch):
    now = [0]
    console = Console(file=io.StringIO(), width=120, height=30, force_terminal=True, force_interactive=True)
    presenter = ProgressHandler(console, clock=lambda: now[0])
    presenter.progress.live.auto_refresh = False
    messages = []
    monkeypatch.setattr(presenter, 'message', messages.append)
    try:
        presenter.event({'kind': 'stage', 'id': 'background', 'label': 'Generating background'})
        now[0] = 60
        presenter.event({'kind': 'stage', 'id': 'background_frames', 'parent': 'background',
                         'label': 'Drawing background frames', 'completed': 240, 'total': 480,
                         'detail': '240/480 frames'})
        assert not messages
        task = next(task for task in presenter.progress.tasks if task.description == 'Drawing background frames')
        assert task.completed == 240 and task.fields['detail'] == '50% 240/480 frames'
        presenter.event({'kind': 'stage', 'id': 'background_frames', 'parent': 'background',
                         'label': 'Drawing background frames', 'state': 'done'})
        assert not messages
        presenter.event({'kind': 'stage', 'id': 'background', 'label': 'Generating background',
                         'state': 'done', 'elapsed': 125})
        assert messages == ['✓ Background ready · 2m 05s']
        assert not presenter.tasks
    finally:
        presenter.close()


def test_redirected_progress_shows_rate_limited_milestones():
    now = [0]
    output = io.StringIO()
    presenter = ProgressHandler(Console(file=output, force_terminal=False), clock=lambda: now[0])
    event = {'kind': 'stage', 'id': 'frames', 'label': 'Drawing frames', 'total': 100}
    presenter.event({**event, 'completed': 0})
    for seconds, completed in ((1, 25), (11, 25), (12, 50), (22, 50)):
        now[0] = seconds
        presenter.event({**event, 'completed': completed})
    presenter.event({**event, 'completed': 100, 'state': 'done'})
    text = output.getvalue()
    assert text.count('25%') == 1 and text.count('50%') == 1
    assert '✓ Drawing frames · 22s' in text
    assert ' · done' not in text and '\x1b' not in text


def test_stopped_stage_does_not_leave_success_summary(monkeypatch):
    presenter = ProgressHandler(Console(file=io.StringIO(), force_terminal=True, force_interactive=True))
    messages = []
    monkeypatch.setattr(presenter, 'message', messages.append)
    try:
        presenter.event({'kind': 'stage', 'id': 'render', 'label': 'Rendering video'})
        presenter.event({'kind': 'stage', 'id': 'render', 'label': 'Rendering video', 'state': 'stopped'})
        assert messages == []
    finally:
        presenter.close()


def test_noninteractive_terminal_uses_plain_progress():
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, force_interactive=False)
    presenter = ProgressHandler(console)
    presenter.event({'kind': 'stage', 'id': 'background', 'label': 'Generating background'})
    assert 'Generating background' in output.getvalue()
    assert not presenter.started


def test_colab_ready_includes_connection_upload_and_startup(caplog, monkeypatch):
    now = [0]
    presenter = ProgressHandler(Console(file=io.StringIO(), force_terminal=True, force_interactive=True),
                                clock=lambda: now[0])
    messages = []
    monkeypatch.setattr(presenter, 'message', messages.append)
    terminal.LOGGER.addHandler(presenter)
    try:
        with caplog.at_level(logging.INFO):
            terminal.notify('Preparing Colab', stage='colab_setup')
            now[0] = 25
            progress = terminal.RemoteProgress('Starting pipeline on Colab', clock=lambda: now[0])
            now[0] = 30
            event = {'version': 1, 'kind': 'stage', 'id': 'runtime', 'parent': 'colab_setup',
                     'label': 'Preparing runtime'}
            progress.feed('KARAOKE_EVENT ' + json.dumps(event))
            now[0] = 30.002
            progress.feed('KARAOKE_EVENT ' + json.dumps({**event, 'label': 'Opening render project'}))
            now[0] = 30.003
            progress.feed('KARAOKE_EVENT ' + json.dumps({**event, 'state': 'done'}))
        assert messages == ['✓ Colab ready · 30s']
        assert not presenter.tasks
    finally:
        terminal.LOGGER.removeHandler(presenter)
        presenter.close()


@pytest.mark.parametrize(('visible_seconds', 'reported_seconds', 'expected'), [
    (.04, None, '<1s'),
    (19, .04, '19s'),
    (1.2, 125, '2m 05s'),
])
def test_completion_never_resets_visible_elapsed_to_zero(visible_seconds, reported_seconds, expected, monkeypatch):
    now = [0]
    presenter = ProgressHandler(Console(file=io.StringIO(), force_terminal=True, force_interactive=True),
                                clock=lambda: now[0])
    messages = []
    monkeypatch.setattr(presenter, 'message', messages.append)
    try:
        event = {'kind': 'stage', 'id': 'package', 'label': 'Packaging results'}
        presenter.event(event)
        now[0] = visible_seconds
        finish = {**event, 'state': 'done'}
        if reported_seconds is not None:
            finish['elapsed'] = reported_seconds
        presenter.event(finish)
        assert messages == [f'✓ Results packaged · {expected}']
    finally:
        presenter.close()


def test_unstarted_setup_completion_does_not_invent_a_duration(monkeypatch):
    presenter = ProgressHandler(Console(file=io.StringIO(), force_terminal=True, force_interactive=True))
    messages = []
    monkeypatch.setattr(presenter, 'message', messages.append)
    presenter.event({'kind': 'stage', 'id': 'colab_setup', 'label': 'Preparing Colab', 'state': 'done'})
    assert not messages and not presenter.started
