import importlib.util
import io
import json
from pathlib import Path
import runpy
from unittest.mock import MagicMock, Mock
from urllib.error import HTTPError, URLError

import pytest
from tests.services.test_catalog import VALID

PATH = Path(__file__).resolve().parents[3] / 'db/ingestion/movies.py'
spec = importlib.util.spec_from_file_location('ingestion_movies', PATH)
ingestion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ingestion)


@pytest.mark.parametrize('token', ['', 'secret'])
def test_download_headers_and_limits(monkeypatch, token):
    fetch = Mock(return_value=io.BytesIO(b'123'))
    monkeypatch.setattr(ingestion, 'urlopen', fetch)
    assert ingestion.download('http://test', token, 3) == b'123'
    request = fetch.call_args.args[0]
    assert request.get_header('Accept') == ('application/json' if token else 'image/jpeg')
    assert request.get_header('Authorization') == ('Bearer secret' if token else None)
    fetch.return_value = io.BytesIO(b'1234')
    with pytest.raises(ValueError, match='size limit'):
        ingestion.download('http://test', token, 3)


@pytest.mark.parametrize('status,attempts', [(404, 1), (429, 4), (500, 4)])
def test_bounded_retry(monkeypatch, status, attempts):
    fetch = Mock(side_effect=HTTPError('http://test', status, 'failure', {}, None))
    sleep = Mock()
    monkeypatch.setattr(ingestion, 'urlopen', fetch)
    monkeypatch.setattr(ingestion.time, 'sleep', sleep)
    with pytest.raises(HTTPError):
        ingestion.download('http://test')
    assert fetch.call_count == attempts
    assert [c.args[0] for c in sleep.call_args_list] == ([1, 2, 4] if attempts == 4 else [])


def test_retry_then_success(monkeypatch):
    monkeypatch.setattr(ingestion, 'urlopen', Mock(side_effect=[HTTPError('http://test', 503, 'failure', {}, None), io.BytesIO(b'ok')]))
    monkeypatch.setattr(ingestion.time, 'sleep', Mock())
    assert ingestion.download('http://test') == b'ok'


@pytest.mark.parametrize('empty', [False, True])
def test_genre_pagination(monkeypatch, empty):
    pages = [{'results': [{'id': 1}], 'total_pages': 2}, {'results': [] if empty else [{'id': 2}], 'total_pages': 2}]
    download = Mock(side_effect=[json.dumps(page) for page in pages])
    monkeypatch.setattr(ingestion, 'download', download)
    assert list(ingestion.tmdb_genre_candidates('token', 1)) == (['1'] if empty else ['1', '2'])
    assert download.call_count == 2


def test_interleaves_and_deduplicates_genres(monkeypatch):
    monkeypatch.setattr(ingestion, 'download', Mock(return_value='{"genres":[{"id":1},{"id":2}]}'))
    monkeypatch.setattr(ingestion, 'tmdb_genre_candidates', lambda token, genre: iter(['1', '2'] if genre == 1 else ['1', '3']))
    assert list(ingestion.tmdb_candidates('token')) == ['1', '3', '2']


def test_genre_feed_stops_at_provider_page_limit(monkeypatch):
    download = Mock(return_value=json.dumps({'results': [{'id': 1}], 'total_pages': 501}))
    monkeypatch.setattr(ingestion, 'download', download)
    assert len(list(ingestion.tmdb_genre_candidates('token', 1))) == 500
    assert download.call_count == 500
    assert download.call_args.args[0].endswith('&page=500')


DETAILS = {'title': 'Title', 'overview': 'Plot', 'runtime': 90, 'genres': [{'name': 'Drama'}],
           'credits': {'cast': [{'name': 'Actor'}], 'crew': [{'name': 'Other', 'job': 'Writer'}, {'name': 'Director', 'job': 'Director'}]},
           'spoken_languages': [{'iso_639_1': ''}, {'iso_639_1': 'en'}], 'production_countries': [{'iso_3166_1': 'PT'}]}


@pytest.mark.parametrize('poster,image', [(None, None), ('bad/path', None), ('/image.jpg', b'\xff\xd8\xffimage'),
                                       ('/image.jpg', b'not jpeg'), ('/image.jpg', URLError('offline'))])
