"""Read guard for the coordinator's canonical approval and downstream-use boundary.

Importable even if this app is omitted from INSTALLED_APPS: restored annotations
must fail closed. This module does not monkey-patch casework or grant publication.
"""

from django.apps import apps
from django.conf import settings
from django.db import connection

from apps.casework import services as cases
from apps.source_rights.services import projection_expiry_guard


def require_for_answer(answer, *, actor=None, provider=None):
    """Return earliest exact-right expiry; caller owns the case lock and use boundary.

    Supply the authenticated scholarly actor before approval. Otherwise resolve
    the recorded approver with its original provider and epoch. The coordinator
    must retain this expiry until its entire final response/transaction completes.
    """
    if answer is None:
        return None
    if not connection.in_atomic_block:
        raise cases.CaseConflict("pdf_case_lock_required")
    table = "pdf_citations_pdfcitation"
    if not apps.is_installed("apps.pdf_citations"):
        if table in connection.introspection.table_names():
            with connection.cursor() as cursor:
                cursor.execute(
                    'SELECT 1 FROM "pdf_citations_pdfcitation" WHERE answer_id = %s LIMIT 1',
                    [answer.pk],
                )
                if cursor.fetchone():
                    raise cases.CaseConflict("pdf_citation_schema_unavailable")
        return None
    from .models import PdfCitation

    if not PdfCitation.objects.filter(answer=answer).exists():
        return None
    if actor is None:
        decision = getattr(answer, "decision", None)
        provider = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        if (
            decision is None
            or decision.action != "APPROVE"
            or provider is None
            or getattr(provider, "provider_id", None) != decision.provider_id
        ):
            raise cases.CaseConflict("pdf_approval_authority_unavailable")
        actor = cases._identity(provider, decision.subject_id, answer.case)
        if actor.auth_epoch != decision.auth_epoch:
            raise cases.CaseConflict("pdf_approval_authority_changed")
    if provider is None:
        raise cases.CaseConflict("pdf_approval_authority_unavailable")
    from .services import for_locked_answer

    with projection_expiry_guard() as deadlines:
        for_locked_answer(answer=answer, actor=actor, provider=provider)
        return min(deadlines, default=None)
