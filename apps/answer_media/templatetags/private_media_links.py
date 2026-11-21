"""Issue current-session locators from the native request, never from DTO grants."""

from urllib.parse import urljoin

from django import template

from apps.private_media.links import enabled, issue

register = template.Library()


@register.simple_tag(takes_context=True)
def private_media_url(context, url, purpose="INLINE"):
    canonical = urljoin(context.request.path, url) if enabled() else url
    return issue(context.request, canonical, purpose=purpose)
