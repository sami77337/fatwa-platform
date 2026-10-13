from django.apps import AppConfig


class ReferenceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reference"

    def ready(self) -> None:
        from . import checks  # noqa: F401
