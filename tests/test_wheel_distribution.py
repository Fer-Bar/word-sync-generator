import subprocess
import zipfile
from pathlib import Path


def test_wheel_contains_runtime_without_local_artwork(tmp_path):
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(tmp_path)], cwd=root, check=True, capture_output=True)
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
        assert not any("logos" in Path(name).parts for name in names)
        assert {
            "karaoke_app/runtime/karaoke_job.py", "karaoke_app/runtime/karaoke_launch.py",
            "karaoke_app/runtime/requirements.txt", "karaoke_app/THIRD_PARTY_NOTICES.md",
            "karaoke_app/assets/fonts/Anton-Regular.ttf",
        } <= names
