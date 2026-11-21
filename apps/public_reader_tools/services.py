"""Whole-response publication and tool authority checks; saved references are local."""

import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import Case
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.experimental_publication.models import PublicationEdition
from apps.library_preview import services as preview
from apps.platform_recovery.integration import mutation_context
from apps.public_answer_media import public as recording_public
from apps.public_answer_media.boundaries import _epoch, core_state, identity_pin

from .authority import ReaderGrant, ReaderToolsAuthority

ACTIONS = ("SAVE_REFERENCE", "SHARE_LINK", "PRINT", "DOWNLOAD_TEXT")


def enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_PUBLIC_READER_TOOLS_ENABLED", False) is not True
    ):
        raise preview.PreviewUnavailable()


@dataclass
class Boundary:
    authority: object
    directory: object
    authority_epoch: str
    directory_epoch: str
    case: object
    source: object
    canonical: object
    grants: dict = field(default_factory=dict)
    actors: dict = field(default_factory=dict)
    deadlines: list = field(default_factory=list)

    def check_state(self):
        enabled()
        if (
            getattr(settings, "FATWA_PUBLIC_READER_TOOLS_AUTHORITY", None) is not self.authority
            or getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None) is not self.directory
            or _epoch(self.authority, "projection_epoch") != self.authority_epoch
            or _epoch(self.directory, "projection_epoch") != self.directory_epoch
            or core_state(self.case.pk) != self.canonical
            or any(timezone.now() >= deadline for deadline in self.deadlines)
        ):
            raise preview.PreviewUnavailable()

    def permission(self, action, *, required=False):
        try:
            grant = self.authority.grant(
                publication_id=str(self.source.pk),
                content_sha256=self.source.content_sha256,
                action=action,
            )
        except Exception as exc:
            raise preview.PreviewUnavailable() from exc
        if grant is None:
            if required:
                raise preview.PreviewUnavailable()
            return False
        if type(grant) is not ReaderGrant or (
            grant.publication_id != str(self.source.pk)
            or grant.content_sha256 != self.source.content_sha256
            or grant.action != action
            or grant.provider_id != self.directory.provider_id
            or any(
                type(value) is not str or not 1 <= len(value) <= 128
                for value in (grant.provider_id, grant.subject_id, grant.auth_epoch)
            )
            or not isinstance(grant.valid_until, datetime)
            or timezone.is_naive(grant.valid_until)
            or grant.valid_until <= timezone.now()
            or grant.valid_until > timezone.now() + timedelta(hours=1)
        ):
            raise preview.PreviewUnavailable()
        actor = cases._identity(self.directory, grant.subject_id, self.case)
        if actor.auth_epoch != grant.auth_epoch:
            raise preview.PreviewUnavailable()
        previous = self.grants.get(action)
        if previous is not None and previous != grant:
            raise preview.PreviewUnavailable()
        self.grants[action] = grant
        self.actors[actor.subject_id] = identity_pin(actor)
        self.deadlines.extend((grant.valid_until, actor.valid_until))
        return True

    def finish(self):
        for action in tuple(self.grants):
            self.permission(action, required=True)
        for subject, expected in self.actors.items():
            if identity_pin(cases._identity(self.directory, subject, self.case)) != expected:
                raise preview.PreviewUnavailable()
        self.check_state()


def _boundary(source):
    enabled()
    authority = getattr(settings, "FATWA_PUBLIC_READER_TOOLS_AUTHORITY", None)
    directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    if not isinstance(authority, ReaderToolsAuthority) or directory is None:
        raise preview.PreviewUnavailable()
    case = Case.objects.get(pk=source.case_id)
    return Boundary(
        authority,
        directory,
        _epoch(authority, "projection_epoch"),
        _epoch(directory, "projection_epoch"),
        case,
        source,
        core_state(case.pk),
    )


@mutation_context
@contextmanager
def reader_projection(publication_id, *, action=None):
    if action is not None and action not in ACTIONS:
        raise preview.PreviewUnavailable()
    try:
        with synthetic_queue_atomic():
            enabled()
            source = PublicationEdition.objects.filter(pk=cases._uuid(publication_id)).first()
            if source is None:
                raise preview.PreviewUnavailable()
            guard = _boundary(source)
            # The existing exact text reader holds current canonical source,
            # citation and original-byte guards through the actual response.
            with recording_public.publication_projection(source.pk, include_media=False) as result:
                available = []
                for operation in (action,) if action else ACTIONS:
                    if guard.permission(operation, required=action is not None):
                        available.append(operation)
                guard.check_state()
                yield {
                    "publication": result["publication"],
                    "actions": available,
                    "descriptor": {
                        "publication_id": str(source.pk),
                        "version": source.number,
                        "content_sha256": source.content_sha256,
                        "title": result["publication"]["title"],
                        "url": reverse("library_preview:detail", args=[source.pk]),
                        "reader_url": reverse("public_reader", args=[source.pk]),
                    },
                    "snapshot": guard,
                }
                guard.finish()
            # Source readers can invoke callbacks on exit. No such callback may
            # change a previously checked tool/actor grant in the final response.
            guard.check_state()
    except cases.CaseConflict as exc:
        raise preview.PreviewUnavailable() from exc


def text_copy(result):
    row, descriptor = result["publication"], result["descriptor"]
    lines = [row["title"], row["category"], f"النسخة المنشورة: {row['number']}", "", row["body"]]
    if row["references"]:
        lines.extend(("", "الإحالات المصرح بعرضها"))
        for source in row["references"]:
            fields = [
                source.get(key, "")
                for key in (
                    "work_title",
                    "heading_title",
                    "edition_title",
                    "printed_part",
                    "printed_page",
                )
            ]
            lines.append(" · ".join(str(value) for value in fields if value))
    lines.extend(
        (
            "",
            "مرجع النسخة العامة: " + descriptor["url"],
            "هذه نسخة شخصية من النص المتاح؛ لا تتضمن مرفقات أو سجلًا داخليًا.",
        )
    )
    return ("\n".join(lines) + "\n").encode("utf-8")
