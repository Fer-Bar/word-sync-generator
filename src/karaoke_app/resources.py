"""Locate immutable package resources separately from writable project data."""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
_CHECKOUT = PACKAGE_ROOT.parents[1]
IS_CHECKOUT = (_CHECKOUT / "pyproject.toml").is_file() and (_CHECKOUT / "colab").is_dir()
PROJECT_ROOT = _CHECKOUT if IS_CHECKOUT else Path.cwd()


def runtime_resource(name: str) -> Path:
    """Return a pipeline resource from the checkout or an installed wheel."""
    if name not in {"karaoke_job.py", "karaoke_launch.py", "requirements.txt"}:
        raise ValueError(f"Unknown runtime resource: {name}")
    root = _CHECKOUT / "colab" if IS_CHECKOUT else PACKAGE_ROOT / "runtime"
    return root / name


def logo_resource(name: str) -> Path:
    """Return a bundled logo without writing inside the installed package."""
    if name not in {"banner.png", "principal_logo.png", "thumbnail.png"}:
        raise ValueError(f"Unknown bundled logo: {name}")
    root = _CHECKOUT / "logos" if IS_CHECKOUT else PACKAGE_ROOT / "assets" / "logos"
    return root / name
