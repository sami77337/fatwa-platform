"""Additional locked predicates from V11 C; no rights records or policy replacement.

Only called by workspace services after their owned-DB/canonical-case/identity
checks. Missing app/configuration/registration/review/usage is closed by default.
"""

from django.apps import apps
from django.db import connection

from apps.casework.models import Case
from apps.knowledge_links.models import KnowledgeRevision
from apps.reference.models import ReferenceEdition
from apps.transcript_case_links.models import TranscriptLink

from .rights import ResearchRights


class SourceRightsAdapter(ResearchRights):
    def __init__(self, *, media_rights=None):
        # The C ledger covers TOC and transcripts, not case-owned media. No
        # inferred READ_MEDIA grant: an additional explicit policy is required.
        self.media_rights = media_rights

    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action, resource):
        if not connection.in_atomic_block:
            return False
        if resource.kind in {"ATTACHMENT", "ANSWER_MEDIA"}:
            return (
                action in {"DISCOVER", "READ_MEDIA"}
                and isinstance(self.media_rights, ResearchRights)
                and self.media_rights.permits(
                    provider_id=provider_id,
                    subject_id=subject_id,
                    auth_epoch=auth_epoch,
                    case_ref=case_ref,
                    action=action,
                    resource=resource,
                )
                is True
            )
        if not apps.is_installed("apps.source_rights"):
            return False
        from apps.source_rights import services as ledger
        from apps.source_rights.models import SourceRegistration

        from . import services as workspace

        case = Case.objects.filter(public_ref=case_ref).first()
        if case is None:
            return False

        def reference(source, usage):
            return ledger.permits_reference_for_locked_case(case=case, source=source, usage=usage)

        def transcript(identifier, usage):
            return ledger.permits_transcript_for_locked_case(
                case=case, transcript_id=identifier, usage=usage
            )

        if resource.kind == "EDITION" and action == "DISCOVER":
            edition = (
                ReferenceEdition.objects.select_related("work")
                .filter(pk=resource.edition_id)
                .first()
            )
            if edition is None or workspace._edition_resource(edition) != resource:
                return False
            # Showing an edition selector means at least one exact position is
            # readable in this case. It grants nothing to any other heading.
            registrations = SourceRegistration.objects.filter(
                case=case,
                source__heading__edition=edition,
            ).select_related("source")[:64]
            return any(
                reference(
                    {key: row.source.snapshot[key] for key in ("source", "source_sha256")}, "READ"
                )
                for row in registrations
            )
        if resource.kind == "REFERENCE":
            if action not in {"DISCOVER", "READ_METADATA", "CITE"}:
                return False
            edition_id, row_id = [int(v) for v in resource.identifier.split(":")]
            source = workspace.citations._source(edition_id, row_id)
            return workspace._source_resource(
                source["source"], source["source_sha256"]
            ) == resource and reference(source, "CITE" if action == "CITE" else "READ")
        if resource.kind == "TRANSCRIPT":
            if action not in {"DISCOVER", "READ_METADATA", "SEARCH_TEXT", "READ_TEXT"}:
                return False
            row = (
                TranscriptLink.objects.filter(pk=resource.identifier, case=case)
                .select_related("upload")
                .first()
            )
            return (
                row is not None
                and workspace._digest([row.upload.sha256, row.question_sha256]) == resource.sha256
                and transcript(row.pk, "READ")
            )
        if resource.kind == "KNOWLEDGE":
            if action not in {"DISCOVER", "READ_METADATA"}:
                return False
            row = KnowledgeRevision.objects.filter(
                pk=resource.identifier, publication__case=case
            ).first()
            if row is None or row.snapshot_sha256 != resource.sha256:
                return False
            if row.heading_id:
                source = {key: row.snapshot[key] for key in ("source", "source_sha256")}
                return reference(source, "READ") and reference(source, "RELATE")
            return (
                bool(row.transcript_id)
                and transcript(row.transcript_id, "READ")
                and transcript(row.transcript_id, "RELATE")
            )
        return False
