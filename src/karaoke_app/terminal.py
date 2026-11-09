"""User-facing progress, streamed subprocess output, and private diagnostics."""

import codecs
import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Column
from rich.text import Text

from karaoke_app.resources import PROJECT_ROOT

LOGGER = logging.getLogger(__name__)
EVENT_PREFIX = "KARAOKE_EVENT "


def redact(text: str) -> str:
    """Remove common credentials from diagnostics and public error messages."""
    text = re.sub(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?|(?:[\w-]*(?:token|password|secret|cookie)[\w-]*)"
                  r"[\"']?\s*[:=]\s*[\"']?)[^\s,;\"']+", r"\1[REDACTED]", text)
    for name, value in os.environ.items():
        if len(value) >= 8 and any(word in name.lower() for word in ("token", "secret", "password", "api_key")):
            text = text.replace(value, "[REDACTED]")
    text = re.sub(r"\b(?:hf_[A-Za-z0-9]+|gh[pousr]_[A-Za-z0-9]+)\b", "[REDACTED]", text)
    return re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", text)


class DiagnosticFormatter(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))


class ProgressHandler(logging.Handler):
    """Render semantic events; diagnostics never determine the progress state."""

    def __init__(self, console=None, *, clock=time.monotonic):
        super().__init__()
        self.console = console or Console(stderr=True)
        bar = BarColumn(bar_width=8 if self.console.width < 72 else 40, style="bright_black",
                        complete_style="cyan", finished_style="green", pulse_style="cyan")
        if self.console.width < 72:
            columns = (TextColumn("{task.description}\n{task.fields[detail]}",
                                  table_column=Column(max_width=max(12, self.console.width - 18))),
                       bar, TimeElapsedColumn())
        else:
            columns = (SpinnerColumn(style="cyan"), TextColumn("{task.description}"), bar,
                       TextColumn("{task.fields[detail]}"), TimeElapsedColumn())
        self.progress = Progress(*columns, console=self.console, transient=True,
                                 disable=not self.console.is_interactive)
        self.tasks = {}
        self.clock = clock
        self.began = {}
        self.milestones = {}
        self.labels = {}
        self.metadata = {}
        self.warnings = set()
        self.last_message = None
        self.started = False

    def emit(self, record):
        event = getattr(record, "user_event", None)
        if event is not None:
            self.event(event)
        elif record.name.startswith("karaoke_app") and record.levelno >= logging.INFO:
            self.message(record.getMessage())

    def message(self, message):
        message = redact(str(message))
        if message != self.last_message:
            rendered = Text(message)
            if message.startswith("✓ "):
                rendered.stylize("bold green", 0, 1)
            self.console.print(rendered, markup=False, highlight=False)
            self.last_message = message

    def event(self, event):
        if not isinstance(event, dict):
            return
        kind = event.get("kind")
        if kind == "metadata":
            values = event.get("values", {})
            if not isinstance(values, dict):
                return
            for key in ("Video", "Song", "Artist", "Channel", "Duration"):
                value = values.get(key)
                if value not in (None, "", "NA") and self.metadata.get(key) != value:
                    self.metadata[key] = value
                    if key != "Song" or value != self.metadata.get("Video"):
                        self.message(f"{key}: {value}")
            return
        if kind in {"message", "warning"}:
            message = str(event.get("message", ""))
            if kind == "warning":
                if message in self.warnings:
                    return
                self.warnings.add(message)
            self.message(message)
            return
        if kind != "stage" or not isinstance(event.get("label"), str):
            return
        key = str(event.get("id", event["label"]))
        label = event["label"]
        total, completed = event.get("total"), event.get("completed", 0)
        if not isinstance(total, (int, float)) or total <= 0:
            total = None
        if not isinstance(completed, (int, float)) or completed < 0:
            completed = 0
        state = event.get("state", "running")
        now = self.clock()
        if state != "running" and key not in self.began and "elapsed" not in event:
            return
        if state == "running":
            if key not in self.began or event.get("reset"):
                self.began[key] = now
                self.milestones[key] = (0, now)
            if self.labels.get(key) != label or event.get("reset"):
                self.labels[key] = label
                if not self.console.is_interactive:
                    self.message(label + "…")
            if not self.console.is_interactive and total:
                percent = min(100, int(completed / total * 100))
                last_percent, last_time = self.milestones[key]
                if percent // 25 > last_percent // 25 and now - last_time >= 10:
                    detail = f" · {event['detail']}" if event.get("detail") else ""
                    self.message(f"{label} · {percent}%{detail}")
                    self.milestones[key] = (percent, now)
        if self.console.is_interactive:
            if not self.started:
                self.progress.start()
                self.started = True
            if event.get("reset") and key in self.tasks:
                self.progress.remove_task(self.tasks.pop(key))
            if key not in self.tasks:
                self.tasks[key] = self.progress.add_task(label, total=total, detail="")
            task = self.tasks[key]
            detail = event.get("detail", "")
            if total:
                amount = (f"{completed / 1024 ** 2:.1f}/{total / 1024 ** 2:.1f} MB" if event.get("unit") == "bytes"
                          else f"{min(100, completed / total * 100):.0f}%")
                detail = f"{amount} {detail}".strip()
            self.progress.update(task, description=label, total=total, completed=completed, detail=detail,
                                 visible=state == "running", refresh=True)
            if state != "running":
                self.progress.remove_task(task)
                del self.tasks[key]
        if state != "running":
            began = self.began.pop(key, None)
            self.milestones.pop(key, None)
            if state == "done" and event.get("parent") not in self.began:
                elapsed = event.get("elapsed")
                if began is not None:
                    visible_elapsed = now - began
                    elapsed = max(visible_elapsed, elapsed) if isinstance(elapsed, (int, float)) else visible_elapsed
                duration = ""
                if isinstance(elapsed, (int, float)):
                    if elapsed < 1:
                        duration = " · <1s"
                    else:
                        minutes, seconds = divmod(round(elapsed), 60)
                        duration = f" · {minutes}m {seconds:02d}s" if minutes else f" · {seconds}s"
                summary = {"background": "Background ready", "install_browser": "Renderer ready",
                           "render_karaoke": "Karaoke video ready", "render_lyrics": "Lyrics video ready",
                           "runtime": "Runtime ready", "colab_setup": "Colab ready",
                           "package": "Results packaged"}.get(key, label)
                self.message(f"✓ {summary}{duration}")

    def close(self):
        if self.started:
            self.progress.stop()
            self.started = False
        super().close()


