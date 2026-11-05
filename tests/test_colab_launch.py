import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from colab import karaoke_launch as launch


@pytest.fixture
def cuda_packages(monkeypatch, tmp_path):
    def distribution(name):
        return SimpleNamespace(
            version="test", files=[Path("lib/library.so.12")],
            locate_file=lambda entry: tmp_path / name / entry,
        )

    monkeypatch.setattr(launch.importlib.metadata, "distribution", distribution)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/existing/libs")


def run_pipeline(tmp_path, code):
    bundle = tmp_path / "source.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("karaoke_pipeline.py", code)
    config_path = tmp_path / "karaoke_job.json"
    config_path.write_text(json.dumps({"source_bundle": str(bundle)}))
    launch.main(config_path)


def test_child_receives_cuda_paths_before_python_starts(tmp_path, cuda_packages):
    output = tmp_path / "environment.json"
    run_pipeline(tmp_path, f"""
import json
import os
from pathlib import Path
Path({str(output)!r}).write_text(json.dumps(os.environ['LD_LIBRARY_PATH']))
""")
    paths = json.loads(output.read_text()).split(":")
    assert paths == [
        str(tmp_path / "nvidia-cublas-cu12/lib"),
        str(tmp_path / "nvidia-cudnn-cu12/lib"),
        "/existing/libs",
    ]


def test_child_failure_preserves_recovery_status(tmp_path, cuda_packages):
    status = tmp_path / "karaoke_status.json"
    with pytest.raises(RuntimeError, match="code 1"):
        run_pipeline(tmp_path, f"""
from pathlib import Path
Path({str(status)!r}).write_text('{{"status":"failed","stage":"lyrics","recovery_archive_path":"checkpoint.zip"}}')
raise RuntimeError('failed lyrics')
""")
    assert json.loads(status.read_text())["recovery_archive_path"] == "checkpoint.zip"


@pytest.mark.parametrize("exit_code", [0, 1])
def test_child_output_reaches_notebook_python_stream(tmp_path, cuda_packages, monkeypatch, exit_code):
    output = io.StringIO()
    monkeypatch.setattr(launch.sys, "stdout", output)
    code = f"""
import logging
import sys
logging.basicConfig(level=logging.INFO)
logging.info('Source metadata: artist=None')
sys.stdout.write('pipeline progress\\n')
sys.exit({exit_code})
"""
    if exit_code:
        with pytest.raises(RuntimeError, match="code 1"):
            run_pipeline(tmp_path, code)
    else:
        run_pipeline(tmp_path, code)
    assert "Source metadata: artist=None" in output.getvalue()
    assert "pipeline progress" in output.getvalue()
