import io
import json
from datetime import date
from unittest.mock import Mock

import pytest
from services import filters


@pytest.fixture
def available(monkeypatch):
    fetch = Mock(return_value=io.BytesIO(json.dumps({'genres': ['Drama'], 'languages': ['en']}).encode()))
    monkeypatch.setattr(filters, 'urlopen', fetch)
    result = filters.options('http://movies/')
    fetch.assert_called_once_with('http://movies/movies/filter-options', timeout=5)
    assert result['year_max'] == date.today().year + 5
    assert result['generation_available'] is False
    return result


@pytest.mark.parametrize('body', [[], {}, {'genres': 'Drama', 'languages': []}, {'genres': [1], 'languages': []}])
def test_invalid_catalog_options(monkeypatch, body):
    monkeypatch.setattr(filters, 'urlopen', lambda *a, **kw: io.BytesIO(json.dumps(body).encode()))
    with pytest.raises(ValueError, match='Invalid catalog'):
        filters.options('http://movies')


def test_defaults_and_normalization(available):
    result = filters.validate({}, available)
    assert result == {'genres': [], 'languages': [], 'actors': [], 'directors': [],
                      'year_from': None, 'year_to': None, 'duration': 'any', 'count': 10}
    result = filters.validate({'genres': ['Drama', 'Drama'], 'actors': [' Name ', 'name'],
                               'year_from': 1888, 'year_to': available['year_max'], 'count': 5}, available)
    assert result['genres'] == ['Drama']
    assert result['actors'] == ['Name']
    assert result['year_from'] == 1888


@pytest.mark.parametrize('data', [None, {'extra': 1}, {'genres': 'Drama'}, {'genres': ['Drama'] * 11},
    {'genres': [1]}, {'genres': ['missing']}, {'actors': 'name'}, {'actors': ['a'] * 11},
    {'actors': [1]}, {'actors': ['']}, {'actors': ['a' * 201]}, {'actors': ['a\nb']},
    {'year_from': True}, {'year_from': 1887}, {'year_to': 9999},
    {'year_from': 2000, 'year_to': 1999}, {'duration': 'missing'}, {'count': True}, {'count': 6}])
def test_reject_invalid_filters(available, data):
    with pytest.raises(ValueError):
        filters.validate(data, available)


# --- offline validation used by the recommendation pipeline -----------------------------------------------------

def test_count_and_year_constants_match_the_published_options(available):
    assert filters.COUNTS == (5, 10, 15, 20) and filters.DEFAULT_COUNT == 10 and filters.YEAR_MIN == 1888
    assert available['counts'] == list(filters.COUNTS) and available['year_min'] == filters.YEAR_MIN
    assert available['year_max'] == filters.year_max() == date.today().year + 5


def test_offline_validation_defaults_and_normalization_equal_the_live_validator(available):
    assert filters.validate_offline(None) == filters.validate({}, available) == {
        'genres': [], 'languages': [], 'actors': [], 'directors': [], 'year_from': None, 'year_to': None,
        'duration': 'any', 'count': 10}
    data = {'genres': ['Drama', 'Drama'], 'languages': ['en'], 'actors': [' Name ', 'name'], 'directors': ['D'],
            'year_from': 1888, 'year_to': available['year_max'], 'duration': 'long', 'count': 20}
    assert filters.validate_offline(data) == filters.validate(data, available)
    assert filters.validate_offline({}) == filters.validate_offline(None)


def test_offline_validation_does_not_check_catalog_membership_or_mutate_its_input():
    data = {'genres': ['Western'], 'languages': ['xx']}
    assert filters.validate_offline(data)['genres'] == ['Western'] and data == {'genres': ['Western'], 'languages': ['xx']}


@pytest.mark.parametrize('data', [{'extra': 1}, {'genres': 'Drama'}, {'genres': ['Drama'] * 11}, {'genres': [1]}, {'genres': None},
    {'languages': 'en'}, {'languages': [None]}, {'actors': 'name'}, {'actors': ['a'] * 11}, {'actors': [1]}, {'actors': ['']},
    {'actors': ['a' * 201]}, {'actors': ['a\nb']}, {'year_from': True}, {'year_from': 1887}, {'year_to': 9999},
    {'year_from': 2000, 'year_to': 1999}, {'duration': 'missing'}, {'count': True}, {'count': 6}, {'count': '10'}, {'count': None},
    'drama', 5, ['x'], 0])
def test_offline_validation_rejects_everything_the_live_validator_rejects_except_membership(data):
    with pytest.raises(ValueError):
        filters.validate_offline(data)


# --- catalog-derived options (genre/language membership without a second request) ---------------------------------

def movie(genres, languages):
    return {'genres': genres, 'languages': languages}


def test_catalog_options_list_the_distinct_sorted_non_empty_values():
    options = filters.catalog_options([movie(['Drama', 'Action'], ['en']), movie(['Drama'], ['fr', 'en']), movie([], []), movie(['', 'Comedy'], [''])])
    assert options['choices'] == {'genres': ['Action', 'Comedy', 'Drama'], 'languages': ['en', 'fr']}
    assert filters.catalog_options([])['choices'] == {'genres': [], 'languages': []}


def test_catalog_options_equal_what_the_movie_service_endpoint_lists(monkeypatch):
    catalog = [movie(['Drama', 'Action'], ['en']), movie(['Drama'], ['fr', 'en']), movie(['Western'], ['en'])]
    endpoint = {'genres': sorted({g for m in catalog for g in m['genres']}), 'languages': sorted({l for m in catalog for l in m['languages']})}
    monkeypatch.setattr(filters, 'urlopen', lambda *a, **kw: io.BytesIO(json.dumps(endpoint).encode()))
    assert filters.catalog_options(catalog)['choices'] == filters.options('http://movies')['choices']


def test_catalog_options_complete_the_existing_validator_and_keep_its_semantics():
    options = filters.catalog_options([movie(['Drama', 'Action'], ['en'])])
    assert filters.validate({'genres': ['Drama'], 'languages': ['en']}, options)['genres'] == ['Drama']
    assert filters.validate({}, options) == filters.validate_offline(None)
    for bad in ({'genres': ['Western']}, {'genres': ['drama']}, {'languages': ['fr']}, {'languages': ['EN']}, {'genres': ['Drama', 'Nope']}):
        with pytest.raises(ValueError, match='available'):
            filters.validate(bad, options)
    assert options['year_min'] == filters.YEAR_MIN and options['year_max'] == filters.year_max() and options['counts'] == filters.COUNTS


def test_catalog_options_do_not_mutate_the_catalog():
    catalog = [movie(['Drama'], ['en'])]
    snapshot = [dict(m, genres=list(m['genres']), languages=list(m['languages'])) for m in catalog]
    filters.catalog_options(catalog)
    assert catalog == snapshot
