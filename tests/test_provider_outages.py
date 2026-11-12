"""Provider outages must not multiply retries across every search variant."""

from unittest.mock import Mock

import pytest

from colab import karaoke_job as job
from karaoke_app import lyric_references as refs


def test_lrclib_timeout_falls_back_once_and_records_reason(monkeypatch):
    request = Mock(side_effect=TimeoutError("provider offline"))
    monkeypatch.setattr(job.urllib.request, "urlopen", request)
    monkeypatch.setattr(job, "_load_references_module", lambda: refs)
    monkeypatch.setattr(refs, "genius_reference", lambda *args, **kwargs: None)
    record, (document, evidence) = job._prepare_reference(
        {"title": "Test Song", "artist": "Test Artist", "album": "Album", "duration": 120},
        {"lyrics": {}, "language": "en"}, None,
    )
    assert request.call_count == 1
    assert record is None and document is None
    assert evidence["source"] == "whisper"
    assert any(attempt["source"] == "lrclib" and "offline" in attempt["error"] for attempt in evidence["attempts"])


def test_explicit_id_failure_does_not_silently_select_another_reference(monkeypatch):
    monkeypatch.setattr(job.urllib.request, "urlopen", Mock(side_effect=TimeoutError("offline")))
    with pytest.raises(RuntimeError):
        job._fetch_lrclib({}, {"lyrics": {"lrclib_id": 42}})


@pytest.mark.parametrize("code,expected_calls", [(429, 3), (503, 1), (403, 1)])
def test_service_failures_have_one_retry_budget_and_can_use_genius(monkeypatch, code, expected_calls):
    from urllib.error import HTTPError

    request = Mock(side_effect=HTTPError("https://lrclib.net/api/get", code, "unavailable", {}, None))
    monkeypatch.setattr(job.urllib.request, "urlopen", request)
    sleep = Mock()
    monkeypatch.setattr(job.time, "sleep", sleep)
    monkeypatch.setattr(job, "_load_references_module", lambda: refs)
    monkeypatch.setattr(refs, "genius_reference", lambda *args, **kwargs: {
        "source": "genius", "lines": [{"text": "test words"}],
    })
    _, (document, evidence) = job._prepare_reference(
        {"title": "Test Song", "artist": "Test Artist", "duration": 120}, {"lyrics": {}}, None,
    )
    assert request.call_count == expected_calls
    assert sleep.call_count == expected_calls - 1
    assert evidence["source"] == "genius"
    assert evidence["attempts"][0]["status"] == "unavailable"
    assert document["lines"][0]["text"] == "test words"


def test_http_404_can_still_use_search_and_records_no_match(monkeypatch):
    from urllib.error import HTTPError

    calls = []

    def request(path):
        calls.append(path)
        if path.startswith("/get"):
            raise OSError("HTTP 404: not found") from HTTPError("url", 404, "not found", {}, None)
        return []

    monkeypatch.setattr(job, "_lrclib_request", request)
    monkeypatch.setattr(job, "_load_references_module", lambda: refs)
    monkeypatch.setattr(refs, "genius_reference", lambda *args, **kwargs: None)
    _, (_, evidence) = job._prepare_reference(
        {"title": "Test Song", "artist": "Test Artist", "duration": 120}, {"lyrics": {}}, None,
    )
    assert any(path.startswith("/search") for path in calls)
    assert evidence["attempts"][0]["status"] == "no_match"


@pytest.mark.parametrize("error", [ConnectionResetError("connection reset"), TimeoutError("timeout")])
def test_transport_failures_are_provider_failures(monkeypatch, error):
    monkeypatch.setattr(job.urllib.request, "urlopen", Mock(side_effect=error))
    with pytest.raises(job.LyricsProviderUnavailable):
        job._lrclib_request("/search?q=test")


def test_genius_403_is_visible_at_info_without_html(monkeypatch, caplog):
    import logging

    monkeypatch.setattr(job, "_lrclib_request", lambda path: [])

    def denied(*args, **kwargs):
        raise AssertionError("Unexpected response status code: 403. Expected 200 or 204. "
                             "Response body: <!DOCTYPE html><html>blocked</html>")

    monkeypatch.setattr(refs, "genius_reference", denied)
    with caplog.at_level(logging.INFO):
        _, (document, evidence) = job._prepare_reference(
            {"title": "Song", "artist": "Artist", "duration": 120}, {"lyrics": {}}, None,
        )
    assert document is None and evidence["source"] == "whisper"
    failure = next(item for item in evidence["attempts"] if item["source"] == "genius")
    assert failure["http_status"] == 403 and failure["reason"] == "access_denied"
    assert "<html>" not in failure["error"] and "<html>" not in caplog.text
    events = [record.user_event["message"] for record in caplog.records if hasattr(record, "user_event")]
    assert any("HTTP 403" in event for event in events)
    assert any("0 candidatos" in event for event in events)
    assert any("Whisper transcribirá" in event for event in events)


def test_lrclib_selection_and_rejections_are_visible_at_info(monkeypatch, caplog):
    import logging

    records = [
        {"id": 1, "trackName": "Song", "artistName": "Artist", "duration": 120, "plainLyrics": "A line"},
        {"id": 2, "trackName": "Song", "artistName": "Other", "duration": 120, "plainLyrics": "Another line"},
    ]
    monkeypatch.setattr(job, "_lrclib_request", lambda path: records if path.startswith("/search") else None)
    monkeypatch.setattr(refs, "genius_reference", lambda *a, **kw: pytest.fail("Unnecessary Genius request"))
    with caplog.at_level(logging.INFO):
        _, (document, evidence) = job._prepare_reference(
            {"title": "Song", "artist": "Artist", "duration": 120}, {"lyrics": {}}, None,
        )
    assert document and evidence["source"] == "lrclib"
    assert "2 candidatos únicos" in caplog.text
    assert "artist_mismatch" in caplog.text
    assert "seleccionado id=1" in caplog.text
