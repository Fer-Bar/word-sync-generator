import logging

import pytest

from colab.karaoke_job import _resolve_song_identity


@pytest.mark.parametrize(('title', 'artist', 'track'), [
    ('Main Artist - Multi Word Title (ft. Guest Singer) (Official Audio)',
     'Main Artist feat. Guest Singer', 'Multi Word Title'),
    ('Artist – Song [Official Music Video]', 'Artist', 'Song'),
    ('Artist — Song (Lyrics)', 'Artist', 'Song'),
    ('Artist | Song (Video Oficial)', 'Artist', 'Song'),
    ('Artist feat. Guest - Song', 'Artist feat. Guest', 'Song'),
    ('Artist - Song feat. Guest', 'Artist feat. Guest', 'Song'),
    ('Artist - Song (Live)', 'Artist', 'Song (Live)'),
    ('Artist - Song (Remix)', 'Artist', 'Song (Remix)'),
    ('North-South - Song', 'North-South', 'Song'),
    ('Artista - Canción (Audio Oficial)', 'Artista', 'Canción'),
    ('BAD BUNNY - BAILE INoLVIDABLE (Video Oficial) | DeBÍ TiRAR MáS FOToS',
     'BAD BUNNY', 'BAILE INoLVIDABLE'),
    ('Another Artist – Another Song [Official Music Video] | New Album', 'Another Artist', 'Another Song'),
    ('Artist - Song (Visualizer) | Album', 'Artist', 'Song'),
    ('Artist - Song (Video Lyrics)', 'Artist', 'Song'),
    ('Artist - Song lyrics', 'Artist', 'Song'),
    ('Artist - Song | Official Lyric Video', 'Artist', 'Song'),
    ('Artista - Canción Video Oficial | Álbum', 'Artista', 'Canción'),
    ('Artist - Song (Live) (Official Video) | Album', 'Artist', 'Song (Live)'),
    ('Artist - Song (Remix) lyrics', 'Artist', 'Song (Remix)'),
    ('Artist - Lyrics of Love', 'Artist', 'Lyrics of Love'),
    ('Artist - Song (lyrics version)', 'Artist', 'Song'),
])
def test_infers_common_music_titles(title, artist, track, caplog):
    with caplog.at_level(logging.DEBUG):
        result = _resolve_song_identity({'title': title, 'uploader': 'Some channel'}, {})
    assert result == {'title': track, 'track': track, 'artist': artist, 'video_title': title}
    assert 'inferred' in caplog.text


@pytest.mark.parametrize(('raw', 'overrides', 'artist', 'track'), [
    ({'title': 'Other - Wrong', 'artist': 'Real', 'track': 'Correct'}, {}, 'Real', 'Correct'),
    ({'title': 'Other - Wrong', 'artist': 'Real', 'track': 'Correct'},
     {'artist': 'Custom', 'title': 'Custom song'}, 'Custom', 'Custom song'),
    ({'title': 'Artist - Song', 'creator': 'Artist'}, {}, 'Artist', 'Song'),
    ({'title': 'Song - Artist', 'artist': 'Artist'}, {}, 'Artist', 'Song'),
    ({'title': 'Song - Artist', 'track': 'Song'}, {}, 'Artist', 'Song'),
    ({'title': 'Song (Official Audio)', 'uploader': 'Artist - Topic'}, {}, 'Artist', 'Song'),
    ({'title': 'Artist - Song'}, {'artist': 'Artist'}, 'Artist', 'Song'),
    ({'title': 'Artist - Song'}, {'title': 'Song'}, 'Artist', 'Song'),
])
def test_metadata_and_override_precedence(raw, overrides, artist, track):
    result = _resolve_song_identity(raw, overrides)
    assert result['artist'] == artist
    assert result['track'] == track


@pytest.mark.parametrize('title', ['Random upload', 'A - B - C', ' - Song', 'Artist - ', 'A - B | C'])
def test_ambiguous_titles_do_not_use_arbitrary_channel_as_artist(title):
    result = _resolve_song_identity({'title': title, 'uploader': 'Music uploads'}, {})
    assert result['artist'] is None
    assert result['track'] == title


def test_conflicting_artist_does_not_infer_track():
    result = _resolve_song_identity({'title': 'Other - Song', 'artist': 'Real'}, {})
    assert result['artist'] == 'Real'
    assert result['track'] == 'Other - Song'


