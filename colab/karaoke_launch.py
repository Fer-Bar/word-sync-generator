"""Start preparation with NVIDIA library paths visible to the dynamic loader."""

import importlib.metadata
import json
import logging
import os
import shutil
import subprocess
import sys
import zipfile
from collections import deque
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def _run_streamed(command: list[str], *, environment: dict[str, str] | None = None) -> None:
    tail = deque(maxlen=20)
    with subprocess.Popen(
        command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    ) as process:
        # Colab captures notebook streams, not inherited child file descriptors.
        for line in process.stdout:
            tail.append(line)
            sys.stdout.write(line)
            sys.stdout.flush()
        returncode = process.wait()
    if returncode:
        details = "".join(tail).strip()
        raise RuntimeError(f"Process exited with code {returncode}: {command[0]}\n{details}")


def _install_requirements(requirements: Path) -> Path:
    event = {"version": 1, "kind": "stage", "id": "dependencies",
             "label": "Preparing dependencies", "parent": "colab_setup"}
    sys.stdout.write("KARAOKE_EVENT " + json.dumps(event) + "\n")
    sys.stdout.flush()
    uv = shutil.which("uv")
    if uv is None:
        bootstrap = requirements.parent / "karaoke-bootstrap"
        _run_streamed([sys.executable, "-m", "pip", "install", "--target", str(bootstrap), "uv==0.13.4"])
        uv = str(bootstrap / "bin" / "uv")
    runtime = requirements.parent / "karaoke-env"
    python = runtime / "bin" / "python"
    _run_streamed([uv, "venv", "--allow-existing", "--python", sys.executable, str(runtime)])
    _run_streamed([uv, "pip", "install", "--python", str(python), "-r", str(requirements)])
    _run_streamed([uv, "pip", "check", "--python", str(python)])
    sys.stdout.write("KARAOKE_EVENT " + json.dumps({**event, "state": "done"}) + "\n")
    sys.stdout.flush()
    return python


def cuda_environment() -> dict[str, str]:
    """Expose pip-installed CUDA libraries before starting the preparation process."""
    environment = os.environ.copy()
    directories = []
    for package in ("nvidia-cublas-cu12", "nvidia-cudnn-cu12"):
        distribution = importlib.metadata.distribution(package)
        for entry in distribution.files or []:
            if ".so" in entry.name:
                directory = str(Path(distribution.locate_file(entry)).parent)
                if directory not in directories:
                    directories.append(directory)
        LOGGER.info("CUDA dependency: %s=%s", package, distribution.version)
    if not directories:
        raise RuntimeError("No CUDA library directories found in the installed NVIDIA packages")
    previous = environment.get("LD_LIBRARY_PATH")
    environment["LD_LIBRARY_PATH"] = os.pathsep.join([*directories, *([previous] if previous else [])])
    return environment


def main(config_path: Path = Path("/content/karaoke_job.json")) -> None:
    """Run uploaded code or the installed pipeline outside the notebook kernel."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", force=True)
    status_path = config_path.with_name("karaoke_status.json")
    status_path.unlink(missing_ok=True)
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if config.get("source_bundle"):
            pipeline = config_path.with_name("karaoke_pipeline.py")
            requirements = config_path.with_name("requirements.txt")
            with zipfile.ZipFile(config["source_bundle"]) as archive:
                pipeline.write_bytes(archive.read(pipeline.name))
                if requirements.name in archive.namelist():
                    requirements.write_bytes(archive.read(requirements.name))
                    runtime = config_path.parent / "karaoke-env"
                    if Path(sys.prefix).resolve() != runtime.resolve():
                        launcher = config_path.with_name("karaoke_launch.py")
                        launcher.write_bytes(archive.read(launcher.name))
                        python = _install_requirements(requirements)
                        environment = os.environ.copy()
                        environment.pop("PYTHONPATH", None)
                        environment.pop("PYTHONHOME", None)
                        environment["VIRTUAL_ENV"] = str(runtime)
                        environment["PATH"] = f"{python.parent}{os.pathsep}{environment.get('PATH', '')}"
                        environment["KARAOKE_RUNTIME_DIR"] = str(config_path.resolve().parent)
                        _run_streamed([str(python), "-u", str(launcher)], environment=environment)
                        return
        else:
            pipeline = Path(__file__).resolve().with_name("karaoke_job.py")
        environment = cuda_environment()
        environment["KARAOKE_RUNTIME_DIR"] = str(config_path.resolve().parent)
        _run_streamed(
            [sys.executable, "-u", str(pipeline)],
            environment=environment,
        )
    except Exception as error:
        if not status_path.exists():
            status_path.write_text(json.dumps({"status": "failed", "error": str(error)}), encoding="utf-8")
        raise


if __name__ == "__main__":
    main(Path(os.environ.get("KARAOKE_RUNTIME_DIR", "/content")) / "karaoke_job.json")
