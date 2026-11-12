"""The JSON inspection API exposes existing preparation evidence without modifying projects."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from karaoke_app.job_document import STATE_FILENAME


def test_inspect_exposes_saved_design_without_changing_project(prepared_project):
    from karaoke_app.job_document import load_job_document
    from karaoke_app.notebook_runner import project_info

    before = {p.relative_to(prepared_project): p.read_bytes() for p in prepared_project.rglob('*') if p.is_file()}
    document = load_job_document(prepared_project)
    result = project_info(prepared_project)
    assert result['design'] == {'background': document['background'], 'style': document.get('style', {})}
    after = {p.relative_to(prepared_project): p.read_bytes() for p in prepared_project.rglob('*') if p.is_file()}
    assert after == before


@pytest.mark.parametrize("provider", ["lrclib", "genius", "txt", "whisper", None])
def test_inspect_reports_song_evidence_and_timings_without_writes(prepared_project, tmp_path, provider):
    state = prepared_project / STATE_FILENAME
    document = json.loads(state.read_text())
    document["source"].update(album="Studio album", language="en")
    if provider:
        document["alignment"] = {
            "reference_source": provider, "engine": "ctc-forced-aligner", "word_timing": "generated",
            "needs_review": True, "asr_anchor_check": {"status": "insufficient_anchors"},
            "acoustic_verification": "completed",
        }
    state.write_text(json.dumps(document))
    before = {p.relative_to(prepared_project): p.read_bytes() for p in prepared_project.rglob("*") if p.is_file()}
    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    request.write_text(json.dumps({"directory": str(prepared_project)}))
    process = subprocess.run(
        [sys.executable, "-m", "karaoke_app.notebook_runner", "inspect",
         "--request", str(request), "--result", str(result)], capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}, timeout=20,
    )
    assert (process.returncode, process.stdout, process.stderr) == (0, "", "")
    info = json.loads(result.read_text())
    assert info["title"] == "Song"
    assert info["vocals"] == str(prepared_project / "vocals.wav")
    assert info["lyrics"] == "Hello world"
    assert info["song"] == {"title": "Song", "artist": "Test artist", "album": "Studio album", "language": "en"}
    assert info["review"] == {
        "reference_source": provider,
        "alignment_engine": "ctc-forced-aligner" if provider else None,
        "word_timing": "generated" if provider else None,
        "acoustic_verification": "completed" if provider else None,
        "needs_review": True if provider else None,
        "anchor_status": "insufficient_anchors" if provider else None,
    }
    assert info["timed_lines"] == [{
        "text": "Hello world", "start_ms": 200, "end_ms": 800,
        "words": [{"text": "Hello ", "start_ms": 200, "end_ms": 500},
                  {"text": "world", "start_ms": 500, "end_ms": 800}],
    }]
    after = {p.relative_to(prepared_project): p.read_bytes() for p in prepared_project.rglob("*") if p.is_file()}
    assert after == before


@pytest.mark.parametrize("anchor", [None, {}, "unknown", ["unknown"]])
def test_inspect_unknown_anchor_keeps_project_readable(prepared_project, tmp_path, anchor):
    state = prepared_project / STATE_FILENAME
    document = json.loads(state.read_text())
    document["alignment"] = {"text_source": "whisper", "asr_anchor_check": anchor}
    state.write_text(json.dumps(document))
    before = {p.relative_to(prepared_project): p.read_bytes() for p in prepared_project.rglob("*") if p.is_file()}
    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    request.write_text(json.dumps({"directory": str(prepared_project)}))
    process = subprocess.run(
        [sys.executable, "-m", "karaoke_app.notebook_runner", "inspect",
         "--request", str(request), "--result", str(result)], capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}, timeout=20,
    )
    assert (process.returncode, process.stdout, process.stderr) == (0, "", "")
    info = json.loads(result.read_text())
    assert info["title"] == "Song"
    assert info["vocals"] == str(prepared_project / "vocals.wav")
    assert info["lyrics"] == "Hello world"
    assert info["review"]["reference_source"] == "whisper"
    assert info["review"]["anchor_status"] is None
    assert info["review"]["needs_review"] is None
    assert info["timed_lines"][0]["start_ms"] == 200
    assert info["timed_lines"][0]["words"][1]["end_ms"] == 800
    after = {p.relative_to(prepared_project): p.read_bytes() for p in prepared_project.rglob("*") if p.is_file()}
    assert after == before