def notify(label: str, *, stage: str | None = None, **fields) -> None:
    """Report a meaningful stage or result, independently of technical logs."""
    event = ({"kind": "stage", "id": stage, "label": label} if stage else
             {"kind": "message", "message": label})
    LOGGER.info(label, extra={"user_event": {**event, **fields}})


def configure_logging(verbose: bool = False, *, log_dir: Path | None = None, diagnostics: bool = True) -> Path | None:
    """Configure one terminal presenter and a redacted per-run diagnostic file."""
    handlers = [ProgressHandler()]
    path = None
    if diagnostics:
        directory = log_dir or PROJECT_ROOT / ".karaoke/logs"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / f"{datetime.now(UTC):%Y%m%dT%H%M%S-%f}-{os.getpid()}.log"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        handler = logging.StreamHandler(os.fdopen(descriptor, "w", encoding="utf-8"))
        handler.setFormatter(DiagnosticFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handlers.append(handler)
    if verbose:
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(DiagnosticFormatter("%(levelname)s %(name)s: %(message)s"))
        handlers.append(handler)
    logging.basicConfig(level=logging.DEBUG, handlers=handlers, force=True)
    logging.getLogger("karaoke_app").setLevel(logging.DEBUG)
    return path


def stream_process(command, *, timeout=None, on_line=None, on_tick=None):
    """Drain both pipes concurrently, retaining a bounded tail and enforcing timeouts."""
    began = time.monotonic()
    messages = queue.Queue(maxsize=1024)
    tails = {"stdout": deque(maxlen=200), "stderr": deque(maxlen=200)}
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               bufsize=0)
    stopping = threading.Event()

    def enqueue(item):
        while not stopping.is_set():
            try:
                messages.put(item, timeout=.1)
                return
            except queue.Full:
                pass

    def read(pipe, name):
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        pending = ""
        try:
            while chunk := pipe.read(4096):
                pending += decoder.decode(chunk)
                while "\n" in pending:
                    line, pending = pending.split("\n", 1)
                    enqueue((name, line + "\n"))
                # colab-cli uses input() without a newline for its OAuth code prompt.
                if pending.endswith("Enter the authorization code: ") or len(pending) > 65536:
                    enqueue((name, pending))
                    pending = ""
            pending += decoder.decode(b"", final=True)
            if pending:
                enqueue((name, pending))
        finally:
            pipe.close()
            enqueue((name, None))

    threads = [threading.Thread(target=read, args=(getattr(process, name), name), daemon=True)
               for name in tails]
    for thread in threads:
        thread.start()
    ended = 0
    last_tick = began
    try:
        while ended < 2 or process.poll() is None:
            now = time.monotonic()
            if on_tick and now - last_tick >= 1:
                on_tick()
                last_tick = now
            if timeout is not None and time.monotonic() - began >= timeout:
                raise subprocess.TimeoutExpired([command[0]], timeout)
            try:
                name, line = messages.get(timeout=.1)
            except queue.Empty:
                continue
            if line is None:
                ended += 1
                continue
            tails[name].append(line)
            LOGGER.debug("%s: %s", name, line.rstrip())
            if on_line:
                on_line(line)
        return subprocess.CompletedProcess(command, process.wait(), "".join(tails["stdout"]),
                                           "".join(tails["stderr"]))
    finally:
        stopping.set()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for thread in threads:
            thread.join(timeout=1)


