"""Shared response helpers for this service."""


def no_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    return response
