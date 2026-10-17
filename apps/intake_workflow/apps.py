from django.apps import AppConfig
from django.db.models.signals import pre_migrate


class IntakeWorkflowConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.intake_workflow'

    def ready(self):
        from .guards import require_owned_migration
        pre_migrate.connect(require_owned_migration, dispatch_uid='wave7.owned-migrations', weak=False)
