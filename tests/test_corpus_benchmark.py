import hashlib
import json

import pytest

from karaoke_app.corpus_benchmark import evaluate_corpus
from karaoke_app.lyrics_file import dump_lyrics_file


@pytest.fixture
def corpus(tmp_path):
    reference = tmp_path / "reference.yaml"
    reference.write_text(dump_lyrics_file({"version": "1.0", "metadata": {"title": "Test"}, "lines": [
        {"text": "hello", "start_ms": 1000, "end_ms": 1500,
         "words": [{"text": "hello", "start_ms": 1000, "end_ms": 1500}]}]}))
    (tmp_path / "original.yaml").write_bytes(reference.read_bytes())
    candidate = tmp_path / "asr.json"
    candidate.write_text(json.dumps({"words": [{"text": "hello", "start": 1.1, "end": 1.6}]}))
    audio, vocals = tmp_path / "audio.webm", tmp_path / "vocals.flac"
    audio.write_bytes(b"original audio")
    vocals.write_bytes(b"fixed stems")
    case = {"id": "song", "reference_status": "user_confirmed_text_and_word_timings",
            "original_reference": "original.yaml", "baselines": [
                {"source": candidate.name, "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest()}]}
    for key, path in [("reference", reference), ("audio", audio), ("vocals", vocals)]:
        case[key] = path.name
        case[f"{key}_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"cases": [case]}))
    return manifest


def test_replay_reports_historical_metrics_without_claiming_fresh_inference(corpus):
    report = evaluate_corpus(corpus, corpus.parent)
    assert report["mode"] == "historical_replay"
    assert not report["fresh_inference_verified"]
    assert report["results"][0]["all_voices"]["timing_on_exact_matches"]["start_mae_ms"] == 100


@pytest.mark.parametrize("filename", ["reference.yaml", "audio.webm", "vocals.flac", "asr.json"])
def test_changed_inputs_fail_instead_of_moving_the_baseline(corpus, filename):
    (corpus.parent / filename).write_bytes(b"changed")
    with pytest.raises(ValueError, match="Corpus input changed"):
        evaluate_corpus(corpus, corpus.parent)


def test_missing_candidate_does_not_silently_skip_a_song(corpus):
    with pytest.raises(FileNotFoundError):
        evaluate_corpus(corpus, corpus.parent, corpus.parent / "missing-candidates")


def test_cli_refuses_to_overwrite_a_reference(corpus, monkeypatch):
    from karaoke_app.corpus_benchmark import main

    reference = corpus.parent / "reference.yaml"
    original = reference.read_bytes()
    monkeypatch.setattr("sys.argv", ["corpus", "--manifest", str(corpus), "--root", str(corpus.parent),
                                    "--output", str(reference)])
    with pytest.raises(SystemExit):
        main()
    assert reference.read_bytes() == original
