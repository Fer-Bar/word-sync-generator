"""JSON adapter for notebook controls running outside the engine's Python environment."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from karaoke_app.job_document import load_job_document, resolve_job_asset
from karaoke_app.lyrics_file import load_lyrics_file
from karaoke_app.notebook import prepare_audio, render_project, runtime_report


def project_info(directory: Path) -> dict:
    """Return reviewable lyrics and media locations without changing the project."""
    document = load_job_document(directory)
    lyrics = load_lyrics_file(resolve_job_asset(directory, document["media"]["lyrics"], "lyrics"))
    return {
        "title": document["title"],
        "vocals": str(resolve_job_asset(directory, document["media"]["vocals_audio"], "vocals")),
        "lyrics": "\n".join(line["text"] for line in lyrics["lines"]),
    }


def main() -> None:
    """Execute one notebook request and write its result only after success."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("diagnose", "prepare", "inspect", "render"))
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    if args.operation == "diagnose":
        import torch

        result = {**runtime_report(), "cuda_available": torch.cuda.is_available()}
        if result["cuda_available"]:
            result["gpu"] = torch.cuda.get_device_name(0)
    elif args.operation == "prepare":
        for field in ("source", "output_dir", "lyrics_text"):
            if request.get(field) is not None:
                request[field] = Path(request[field])
        result = asdict(prepare_audio(**request))
    elif args.operation == "inspect":
        result = project_info(Path(request["directory"]))
    else:
        result = asdict(render_project(Path(request["directory"]), options=request.get("options")))
    args.result.write_text(json.dumps(result, default=str, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
