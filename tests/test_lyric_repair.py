"""Local repair applies reference text and preserves independent ASR evidence."""

import json
import shlex

from colab import karaoke_job as job
from karaoke_app import lyric_repair
from karaoke_app.lyrics_file import dump_lyrics_file


def _transcript(text, *, probability=0.95):
    words = [
        {"text": word, "start": 1 + i * 0.5, "end": 1.3 + i * 0.5, "probability": probability}
        for i, word in enumerate(text.split())
    ]
    return {"segments": [{"words": words}]}


def _make_job(tmp_path, asr_text, reference_text):
    lyrics = job._transcript_to_lyrics(
        {
            "song": {"title": "Song", "artist": "Artist", "duration": 60},
            "transcription": {"language": "en"},
            "segments": _transcript(asr_text)["segments"],
        }
    )
    (tmp_path / "lyrics.lyricsfile.yaml").write_text(dump_lyrics_file(lyrics), encoding="utf-8")
    (tmp_path / "transcription.json").write_text(json.dumps(_transcript(asr_text)), encoding="utf-8")
    document = {
        "title": "Song",
        "source": {
            "title": "Song",
            "track": "Song",
            "artist": "Artist",
            "source_url": "https://example.test/video",
        },
        "preparation": {},
        "media": {"lyrics": "lyrics.lyricsfile.yaml"},
    }
    (tmp_path / ".karaoke").mkdir(exist_ok=True)
    (tmp_path / ".karaoke/project.json").write_text(json.dumps(document), encoding="utf-8")
    (tmp_path / "alignment.json").write_text(json.dumps({"segmentation": "heuristic"}), encoding="utf-8")
    pipeline = tmp_path / "pipeline.py"
    pipeline.write_text(
        "def _lrclib_candidate_is_safe(candidate, *, track, artist, duration):\n    return True\n",
        encoding="utf-8",
    )
    reference = {
        "source": "genius",
        "id": 1,
        "url": "https://genius.com/Artist-song-lyrics",
        "original_text": reference_text,
        "lines": [{"text": line} for line in reference_text.splitlines()],
        "metadata": {"title": "Song", "artist": "Artist"},
    }
    return pipeline, reference


def test_realign_hint_points_to_reference_txt(tmp_path):
    hint = lyric_repair._realign_hint(tmp_path, {"title": "Song", "source": {"title": "Song", "artist": "Artist"}})
    assert "--lyrics-text" in hint and str(tmp_path / "reference.txt") in hint


def test_repair_reports_reference_applied(tmp_path, monkeypatch):
    pipeline, reference = _make_job(tmp_path, "hitting them corners and clerks", "Hitting them corners and curbs")
    monkeypatch.setattr(lyric_repair, "genius_reference", lambda *a, **k: reference)
    result = lyric_repair.repair_prepared_lyrics(tmp_path, pipeline)
    assert result["status"] == "repaired"
    assert result["text_action"] == "reference_applied"
    assert result["estimated_words"] == 1
    assert "--lyrics-text" in result["realign_hint"]
    alignment = json.loads((tmp_path / "alignment.json").read_text(encoding="utf-8"))
    assert alignment["text_action"] == "reference_applied"
    assert alignment["strategy"] == "reference_text_asr_timing"
    assert "curbs" in (tmp_path / "lyrics.lyricsfile.yaml").read_text(encoding="utf-8")


def test_repair_reports_cosmetic_when_only_punctuation_differs(tmp_path, monkeypatch):
    pipeline, reference = _make_job(tmp_path, "Only Saturdays on late nights", "Only Saturdays, on late nights")
    monkeypatch.setattr(lyric_repair, "genius_reference", lambda *a, **k: reference)
    result = lyric_repair.repair_prepared_lyrics(tmp_path, pipeline)
    assert result["text_action"] == "reference_applied"
    assert result["estimated_words"] == 0
    assert "Only Saturdays," in (tmp_path / "lyrics.lyricsfile.yaml").read_text()


def test_repair_marks_reference_disagreement_even_when_asr_matches_output(tmp_path, monkeypatch):
    pipeline, reference = _make_job(tmp_path, "hitting them corners and clerks", "Hitting them corners and curbs")
    monkeypatch.setattr(lyric_repair, "genius_reference", lambda *a, **k: reference)
    lyric_repair.repair_prepared_lyrics(tmp_path, pipeline)
    validation = json.loads((tmp_path / "lyrics_validation.json").read_text())
    alignment = json.loads((tmp_path / "alignment.json").read_text())
    assert validation["needs_review"] and alignment["needs_review"]
    assert validation["line_basis"] == "reference"
    assert validation["lines"][0]["missing_or_different"] == ["curbs"]
    assert validation["realign_hint"] == alignment["realign_hint"]


