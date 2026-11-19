"""Versioned filter contract. No prompt generation or inference."""
from datetime import date
import json
from urllib.request import urlopen

CHOICES = ('genres', 'languages')
NAMES = ('actors', 'directors')
COUNTS = (5, 10, 15, 20)
DEFAULT_COUNT = 10
YEAR_MIN = 1888
DURATIONS = [
    {'id': 'any', 'label': 'Any duration', 'min': None, 'max': None},
    {'id': 'short', 'label': 'Under 90 min', 'min': 1, 'max': 89},
    {'id': 'medium', 'label': '90–120 min', 'min': 90, 'max': 120},
    {'id': 'long', 'label': '121–180 min', 'min': 121, 'max': 180},
    {'id': 'epic', 'label': 'Over 180 min', 'min': 181, 'max': 10000},
]


def year_max():
    return date.today().year + 5


def options(movie_url):
    with urlopen(movie_url.rstrip('/') + '/movies/filter-options', timeout=5) as response:
        choices = json.load(response)
    if not isinstance(choices, dict) or any(not isinstance(choices.get(key), list) or
            any(not isinstance(value, str) for value in choices[key]) for key in CHOICES):
        raise ValueError('Invalid catalog filter options')
    return {'version': 1, 'choices': {key: choices[key] for key in CHOICES}, 'durations': DURATIONS,
            'year_min': YEAR_MIN, 'year_max': year_max(), 'counts': list(COUNTS),
            'max_selections': 10, 'generation_available': False}


def validate(data, available):
    if not isinstance(data, dict) or set(data) - {*CHOICES, *NAMES, 'year_from', 'year_to', 'duration', 'count'}:
        raise ValueError('Provide predefined filters only.')
    result = {}
    for key in CHOICES:
        values = data.get(key, [])
        allowed = set(available['choices'][key])
        if not isinstance(values, list) or len(values) > 10 or any(
                not isinstance(value, str) or value not in allowed for value in values):
            raise ValueError(f'Select up to 10 available {key}.')
        result[key] = list(dict.fromkeys(values))
    for key in NAMES:
        values = data.get(key, [])
        if not isinstance(values, list) or len(values) > 10 or any(
                not isinstance(value, str) or not 1 <= len(value.strip()) <= 200 or
                any(ord(char) < 32 for char in value) for value in values):
            raise ValueError(f'Provide up to 10 {key} names, 1–200 characters each.')
        unique = {}
        for value in values:
            unique.setdefault(value.strip().casefold(), value.strip())
        result[key] = list(unique.values())
    for key in ('year_from', 'year_to'):
        value = data.get(key)
        if value is not None and (type(value) is not int or not available['year_min'] <= value <= available['year_max']):
            raise ValueError(f'{key} must be a valid release year.')
        result[key] = value
    if result['year_from'] is not None and result['year_to'] is not None and result['year_from'] > result['year_to']:
        raise ValueError('Release year range is reversed.')
    result['duration'] = data.get('duration', 'any')
    result['count'] = data.get('count', DEFAULT_COUNT)
    if result['duration'] not in [entry['id'] for entry in DURATIONS]:
        raise ValueError('Select an available duration.')
    if type(result['count']) is not int or result['count'] not in available['counts']:
        raise ValueError('Select 5, 10, 15, or 20 recommendations.')
    return result


def validate_offline(data):
    """Structural validation of filters with no Movie Service access, so it can run before any external call.

    Everything validate() checks is checked (structure, limits, years, duration, count) except that a genre or
    language exists: that needs the catalog, see catalog_options(). None means no filters.
    """
    data = {} if data is None else data
    if not isinstance(data, dict):
        raise ValueError('Provide predefined filters only.')
    choices = {key: [value for value in data[key] if isinstance(value, str)] if isinstance(data.get(key), list) else []
               for key in CHOICES}
    return validate(data, {'choices': choices, 'year_min': YEAR_MIN, 'year_max': year_max(), 'counts': COUNTS})


def catalog_options(catalog):
    """The available genre and language choices of an already fetched catalog, ready for validate().

    These are exactly the values Movie Service's /movies/filter-options lists (the distinct non-empty genres
    and languages of its movies), obtained without a second request.
    """
    return {'choices': {'genres': sorted({value for movie in catalog for value in movie['genres'] if value}),
                        'languages': sorted({value for movie in catalog for value in movie['languages'] if value})},
            'year_min': YEAR_MIN, 'year_max': year_max(), 'counts': COUNTS}
