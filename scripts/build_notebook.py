"""Build or verify the single notebook/wheel delivery in notebooks/."""

import argparse
import ast
import hashlib
import json
import logging
import shutil
import subprocess
import tempfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def package_sources(root: Path, project: dict) -> dict[str, Path]:
    """Resolve packaged files from the source tree and the build configuration."""
    sources = {
        path.relative_to(root / "src").as_posix(): path
        for path in (root / "src/karaoke_app").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}
    }
    sources.update({
        destination: root / source
        for source, destination in project["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"].items()
    })
    return sources


def source_bytes(path: Path) -> bytes:
    """Match Git's LF text checkout so local and CI wheels have the same digest."""
    content = path.read_bytes()
    if path.suffix in {".py", ".txt", ".md", ".js", ".json", ".html", ".css", ".toml"} or path.name == "LICENSE":
        content = content.replace(b"\r\n", b"\n")
    return content


def validate_wheel(root: Path, wheel: Path, project: dict) -> None:
    """Reject wheels whose version or packaged sources differ from this checkout."""
    version = project["project"]["version"]
    with zipfile.ZipFile(wheel) as archive:
        metadata = BytesParser().parsebytes(archive.read(f"lyrics_generator-{version}.dist-info/METADATA"))
        if metadata["Version"] != version:
            raise ValueError("Wheel version does not match pyproject.toml")
        if any("logos" in Path(name).parts for name in archive.namelist()):
            raise ValueError("Local artwork must not be packaged")
        sources = package_sources(root, project)
        if {name for name in archive.namelist() if name.startswith("karaoke_app/")} != set(sources):
            raise ValueError("Wheel file list differs from the current package sources")
        for name, path in sources.items():
            if archive.read(name) != source_bytes(path):
                raise ValueError(f"Wheel is stale: {path.relative_to(root)}. Rebuild the notebook delivery.")


def notebook_constants(notebook: dict) -> tuple[dict, dict]:
    """Compile the notebook and locate generated engine identity fields."""
    setup = next(cell for cell in notebook["cells"] if cell.get("id") == "setup")
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), f"notebook:{cell['id']}", "exec")
            if cell.get("outputs") or cell.get("execution_count") is not None:
                raise ValueError("Clear notebook outputs before distributing it")
    constants = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in ast.parse("".join(setup["source"])).body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"RELEASE_VERSION", "RELEASE_SHA256"}
    }
    if set(constants) != {"RELEASE_VERSION", "RELEASE_SHA256"}:
        raise ValueError("Notebook is missing engine identity fields")
    return setup, constants


def build_delivery(root: Path, *, check: bool = False) -> Path:
    """Keep the canonical notebook paired with exactly one current engine wheel."""
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    folder = root / "notebooks"
    path = folder / "generate_video.ipynb"
    if list(folder.glob("*.ipynb")) != [path]:
        raise ValueError("Keep only notebooks/generate_video.ipynb as the editable notebook")
    notebook = json.loads(path.read_text(encoding="utf-8"))
    setup, constants = notebook_constants(notebook)
    wheel = folder / f"lyrics_generator-{version}-py3-none-any.whl"
    if check:
        if list(folder.glob("*.whl")) != [wheel]:
            raise ValueError("Build the single matching wheel with scripts/build_notebook.py")
        validate_wheel(root, wheel, project)
        if constants != {"RELEASE_VERSION": version, "RELEASE_SHA256": hashlib.sha256(wheel.read_bytes()).hexdigest()}:
            raise ValueError("Notebook and wheel do not match. Rebuild the notebook delivery.")
        LOGGER.info("Verified notebook and wheel %s", version)
        return wheel

    with tempfile.TemporaryDirectory(prefix="karaoke-build-") as temporary:
        snapshot = Path(temporary) / "source"
        for source in {*package_sources(root, project).values(), root / "pyproject.toml", root / "LICENSE"}:
            destination = snapshot / source.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source_bytes(source))
        subprocess.run(
            ["uv", "build", "--wheel", "--no-sources", "--out-dir", temporary, str(snapshot)], cwd=root, check=True,
        )
        built = Path(temporary) / wheel.name
        validate_wheel(root, built, project)
        identity = {"RELEASE_VERSION": version, "RELEASE_SHA256": hashlib.sha256(built.read_bytes()).hexdigest()}
        for key, value in identity.items():
            indexes = [index for index, line in enumerate(setup["source"]) if line.startswith(f"{key} = ")]
            if len(indexes) != 1:
                raise ValueError(f"Expected exactly one generated {key} assignment")
            setup["source"][indexes[0]] = f"{key} = {value!r}\n"
        shutil.copyfile(built, wheel)
    path.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for stale in folder.glob("lyrics_generator-*.whl"):
        if stale != wheel:
            stale.unlink()
    LOGGER.info("Built %s and pinned its SHA-256 in %s", wheel.name, path.relative_to(root))
    return wheel


def main() -> None:
    """Build the delivery, or check it without modifying files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify existing wheel, source, version and notebook hash")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    build_delivery(Path(__file__).resolve().parents[1], check=args.check)


if __name__ == "__main__":
    main()
