"""Native advanced filters over explicit approved lesson and manual relationships.

This is separate from full-text source retrieval. Missing organization never
removes a text match unless a human explicitly chooses the corresponding filter.
"""


def search(**kwargs):
    from apps.scholarly_links.services import search as scholarly_search

    return scholarly_search(**kwargs)
