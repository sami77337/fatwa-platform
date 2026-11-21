"""Preserve upstream denial decisions while giving this API a uniform error envelope."""

from .views import failure


class MaterialAPIResponses:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/library-preview/api/v1/materials/") and response.status_code in {400, 403, 404, 405}:
            return failure(response.status_code)
        return response