def test_movie_metadata_and_local_poster(monkeypatch, tmp_path, poster, image):
    download = Mock(side_effect=[json.dumps({**DETAILS, 'poster_path': poster}), image])
    monkeypatch.setattr(ingestion, 'download', download)
    movie = ingestion.tmdb_movie('1', 'token', tmp_path)
    assert movie['directors'] == ['Director']
    assert movie['languages'] == ['en']
    assert movie['countries'] == ['PT']
    if isinstance(image, bytes) and image.startswith(b'\xff'):
        assert (tmp_path / movie['poster_key']).read_bytes() == image
        assert not list(tmp_path.glob('*.tmp'))
    else:
        assert movie['poster_key'] is None


def test_incomplete_metadata_is_rejected_before_poster_download(monkeypatch, tmp_path):
    fetch = Mock(return_value=json.dumps({'title': 'Title', 'runtime': 0}))
    monkeypatch.setattr(ingestion, 'download', fetch)
    with pytest.raises(ValueError):
        ingestion.tmdb_movie('1', 'token', tmp_path)
    fetch.assert_called_once()


@pytest.fixture
def cli(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL', 'test-only')
    monkeypatch.setenv('TMDB_READ_TOKEN', 'token')
    monkeypatch.setenv('MOVIE_MEDIA_DIR', str(tmp_path / 'media'))
    monkeypatch.setattr('sys.argv', ['movies', '--count', '1'])
    initialize = Mock()
    monkeypatch.setattr(ingestion.catalog, 'initialize', initialize)
    conn = MagicMock(); conn.__enter__.return_value = conn
    conn.execute.return_value.fetchone.return_value = {'acquired': True}
    conn.execute.return_value.__iter__.return_value = []
    monkeypatch.setattr(ingestion.catalog, 'connect', Mock(return_value=conn))
    monkeypatch.setattr(ingestion, 'tmdb_candidates', Mock(return_value=['1']))
    monkeypatch.setattr(ingestion, 'tmdb_movie', Mock(return_value=VALID))
    monkeypatch.setattr(ingestion.catalog, 'create', Mock(return_value=({}, True)))
    return conn, tmp_path


@pytest.mark.parametrize('case', ['count', 'database', 'token', 'file', 'lock'])
def test_cli_validation(cli, monkeypatch, case):
    conn, tmp_path = cli
    if case == 'count': monkeypatch.setattr('sys.argv', ['movies', '--count', '0'])
    elif case == 'database': monkeypatch.delenv('DATABASE_URL')
    elif case == 'token': monkeypatch.delenv('TMDB_READ_TOKEN')
    elif case == 'file':
        path = tmp_path / 'movies.json'; path.write_text('{}')
        monkeypatch.setattr('sys.argv', ['movies', '--file', str(path)])
    else: conn.execute.return_value.fetchone.return_value = {'acquired': False}
    with pytest.raises(SystemExit) as error: ingestion.main()
    assert error.value.code == 2


def test_online_ingestion(cli, capsys):
    assert ingestion.main() == 0
    output = capsys.readouterr().out
    assert 'Saved 1/1' in output
    assert json.loads(output.splitlines()[-1])['complete'] is True
    ingestion.catalog.create.assert_called_once_with('test-only', VALID)


def test_offline_counts_duplicates_missing_posters_and_errors(cli, monkeypatch, capsys):
    conn, tmp_path = cli
    conn.execute.return_value.__iter__.return_value = [{'source': 'tmdb', 'source_id': 'known'}]
    key = 'a' * 64 + '.jpg'
    media = tmp_path / 'media'; media.mkdir(); (media / key).write_bytes(b'jpeg')
    records = [{**VALID, 'source_id': 'known'}, {}, {**VALID, 'poster_key': 'b' * 64 + '.jpg'},
               {**VALID, 'source_id': 'exists'}, {**VALID, 'source_id': 'new', 'poster_key': key},
               {**VALID, 'source_id': 'invalid', 'duration_minutes': 0}]
    path = tmp_path / 'movies.json'; path.write_text(json.dumps(records))
    monkeypatch.setattr('sys.argv', ['movies', '--file', str(path), '--count', '3'])
    ingestion.catalog.create.side_effect = [({}, False), ({}, True)]
    assert ingestion.main() == 2
    output = capsys.readouterr()
    assert json.loads(output.out.splitlines()[-1]) == {'requested': 3, 'added': 1, 'skipped': 2, 'failed': 3, 'complete': False}
    assert 'Source exhausted' in output.err
    ingestion.tmdb_candidates.assert_not_called()


def test_entrypoint_handles_source_failure(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv('DATABASE_URL', 'test-only')
    monkeypatch.setattr('sys.argv', ['movies', '--file', str(tmp_path / 'missing.json')])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(PATH), run_name='__main__')
    assert error.value.code == 1
    assert 'Earlier inserts remain saved' in capsys.readouterr().err
