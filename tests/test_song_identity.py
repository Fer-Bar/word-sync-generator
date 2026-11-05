import logging

import pytest

from colab.karaoke_job import _resolve_song_identity


@pytest.mark.parametrize(('title', 'artist', 'track'), [
    ('FKJ - Little Little Voice (ft. Labrinth) (Official Audio)', 'FKJ feat. Labrinth', 'Little Little Voice'),
    ('Artist – Song [Official Music Video]', 'Artist', 'Song'),
    ('Artist — Song (Lyrics)', 'Artist', 'Song'),
    ('Artist | Song (Video Oficial)', 'Artist', 'Song'),
    ('Artist feat. Guest - Song', 'Artist feat. Guest', 'Song'),
    ('Artist - Song feat. Guest', 'Artist feat. Guest', 'Song'),
    ('Artist - Song (Live)', 'Artist', 'Song (Live)'),
    ('Artist - Song (Remix)', 'Artist', 'Song (Remix)'),
    ('AC-DC - Song', 'AC-DC', 'Song'),
    ('Artista - Canción (Audio Oficial)', 'Artista', 'Canción'),
])
def test_infers_common_music_titles(title, artist, track, caplog):
    with caplog.at_level(logging.INFO):
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


@pytest.mark.parametrize('title', ['Random upload', 'A - B - C', ' - Song', 'Artist - '])
def test_ambiguous_titles_do_not_use_arbitrary_channel_as_artist(title):
    result = _resolve_song_identity({'title': title, 'uploader': 'Music uploads'}, {})
    assert result['artist'] is None
    assert result['track'] == title


def test_conflicting_artist_does_not_infer_track():
    result = _resolve_song_identity({'title': 'Other - Song', 'artist': 'Real'}, {})
    assert result['artist'] == 'Real'
    assert result['track'] == 'Other - Song'
