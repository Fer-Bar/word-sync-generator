from karaoke_app import branding


def test_external_logos_are_stored_once_and_never_overwrite_existing(tmp_path, monkeypatch):
    project = tmp_path / "project"
    logos = project / "logos"
    logos.mkdir(parents=True)
    monkeypatch.setattr(branding, "PROJECT_ROOT", project)
    monkeypatch.setattr(branding, "LOGOS", logos)
    (logos / "custom.png").write_bytes(b"existing")
    external = tmp_path / "custom.png"
    external.write_bytes(b"new-logo")
    first = branding.store_shared_logo(external)
    assert first.startswith("logos/custom-")
    assert branding.store_shared_logo(external) == first
    assert (logos / "custom.png").read_bytes() == b"existing"
    assert (project / first).read_bytes() == external.read_bytes()
    assert branding.store_shared_logo(project / first) == first
    assert len(list(logos.iterdir())) == 2
