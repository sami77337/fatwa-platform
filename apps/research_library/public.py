"""An anonymous reader receives only the exact independently released material."""

from contextlib import contextmanager

from django.conf import settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import Case
from apps.data_privacy import integration as privacy
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.library_preview import services as preview
from apps.platform_recovery.integration import mutation_context

from . import services
from .models import LibraryVersion


class Snapshot:
    def __init__(self):
        self.records, self.case_ids, self.files = {}, {}, {}
        self.deadlines = []
        self.authorizations, self.use_checks = {}, []

    def read(self, version_id):
        result = self.records.get(str(version_id))
        if result is None:
            raise preview.PreviewUnavailable()
        return result

    def locate(self, public_id, number):
        result = next(
            (
                r
                for r in self.records.values()
                if r["id"] == str(public_id) and r["number"] == number
            ),
            None,
        )
        if result is None:
            raise preview.PreviewUnavailable()
        return result

    def verify_source_pins(self):
        """Actual-byte checks with no identity or permission callbacks."""
        for blob in self.files.values():
            services._raw(blob)
        if any(timezone.now() >= deadline for deadline in self.deadlines):
            raise preview.PreviewUnavailable()

    def authorize_use(self, version_id, usage):
        row = self.read(version_id)
        if usage not in {"PUBLIC_CONTENT", "DOWNLOAD", "OFFLINE", "EXPORT", "CITE"} or usage not in row["uses"]:
            raise preview.PreviewUnavailable()
        privacy.public(
            "LIBRARY_VERSION", version_id,
            action="EXPORT" if usage in {"DOWNLOAD", "OFFLINE", "EXPORT"} else "READ",
        )
        if usage != "PUBLIC_CONTENT":
            policy, release_values = self.authorizations[str(version_id)]
            values = {**release_values, "action": usage}
            services._permit_raw(policy[0], values)
            self.use_checks.append((policy, values))
        return row

    def content(self, version_id, *, usage="PUBLIC_CONTENT"):
        row = self.authorize_use(version_id, usage)
        if "PUBLIC_CONTENT" not in row["uses"] or not row["file"]:
            raise preview.PreviewUnavailable()
        blob = self.files.get(str(version_id))
        if blob is None:
            raise preview.PreviewUnavailable()
        return {"raw": services._raw(blob), **row["file"]}


def _actor(event, row, directory, policy):
    if directory is None or directory.provider_id != event.provider_id:
        raise cases.CaseConflict("library_public_actor_unavailable")
    actor = cases._identity(directory, event.subject_id, row.item.case)
    if actor.auth_epoch != event.auth_epoch:
        raise cases.CaseConflict("library_public_actor_changed")
    values = dict(
        provider_id=directory.provider_id,
        subject_id=actor.subject_id,
        auth_epoch=actor.auth_epoch,
        case_ref=row.item.case.public_ref,
        action=event.action,
        **services._fields(row),
    )
    services._permit_raw(policy[0], values)
    return actor, values


@mutation_context
@privacy.public_contextual
@contextmanager
def public_projection():
    try:
        services.enabled()
        if getattr(settings, "FATWA_RESEARCH_LIBRARY_PUBLIC_ENABLED", False) is not True:
            raise preview.PreviewUnavailable()
        selected = preview._start()
        policy = services.policy_snapshot()
        directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        snapshot, actors = Snapshot(), []
        snapshot.deadlines.append(selected.valid_until)
        with synthetic_queue_atomic():
            # The scholarly graph mutex is always acquired before any case lock,
            # matching the existing public knowledge/collection composition.
            from django.db import connection

            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(546131,1)")
            case_ids = services.public_case_ids()
            from apps.precise_citations.integration import prelock_cases

            case_ids = prelock_cases(case_ids)
            list(Case.objects.filter(pk__in=case_ids).order_by("pk").select_for_update())
            before = services.public_fingerprint()
            rows = LibraryVersion.objects.filter(
                decisions__action="RELEASE", decisions__valid_until__gt=timezone.now()
            )
            for row in rows.select_related("item__case", "blob").order_by("item_id", "number"):
                services._verify(row)
                actions = {event.action: event for event in row.decisions.order_by("sequence")}
                for event in actions.values():
                    services._verify(event)
                if "REVOKE" in actions or "WITHDRAW" in actions:
                    continue
                try:
                    privacy.public("LIBRARY_VERSION", row.pk)
                    approval = services._approval(row, "PUBLIC_METADATA")
                    release = actions["RELEASE"]
                    checked = []
                    for event in (actions["REVIEW"], approval, release):
                        actor, values = _actor(event, row, directory, policy)
                        checked.append((actor, values, row))
                    privacy.staff("LIBRARY_VERSION", row.pk, provider=directory,
                                  actor=checked[-1][0], action="PUBLISH")
                    actors.extend(checked)
                except (cases.CaseConflict, KeyError):
                    continue
                public_uses = set(approval.uses) & {
                    "PUBLIC_METADATA",
                    "PUBLIC_CONTENT",
                    "DOWNLOAD",
                    "OFFLINE",
                    "EXPORT",
                    "CITE",
                }
                file = None
                if "PUBLIC_CONTENT" in public_uses and row.blob_id:
                    services._raw(row.blob)
                    snapshot.files[str(row.pk)] = row.blob
                    file = services._dto(row)["file"]
                p = row.payload
                snapshot.records[str(row.pk)] = {
                    "id": str(row.item.public_id),
                    "version_id": str(row.pk),
                    "number": row.number,
                    "digest": row.digest,
                    **{
                        key: p[key]
                        for key in (
                            "kind",
                            "title",
                            "work_title",
                            "edition_label",
                            "creator",
                            "description",
                            "language",
                            "source_locator",
                        )
                    },
                    "recorded_text": p["recorded_text"] if "PUBLIC_CONTENT" in public_uses else "",
                    "file": file,
                    "uses": sorted(public_uses),
                    "url": f"/library-preview/materials/{row.item.public_id}/{row.number}/",
                }
                snapshot.case_ids[str(row.pk)] = str(row.item.case_id)
                snapshot.authorizations[str(row.pk)] = (policy, checked[-1][1])
                snapshot.deadlines.extend(
                    [
                        approval.valid_until,
                        release.valid_until,
                        *[actor.valid_until for actor, _, _ in checked],
                    ]
                )
            # Every initial authorizer has run before exposing the assembled DTOs.
            services.assert_policy_snapshot(policy)
            if services.public_fingerprint() != before:
                raise preview.PreviewUnavailable()
            yield snapshot
            for checked_policy, values in snapshot.use_checks:
                services._permit_raw(checked_policy[0], values)
            for actor, values, row in actors:
                services._permit_raw(policy[0], values)
            for actor, _, row in actors:
                fresh = cases._identity(directory, actor.subject_id, row.item.case)
                if services._actor(fresh) != services._actor(actor):
                    raise preview.PreviewUnavailable()
            snapshot.verify_source_pins()
            preview._recheck(selected)
            services.assert_policy_snapshot(policy)
            if services.public_fingerprint() != before:
                raise preview.PreviewUnavailable()
    except cases.CaseConflict as exc:
        raise preview.PreviewUnavailable() from exc