def test_uploaded_identity_service_matches_installed_service(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    from colab import karaoke_job
    from karaoke_app import song_identity

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    shutil.copyfile(Path(song_identity.__file__), inputs / "karaoke_song_identity.py")
    monkeypatch.setattr(karaoke_job, "WORK_DIR", tmp_path)
    raw = {"title": "Artist - Song (Live)", "uploader": "Unrelated Channel"}
    expected = song_identity.resolve_song_identity(raw, {})
    monkeypatch.setattr(song_identity, "resolve_song_identity", lambda *a, **kw: pytest.fail("Used installed service"))
    assert karaoke_job._resolve_song_identity(raw, {}) == expected


@pytest.mark.parametrize('video_title', [
    'Artist - Song (Official Video) | Album',
    'Artist - Song lyrics',
    'Artist - Song [Video Lyrics]',
])
def test_clean_identity_searches_and_selects_closest_duration(video_title, monkeypatch):
    from urllib.parse import parse_qs, urlsplit

    from colab import karaoke_job

    requests = []
    records = [
        {'id': identifier, 'trackName': 'Song', 'artistName': artist, 'duration': duration,
         'syncedLyrics': '[00:01.00] First line\n[00:05.00] Second line'}
        for identifier, artist, duration in [(1, 'Artist', 190), (2, 'Artist', 201),
                                              (3, 'Artist', 200), (4, 'Other', 200)]
    ]

    def request(path):
        params = parse_qs(urlsplit(path).query)
        requests.append(params)
        if path.startswith('/get?'):
            raise OSError('No exact record')
        if params == {'track_name': ['Song'], 'artist_name': ['Artist']}:
            return records
        return []

    monkeypatch.setattr(karaoke_job, '_lrclib_request', request)
    metadata = {**_resolve_song_identity({'title': video_title}, {}), 'duration': 200}
    result = karaoke_job._fetch_lrclib(metadata, {})
    assert result['id'] == 3
    assert {'track_name': ['Song'], 'artist_name': ['Artist']} in requests
    assert {'q': [video_title]} in requests


def test_notebook_youtube_metadata_reaches_preparation_without_swapping_fields(tmp_path, monkeypatch):
    from colab import karaoke_job
    from karaoke_app import notebook, notebook_sources

    source = tmp_path / 'source.mp4'
    source.write_bytes(b'mocked media')
    raw = {'title': 'Singer - Track [Official Video] | Album', 'duration': 200}
    monkeypatch.setattr(notebook_sources, 'download_youtube', lambda *a, **kw: (source, raw))
    monkeypatch.setattr(notebook_sources, 'validate_inputs',
                        lambda paths: {'source': str(source), 'metadata': {}})
    selection = notebook_sources.acquire_youtube('https://www.youtube.com/watch?v=abcdefghijk', tmp_path)
    metadata = selection['metadata']
    assert metadata['title'] == 'Track'
    assert metadata['artist'] == 'Singer'
    config = notebook.preparation_config(source, tmp_path / 'runtime', title=metadata['title'],
                                         artist=metadata['artist'], source_metadata=metadata)
    monkeypatch.setattr(karaoke_job, '_probe_duration', lambda path: 200)
    _, prepared = karaoke_job._acquire_source(config)
    assert prepared['track'] == 'Track'
    assert prepared['artist'] == 'Singer'
    assert prepared['video_title'] == raw['title']


def test_swapped_form_stops_before_preparation_without_changing_fields(tmp_path, monkeypatch):
    from karaoke_app import notebook

    source = tmp_path / 'song.mp4'
    source.write_bytes(b'media')
    metadata = {'video_title': 'BAD BUNNY - BAILE INoLVIDABLE (Video Oficial) | DeBÍ TiRAR MáS FOToS',
                'artist': 'BAD BUNNY', 'track': 'BAILE INoLVIDABLE'}
    monkeypatch.setattr(notebook, '_run_preparation', lambda *a: pytest.fail('Started expensive preparation'))
    with pytest.raises(ValueError, match='parecen invertidos'):
        notebook.prepare_audio(source, output_dir=tmp_path / 'outputs', title='BAD BUNNY',
                               artist='BAILE INoLVIDABLE', source_metadata=metadata)
    assert not (tmp_path / 'outputs').exists()
    assert metadata['artist'] == 'BAD BUNNY'
    config = notebook.preparation_config(source, tmp_path / 'runtime', title='Custom title',
                                         artist='Custom artist', source_metadata=metadata)
    assert config['lyrics']['title'] == 'Custom title'
    assert config['lyrics']['artist'] == 'Custom artist'


@pytest.mark.parametrize('include_exact', [True, False])
def test_exact_lyrics_version_precedes_similar_title_then_falls_back(monkeypatch, include_exact):
    from colab import karaoke_job

    similar = {'id': 1, 'trackName': 'Songs', 'artistName': 'Artist', 'duration': 200,
               'syncedLyrics': '[00:01.00] Similar line'}
    exact = {'id': 2, 'trackName': 'Artist - Song (lyrics version)', 'artistName': 'Artist',
             'duration': 200, 'plainLyrics': 'Exact line'}
    records = [similar, exact] if include_exact else [similar]
    monkeypatch.setattr(karaoke_job, '_lrclib_request', lambda path: records if path.startswith('/search') else None)
    metadata = {'title': 'Artist - Song (Official Video) | Album', 'artist': 'Artist', 'duration': 200}
    selected = karaoke_job._fetch_lrclib(metadata, {})
    assert selected['id'] == (2 if include_exact else 1)
