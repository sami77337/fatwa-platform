"""Test-only composition of the integrator's three changes, never a runtime middleware."""

from pathlib import Path

from django.template import Context, Engine

from config.campaign_urls import urlpatterns as campaign_patterns

from .assets import urlpatterns as asset_patterns

urlpatterns = [*asset_patterns, *campaign_patterns]


class CaptureComposition:
    """Inject the include inside existing forms without copying/replacing their handlers."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code != 200 or not response.get("Content-Type", "").startswith(
            "text/html"
        ):
            return response
        body = response.content.decode()
        template = Engine.get_default().from_string(
            (Path(__file__).parent / "templates/browser_audio/capture.html").read_text()
        )
        for name in ("attachment", "answer_file"):
            marker = f'name="{name}"'
            position = body.find(marker)
            if position < 0:
                continue
            end = body.index("</form>", position)
            # The integrated native template already contains the real component.
            # Keep this older isolated fixture usable without creating a duplicate.
            if f'data-browser-audio data-input-name="{name}"' in body[position:end]:
                continue
            body = (
                body[:end]
                + template.render(
                    Context(
                        {
                            "audio_capture_enabled": True,
                            "audio_input_name": name,
                        }
                    )
                )
                + body[end:]
            )
        response.content = body.encode()
        if "data-browser-audio" in body:
            policy = response["Content-Security-Policy"]
            if "script-src" not in policy:
                response["Content-Security-Policy"] = (
                    policy.replace("media-src 'self';", "media-src 'self' blob:;")
                    + "; script-src 'self'; worker-src 'self'"
                )
            response["Permissions-Policy"] = "microphone=(self), camera=()"
        return response
