"""Exercise uploaded services without the locally installed application package."""

import shutil
import subprocess
import sys
from pathlib import Path


def test_uploaded_lyrics_module_loads_without_application_package(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    for source, target in (
        ("colab/karaoke_job.py", "karaoke_job.py"),
        ("src/karaoke_app/lyrics_file.py", "karaoke_lyrics_file.py"),
        ("src/karaoke_app/lyric_references.py", "karaoke_lyric_references.py"),
    ):
        shutil.copyfile(root / source, tmp_path / target)
    script = """
import importlib.abc
import sys
from pathlib import Path

class BlockLocalPackage(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "karaoke_app" or fullname.startswith("karaoke_app."):
            raise ModuleNotFoundError("No module named 'karaoke_app'", name="karaoke_app")

sys.meta_path.insert(0, BlockLocalPackage())
sys.path.insert(0, str(Path.cwd()))
import karaoke_job
karaoke_job.LYRICS_MODULE_PATH = Path.cwd() / "karaoke_lyrics_file.py"
karaoke_job.REFERENCES_MODULE_PATH = Path.cwd() / "karaoke_lyric_references.py"
lyrics = karaoke_job._load_lyrics_module()
references = karaoke_job._load_references_module()
assert lyrics.sanitize_text("Olá mundo") == references.sanitize_text("Olá mundo")
assert callable(lyrics.validate_lyrics_file)
tokenized = karaoke_job._alignment_document_tokens(
    references.plain_lines("lead (\\necho\\n)"), character_alignment=False,
)
assert tokenized[1][1][0]["isBackground"] is True
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script], cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
