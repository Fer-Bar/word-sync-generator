"""Start preparation with NVIDIA library paths visible to the dynamic loader."""

import importlib.metadata
import json
import logging
import os
import subprocess
import sys
import zipfile
from pathlib import Path

LOGGER = logging.getLogger(__name__)


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
            with zipfile.ZipFile(config["source_bundle"]) as archive:
                pipeline.write_bytes(archive.read(pipeline.name))
        else:
            pipeline = Path(__file__).resolve().with_name("karaoke_job.py")
        environment = cuda_environment()
        environment["KARAOKE_RUNTIME_DIR"] = str(config_path.resolve().parent)
        with subprocess.Popen(
            [sys.executable, "-u", str(pipeline)],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        ) as process:
            # Colab captures notebook streams, not the child process's inherited file descriptors.
            for line in process.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
            returncode = process.wait()
        if returncode:
            raise RuntimeError(f"Preparation process exited with code {returncode}; see remote status and logs")
    except Exception as error:
        if not status_path.exists():
            status_path.write_text(json.dumps({"status": "failed", "error": str(error)}), encoding="utf-8")
        raise


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/content/karaoke_job.json"))
