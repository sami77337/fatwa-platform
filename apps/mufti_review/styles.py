"""Reuse the existing accessible training desk styling with Arabic note input."""
from django.http import HttpResponse
from apps.delivery_queue.author_http import CSS, _private


def stylesheet(request):
    extra = '\n#decision-note{direction:rtl}select{font:inherit;max-width:100%;box-sizing:border-box;padding:.4rem}\n'
    return _private(HttpResponse(CSS + extra, content_type='text/css; charset=utf-8'), head=request.method == 'HEAD')
