"""Run the render CLI end to end, replacing only the external Colab executable."""

import json
import os
import subprocess
import sys
import textwrap
import wave
import zipfile
from pathlib import Path

import imageio_ffmpeg
import pytest

from karaoke_app.job_document import STATE_FILENAME

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def rendering_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    with wave.open(str(project / "original.wav"), "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 8000)
    document = {
        "schema_version": 2, "title": "Song", "source": {"artist": "Test Artist"},
        "video": {"width": 640, "height": 360, "fps": 24},
        "media": {"lyrics": "lyrics.yaml", "original_audio": "original.wav",
                  "instrumental_audio": "original.wav", "vocals_audio": "original.wav"},
        "background": {"kind": "solid", "color": "#000000"},
        "watermark": {"enabled": False}, "intro": {"enabled": False},
    }
    state = project / STATE_FILENAME
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps(document))
    (project / "lyrics.yaml").write_text(textwrap.dedent('''\
        version: "1.0"
        metadata:
          title: Song
          duration_ms: 1000
        lines:
          - text: Hello
            start_ms: 0
            end_ms: 1000
            words:
              - text: Hello
                start_ms: 0
                end_ms: 1000
    '''))
    video = tmp_path / "synthetic.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i",
                    "color=black:s=64x64:d=0.1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
                   check=True, capture_output=True, timeout=30)
    archive = tmp_path / "remote-result.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.write(video, "Song_lyrics.mp4")
        bundle.writestr("render-settings.json", json.dumps(document))
    binary = tmp_path / "bin"
    binary.mkdir()
    colab = binary / "colab"
    colab.write_text(f"#!{sys.executable}\n" + textwrap.dedent('''\
        import json
        import os
        import shutil
        import sys
        from pathlib import Path

        operation = sys.argv[2]
        with Path(os.environ["COLAB_CALLS"]).open("a") as calls:
            calls.write(operation + "\\n")
        if operation == "exec" and os.environ.get("COLAB_FAIL") == "1":
            sys.exit(1)
        if operation == "download":
            target = Path(sys.argv[-1])
            if sys.argv[-2].endswith("status.json"):
                target.write_text(json.dumps({"status": "completed"}))
            else:
                shutil.copyfile(os.environ["COLAB_ARCHIVE"], target)
    '''))
    colab.chmod(0o755)
    env = {**os.environ, "PATH": f"{binary}{os.pathsep}{os.environ['PATH']}", "PYTHONPATH": str(REPO / "src"),
           "COLAB_ARCHIVE": str(archive), "COLAB_CALLS": str(tmp_path / "calls.txt"), "NO_COLOR": "1"}
    return project, env, video.read_bytes()


def run_render(project, env):
    return subprocess.run([sys.executable, "-c", "from karaoke_app.cli import main; raise SystemExit(main())",
                           "render", str(project), "--mode", "lyrics"],
                          cwd=project, env=env, capture_output=True, text=True, timeout=60)


def test_successive_successful_renders_keep_every_variant_and_sidecar(rendering_project):
    project, env, video = rendering_project
    old = project / "renders" / "20260101-000000-lyrics"
    old.mkdir(parents=True)
    (old / "Song_lyrics.mp4").write_bytes(video)
    (old / "notes.txt").write_text("Keep this artistic variant")
    for _ in range(2):
        result = run_render(project, env)
        assert result.returncode == 0, result.stdout + result.stderr
    exports = list((project / "renders").iterdir())
    assert len(exports) == 3
    assert (old / "notes.txt").read_text() == "Keep this artistic variant"
    for export in exports:
        assert (export / "Song_lyrics.mp4").read_bytes() == video
        if export != old:
            assert (export / "subtitles" / "Song.srt").read_text().endswith("Hello\n")
            assert (export / "performance.json").is_file()
    assert Path(env["COLAB_CALLS"]).read_text().splitlines().count("stop") == 2
    assert not (project / ".trash").exists()


def test_failed_remote_render_keeps_previous_exports_and_stops_session(rendering_project):
    project, env, video = rendering_project
    old = project / "renders" / "20260101-000000-lyrics"
    old.mkdir(parents=True)
    (old / "Song_lyrics.mp4").write_bytes(video)
    result = run_render(project, {**env, "COLAB_FAIL": "1"})
    assert result.returncode != 0
    assert list((project / "renders").iterdir()) == [old]
    assert (old / "Song_lyrics.mp4").read_bytes() == video
    assert Path(env["COLAB_CALLS"]).read_text().splitlines()[-1] == "stop"