def remote_event(line):
    """Decode only the versioned event channel; ordinary output stays in diagnostics."""
    if not line.startswith(EVENT_PREFIX):
        stripped = line.strip()
        if (stripped.startswith("https://accounts.google.com/") or
                stripped.startswith("To authorize colab-cli") or
                stripped.startswith("After approving, Google") or
                stripped.startswith("Enter the authorization code:")):
            notify(stripped)
        return
    try:
        event = json.loads(line[len(EVENT_PREFIX):])
    except ValueError:
        LOGGER.debug("Invalid progress event")
        return
    if isinstance(event, dict) and event.get("version") == 1:
        LOGGER.info("Remote progress", extra={"user_event": event})
        return event



def failure_summary(*outputs: str | None) -> str:
    """Extract the useful exception from plain/Rich tracebacks, without stack frames."""
    ansi = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
    exception = re.compile(r"^(?:[\w.]+\.)?[\w]*(?:Error|Exception|Failure|Interrupt|Exit):\s*", re.I)
    candidates = []
    fallback = []
    reported = []
    for output in outputs:
        lines = [ansi.sub("", line).strip() for line in (output or "").splitlines()]
        for index, line in enumerate(lines):
            if line.startswith(EVENT_PREFIX):
                try:
                    event = json.loads(line[len(EVENT_PREFIX):])
                except ValueError:
                    continue
                if (isinstance(event, dict) and event.get("version") == 1 and event.get("kind") == "failure"
                        and isinstance(event.get("message"), str)):
                    reported.append(event["message"])
                continue
            if exception.match(line):
                parts = [line]
                for continuation in lines[index + 1:index + 4]:
                    if (not continuation or exception.match(continuation) or
                            continuation.startswith(("Traceback", "During handling", "The above", "│", "╭", "╰"))):
                        break
                    parts.append(continuation)
                candidates.append(" ".join(parts))
            elif (line and not line.startswith(("│", "╭", "╰", "File ", "Traceback")) and
                  re.search(r"\b(error|failed|denied|unavailable|not found)\b", line, re.I)):
                fallback.append(line)
    useful = [value for value in candidates if not value.startswith("CalledProcessError:")]
    detail = (reported[-1] if reported else useful[-1] if useful else fallback[-1] if fallback
              else candidates[-1] if candidates else "No error details were returned.")
    if "TooManyAssignmentsError:" in detail:
        return ("TooManyAssignmentsError: Colab rejected a new session (HTTP 412: Precondition Failed). "
                "Stop an unused Colab session and retry.")
    detail = re.sub(r"https?://[^\s]+", lambda match: match.group(0).split("?")[0], detail)
    return redact(detail)[:500]


class ProcessFailure(RuntimeError):
    """A short operation failure with the underlying cause retained for the CLI."""

    def __init__(self, label, result):
        self.returncode = result.returncode
        self.cause = failure_summary(result.stdout, result.stderr)
        super().__init__(f"{label} failed (exit {result.returncode}).\n{self.cause}")


class RemoteProgress:
    """Track reported work and expose telemetry silence without inventing progress."""

    def __init__(self, label, *, clock=time.monotonic):
        self.label = label
        self.clock = clock
        self.last_update = clock()
        self.last_stage = None
        self.active_stages = {}
        self.started = False
        self.silence_reported = False

    def feed(self, line):
        event = remote_event(line)
        if not event or event.get("kind") != "stage" or not isinstance(event.get("label"), str):
            return
        self.last_update = self.clock()
        self.last_stage = event["label"]
        key = str(event.get("id", event["label"]))
        if event.get("state", "running") == "running":
            self.active_stages[key] = event["label"]
        else:
            self.active_stages.pop(key, None)
        self.silence_reported = False
        if not self.started:
            notify(self.label, stage="colab", state="stopped")
            self.started = True
        if key == "runtime" and event.get("state") == "done":
            notify("Preparing Colab", stage="colab_setup", state="done")

    def check_silence(self):
        elapsed = self.clock() - self.last_update
        if elapsed >= 60 and not self.silence_reported:
            context = f"Last reported stage: {self.last_stage}." if self.last_stage else "No stage reported yet."
            notify(f"No progress updates from Colab for {int(elapsed)}s. {context}")
            self.silence_reported = True


def run_process(command: list[str], *, check: bool = True,
                timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    operation = command[2] if command[0] == "colab" and len(command) > 2 else command[0]
    label = {"new": "Connecting to Colab", "install": "Preparing dependencies",
             "upload": "Uploading project", "exec": "Starting pipeline on Colab",
             "download": "Downloading results", "stop": "Stopping Colab session"}.get(operation, "Processing")
    notify(label, stage="transfer" if operation in {"upload", "download"} else "colab")
    progress = RemoteProgress(label) if operation == "exec" else None
    try:
        result = stream_process(command, timeout=timeout,
                                on_line=progress.feed if progress else remote_event,
                                on_tick=progress.check_silence if progress else None)
    finally:
        notify(label, stage="transfer" if operation in {"upload", "download"} else "colab", state="stopped")
    if result.returncode and check:
        if progress and progress.active_stages:
            label = next(reversed(progress.active_stages.values()))
        raise ProcessFailure(label, result)
    return result