def test_realign_hint_quotes_shell_arguments(tmp_path):
    title = 'Song "live" $(touch nope)'
    directory = tmp_path / "my outputs" / "song"
    hint = lyric_repair._realign_hint(directory, {"source": {"title": title, "source_url": "https://a/?v=1&x=2"}})
    args = shlex.split(hint)
    assert args[args.index("--title") + 1] == title
    assert args[args.index("--lyrics-text") + 1] == str(directory / "reference.txt")
    assert args[args.index("--output-dir") + 1] == str(directory.parent)


def test_realign_hint_is_accepted_by_preparation_parser(tmp_path):
    from karaoke_app.cli import build_parser

    url = "https://example.test/song"
    hint = lyric_repair._realign_hint(tmp_path, {"source": {"title": "Song", "source_url": url}})
    args = build_parser().parse_args(shlex.split(hint)[3:])
    assert args.source == url
    assert args.lyrics_text == tmp_path / "reference.txt"


def test_saved_reference_repairs_already_grouped_job_without_provider(tmp_path, monkeypatch):
    pipeline, reference = _make_job(tmp_path, "I see a bird", "I see a bear")
    (tmp_path / "reference.txt").write_text("I see a bear\n")
    (tmp_path / "alignment.json").write_text(json.dumps({"segmentation": "reference"}))
    (tmp_path / "lyrics_reference.json").write_text(json.dumps({"source": "lrclib"}))
    def no_provider(*args, **kwargs):
        raise AssertionError("Saved text must take precedence")
    monkeypatch.setattr(lyric_repair, "genius_reference", no_provider)
    speech = (tmp_path / "transcription.json").read_bytes()
    result = lyric_repair.repair_prepared_lyrics(tmp_path, pipeline)
    assert result["status"] == "repaired"
    assert not list(tmp_path.glob("lyrics-backup-*"))
    assert (tmp_path / "transcription.json").read_bytes() == speech
    assert "bear" in (tmp_path / "lyrics.srt").read_text()
    alignment = json.loads((tmp_path / "alignment.json").read_text())
    assert alignment["text_source"] == "lrclib"
    assert alignment["words"][-1]["text"] == "bear"
    assert lyric_repair.repair_prepared_lyrics(tmp_path, pipeline)["reason"] == "reference_text_already_applied"


def test_repair_adds_agents_to_unchanged_text_and_preserves_headers(tmp_path):
    from karaoke_app.lyrics_file import load_lyrics_file

    pipeline, _ = _make_job(tmp_path, "Sing this", "Sing this")
    text = "[Verse 1: Drake,\nDon Toliver\n]\nSing this\n"
    (tmp_path / "reference.txt").write_text(text)
    result = lyric_repair.repair_prepared_lyrics(tmp_path, pipeline)
    assert result["status"] == "repaired"
    assert result["estimated_words"] == 0
    assert (tmp_path / "reference.txt").read_text() == text
    lyrics = load_lyrics_file(tmp_path / "lyrics.lyricsfile.yaml")
    assert lyrics["lines"][0]["agent"] == "Drake, Don Toliver"
    assert lyric_repair.repair_prepared_lyrics(tmp_path, pipeline)["status"] == "skipped"


def test_repair_adds_background_to_unchanged_text_once(tmp_path):
    from karaoke_app.lyrics_file import load_lyrics_file

    pipeline, _ = _make_job(tmp_path, "Sing (oh yeah)", "Sing (oh yeah)")
    (tmp_path / "reference.txt").write_text("Sing (oh yeah)")
    before = load_lyrics_file(tmp_path / "lyrics.lyricsfile.yaml")
    result = lyric_repair.repair_prepared_lyrics(tmp_path, pipeline)
    assert result["status"] == "repaired"
    assert result["estimated_words"] == 0
    lyrics = load_lyrics_file(tmp_path / "lyrics.lyricsfile.yaml")
    words = lyrics["lines"][0]["words"]
    assert [bool(w.get("isBackground")) for w in words] == [False, True, True]
    assert [(w["start_ms"], w["end_ms"]) for w in words] == [
        (w["start_ms"], w["end_ms"]) for w in before["lines"][0]["words"]
    ]
    assert lyric_repair.repair_prepared_lyrics(tmp_path, pipeline)["status"] == "skipped"


def test_failed_repair_restores_original_files(tmp_path, monkeypatch):
    from pathlib import Path

    import pytest

    pipeline, _ = _make_job(tmp_path, "I see a bird", "I see a bear")
    (tmp_path / "reference.txt").write_text("I see a bear\n")
    originals = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    replace = Path.replace

    def fail_srt(self, target):
        if self.name == ".lyrics.srt.repair":
            raise OSError("disk full")
        return replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_srt)
    with pytest.raises(OSError, match="disk full"):
        lyric_repair.repair_prepared_lyrics(tmp_path, pipeline)
    assert all((tmp_path / name).read_bytes() == data for name, data in originals.items())
    assert not list(tmp_path.glob("lyrics-backup-*"))
    assert not list(tmp_path.glob(".*.repair"))
