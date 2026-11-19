"""HTTP helpers extracted from context routes."""
from helpers.responses import no_cache as private
from helpers.http import authorize


def protect():
    return authorize('RECOMMENDATION_API_TOKEN')
