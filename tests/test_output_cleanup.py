from karaoke_app.output_cleanup import obsolete_renders, prune_renders


def make_render(root, name, modes):
    directory = root / "renders" / name
    directory.mkdir(parents=True)
    for mode in modes:
        (directory / f"Song_{mode}.mp4").write_bytes(b"video")
    return directory


def test_retains_latest_of_each_mode_and_ignores_incomplete_and_custom_dirs(tmp_path):
    old = make_render(tmp_path, "20260101-000000-both", ["lyrics", "karaoke"])
    lyrics = make_render(tmp_path, "20260102-000000-lyrics", ["lyrics"])
    assert obsolete_renders(tmp_path) == []
    karaoke = make_render(tmp_path, "20260103-000000-karaoke", ["karaoke"])
    incomplete = make_render(tmp_path, "20260104-000000-both", [])
    custom = make_render(tmp_path, "favorites", ["karaoke"])
    assert obsolete_renders(tmp_path) == [old]
    prune_renders(tmp_path)
    assert not old.exists()
    assert all(p.exists() for p in [lyrics, karaoke, incomplete, custom])


def test_new_both_supersedes_old_separate_renders(tmp_path):
    old = [make_render(tmp_path, f"20260101-000000-{mode}", [mode]) for mode in ["lyrics", "karaoke"]]
    latest = make_render(tmp_path, "20260102-000000-both", ["lyrics", "karaoke"])
    assert set(obsolete_renders(tmp_path)) == set(old)
    prune_renders(tmp_path)
    assert latest.exists()
