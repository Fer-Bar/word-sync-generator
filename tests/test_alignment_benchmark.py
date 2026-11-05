from karaoke_app.alignment_benchmark import compare_alignment


def test_report_cannot_overwrite_either_input_or_link(tmp_path, monkeypatch):
    import pytest

    from karaoke_app.alignment_benchmark import main

    reference = tmp_path / "reference.yaml"
    candidate = tmp_path / "candidate.json"
    reference.write_bytes(b"manual reference must survive")
    candidate.write_bytes(b"candidate must survive")
    alias = tmp_path / "alias.json"
    alias.symlink_to(reference)
    hardlink = tmp_path / "hardlink.json"
    hardlink.hardlink_to(candidate)
    for output in (reference, candidate, alias, hardlink):
        monkeypatch.setattr("sys.argv", ["benchmark", str(reference), str(candidate), "--output", str(output)])
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == 2
        assert reference.read_bytes() == b"manual reference must survive"
        assert candidate.read_bytes() == b"candidate must survive"


def document(words):
    return {"lines": [{"words": words}]}


def word(text, start, **extra):
    return {"text": text, "start_ms": start, "end_ms": start + 200, **extra}


def test_reports_edits_separately_from_timing_on_matches():
    reference = document([word("One", 100), word("two", 400), word("three", 700)])
    candidate = document([word("ONE!", 150), word("different", 400)])
    report = compare_alignment(reference, candidate)
    assert report["operations"] == {"match": 1, "substitution": 1, "deletion": 1, "insertion": 0}
    assert report["token_error_rate"] == 2 / 3
    assert report["timing_on_exact_matches"]["start_mae_ms"] == 50


def test_background_is_evaluated_separately_and_ids_are_not_assumed_correct():
    reference = document([word("lead", 100, agent="v2"), word("echo", 150, isBackground=True)])
    candidate = document([word("lead", 100)])
    assert compare_alignment(reference, candidate)["token_error_rate"] == 0
    assert compare_alignment(reference, candidate, include_background=True)["operations"]["deletion"] == 1
    assert compare_alignment(reference, candidate)["candidate_agents"] == {"unassigned": 1}


def test_reports_raw_offset_without_silently_correcting_it():
    reference = document([word("hello", 100)])
    candidate = document([word("hello", 1100)])
    metrics = compare_alignment(reference, candidate)["timing_on_exact_matches"]
    assert metrics["start_mae_ms"] == 1000
    assert metrics["median_signed_start_delta_ms"] == 1000


def test_background_classification_reports_missed_and_extra_labels():
    reference = document([
        word("lead", 0), word("echo", 100, isBackground=True), word("soft", 200, isBackground=True),
        word("missing", 300, isBackground=True),
    ])
    candidate = document([
        word("lead", 0, isBackground=True), word("echo", 100, isBackground=True), word("soft", 200),
    ])
    report = compare_alignment(reference, candidate, include_background=True)
    assert report["background_on_exact_matches"] == {
        "true_positive": 1, "false_positive": 1, "false_negative": 1, "precision": 0.5, "recall": 0.5,
        "reference_background_tokens": 3, "candidate_background_tokens": 2,
    }
    assert report["operations"]["deletion"] == 1


def test_no_matches_has_no_timing_score():
    report = compare_alignment(document([word("a", 0)]), document([word("b", 0)]))
    assert report["timing_on_exact_matches"]["start_mae_ms"] is None
    assert report["matched_reference_fraction"] == 0


def test_saved_transcription_keeps_raw_times_and_channel_fields(tmp_path):
    import json

    from karaoke_app.alignment_benchmark import load_benchmark_candidate

    path = tmp_path / "transcription.json"
    path.write_text(json.dumps({"segments": [{"agent": "singer", "words": [
        {"text": "word", "start": 1.234, "end": 1.234, "isBackground": True}]}]}))
    result = load_benchmark_candidate(path)
    assert result["lines"][0]["agent"] == "singer"
    item = result["lines"][0]["words"][0]
    assert item["start_ms"] == item["end_ms"] == 1234
    assert item["isBackground"]


def test_saved_alignment_is_compared_without_lyrics_reference_input(tmp_path):
    import json

    from karaoke_app.alignment_benchmark import load_benchmark_candidate

    path = tmp_path / "alignment.json"
    path.write_text(json.dumps({"words": [{"text": "hello", "start": 0.2, "end": 0.5}]}))
    report = compare_alignment(document([word("hello", 100)]), load_benchmark_candidate(path))
    assert report["timing_on_exact_matches"]["start_mae_ms"] == 100


def test_saved_candidate_rejects_missing_or_invalid_timings(tmp_path):
    import json

    import pytest

    from karaoke_app.alignment_benchmark import load_benchmark_candidate

    path = tmp_path / "alignment.json"
    for words in [[], [{"text": "hello", "start": 1}], [{"text": "hello", "start": 2, "end": 1}]]:
        path.write_text(json.dumps({"words": words}))
        with pytest.raises(ValueError):
            load_benchmark_candidate(path)
