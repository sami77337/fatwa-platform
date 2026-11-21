"""Versioned materials and current, independent, exact-version use permissions."""

import json
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from hashlib import sha256

from django.conf import settings
from django.utils import timezone

from apps.case_attachments.storage_bindings import binding_locks
from apps.casework import delivery
from apps.casework import services as cases
from apps.casework.models import Case
from apps.delivery_queue.services import _canonical
from apps.platform_recovery.integration import mutation_context, mutation_service
from apps.private_media.storage import StoredOriginal, configured_storage, read_original
from apps.private_media.validation import MediaValidationError

from .authority import LibraryAuthority
from .models import LibraryBlob, LibraryDecision, LibraryItem, LibraryVersion
from .validation import validate_file

KINDS = {"BOOK", "DOCUMENT", "IMAGE", "AUDIO", "VIDEO"}
USES = {"READ", "DOWNLOAD", "CITE", "EXPORT", "OFFLINE", "PUBLIC_METADATA", "PUBLIC_CONTENT"}
FIELDS = {
    "title": 200,
    "work_title": 200,
    "edition_label": 160,
    "creator": 200,
    "description": 2000,
    "source_locator": 1000,
    "provenance": 1000,
    "rights_basis": 1000,
    "source_version": 128,
    "recorded_text": 10000,
}
_SCOPES = ContextVar("research_library_scopes", default=())


def enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_RESEARCH_LIBRARY_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("library_disabled")


def _digest(value):
    return sha256(_canonical(value)).hexdigest()


def _text(value, maximum, *, required=False):
    cases._text(value, optional=not required)
    if len(value) > maximum:
        raise cases.CaseConflict("library_text_bound")
    return value


def _identity(value):
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}", value) is None:
        raise cases.CaseConflict("library_source_identity_invalid")
    return value


def validate_material(payload, file_bytes=b"", filename="", media_type=""):
    if (
        type(payload) is not dict
        or set(payload) != {*FIELDS, "kind", "language", "synthetic"}
        or payload["kind"] not in KINDS
        or payload["language"] not in {"ar", "en"}
        or payload["synthetic"] is not True
    ):
        raise cases.CaseConflict("library_payload_invalid")
    for key, maximum in FIELDS.items():
        _text(
            payload[key],
            maximum,
            required=key in {"title", "work_title", "provenance", "rights_basis", "source_version"},
        )
    if type(file_bytes) is not bytes:
        raise cases.CaseConflict("library_file_invalid")
    if not file_bytes:
        if filename or media_type:
            raise cases.CaseConflict("library_file_invalid")
        return None
    try:
        parsed = validate_file(file_bytes, filename, media_type)
    except MediaValidationError as exc:
        raise cases.CaseConflict("library_file_invalid") from exc
    required = {
        "BOOK": {"pdf", "text"},
        "DOCUMENT": {"pdf", "text"},
        "IMAGE": {"image"},
        "AUDIO": {"audio"},
        "VIDEO": {"video"},
    }
    if parsed.kind not in required[payload["kind"]]:
        raise cases.CaseConflict("library_file_kind_mismatch")
    return parsed


@mutation_context
@contextmanager
def material_bindings(files=()):
    """Hold exact original digests before and through the outermost database commit.

    Import groups and native command/render units preacquire these same locks. No
    file or owner row is created here, and arbitrary nested external writes fail.
    """
    if not isinstance(files, (list, tuple)) or len(files) > 20 or any(
        type(raw) is not bytes or not 1 <= len(raw) <= 192000 for raw in files
    ):
        raise cases.CaseConflict("library_file_invalid")
    configured = getattr(settings, "FATWA_PRIVATE_MEDIA_STORAGE", None)
    try:
        storage = configured_storage()
        with binding_locks(storage, [sha256(raw).hexdigest() for raw in files]):
            yield storage
            if getattr(settings, "FATWA_PRIVATE_MEDIA_STORAGE", None) is not configured:
                raise cases.CaseConflict("library_storage_changed")
    except (MediaValidationError, OSError) as exc:
        raise cases.CaseConflict("library_storage_unavailable") from exc


def policy_snapshot():
    enabled()
    authority = getattr(settings, "FATWA_RESEARCH_LIBRARY_AUTHORITY", None)
    if not isinstance(authority, LibraryAuthority):
        raise cases.CaseConflict("library_authority_required")
    try:
        epoch = authority.projection_epoch()
    except Exception as exc:
        raise cases.CaseConflict("library_policy_snapshot_required") from exc
    if type(epoch) is not str or not 1 <= len(epoch) <= 4000:
        raise cases.CaseConflict("library_policy_snapshot_required")
    configuration = (
        id(getattr(settings, "FATWA_PRIVATE_MEDIA_STORAGE", None)),
        id(getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)),
        getattr(settings, "FATWA_RESEARCH_LIBRARY_PUBLIC_ENABLED", False) is True,
        getattr(settings, "FATWA_RESEARCH_LIBRARY_OFFLINE_ENABLED", False) is True,
    )
    return authority, epoch, configuration


def assert_policy_snapshot(expected):
    current = policy_snapshot()
    if current[0] is not expected[0] or current[1:] != expected[1:]:
        raise cases.CaseConflict("library_policy_changed")


def _actor(identity):
    return (
        identity.subject_id,
        identity.role,
        identity.active,
        identity.case_keys,
        identity.auth_epoch,
    )


def identity_snapshot(provider):
    """Pure identity state, required by new composed readers after all callbacks."""
    method = getattr(provider, "projection_epoch", None)
    try:
        value = method() if callable(method) else None
    except Exception as exc:
        raise cases.CaseConflict("library_identity_snapshot_required") from exc
    if type(value) is not str or not 1 <= len(value) <= 131072:
        raise cases.CaseConflict("library_identity_snapshot_required")
    return id(provider), provider.provider_id, value


def _body(row):
    result = {}
    for field in row._meta.fields:
        if field.name not in {"canonical_payload", "digest", "created_at"}:
            value = getattr(row, field.attname)
            if hasattr(value, "isoformat"):
                value = value.isoformat(timespec="microseconds")
            elif value is not None and not isinstance(value, (str, int, bool, list, dict)):
                value = str(value)
            result[field.attname] = value
    return result


def _seal(row):
    row.canonical_payload = _canonical(_body(row)).decode("utf-8")
    row.digest = sha256(row.canonical_payload.encode("utf-8")).hexdigest()
    row.save(force_insert=True)
    return row


def _verify(row):
    if (
        json.loads(row.canonical_payload) != _body(row)
        or sha256(row.canonical_payload.encode()).hexdigest() != row.digest
    ):
        raise cases.CaseConflict("library_integrity_failed")


def _version_state(version_id):
    return (
        list(LibraryVersion.objects.filter(pk=version_id).values()),
        list(LibraryDecision.objects.filter(version_id=version_id).order_by("sequence").values()),
    )


def _raw(blob):
    try:
        return read_original(
            StoredOriginal(
                blob.storage_backend,
                blob.storage_key,
                blob.sha256,
                blob.size,
                bytes(blob.original) if blob.original is not None else None,
            )
        )
    except MediaValidationError as exc:
        raise cases.CaseConflict("library_file_unavailable") from exc


class Boundary:
    def __init__(self, case, actor, provider):
        from apps.private_media.links import retain_projection

        self.case, self.actor, self.provider = case, actor, provider
        self.namespace = provider.provider_id
        self.identity_state = identity_snapshot(provider)
        self.policy = policy_snapshot()
        self.case_state = list(Case.objects.filter(pk=case.pk).values())
        self.versions, self.files, self.permissions, self.deadlines = (
            {},
            {},
            [],
            [actor.valid_until],
        )
        self.heads = {}
        retain_projection(self.final_pins)

    def watch(self, row):
        self.versions.setdefault(str(row.pk), _version_state(row.pk))

    def check_permissions(self):
        for values in self.permissions:
            _permit_raw(self.policy[0], values)

    def check_files(self):
        for blob in self.files.values():
            _raw(blob)

    def finish(self):
        self.check_permissions()
        fresh = cases._identity(self.provider, self.actor.subject_id, self.case)
        if self.provider.provider_id != self.namespace or _actor(fresh) != _actor(self.actor):
            raise cases.CaseConflict("library_identity_changed")
        self.check_files()
        self.final_pins()

    def final_pins(self):
        assert_policy_snapshot(self.policy)
        if identity_snapshot(self.provider) != self.identity_state:
            raise cases.CaseConflict("library_identity_changed")
        if list(Case.objects.filter(pk=self.case.pk).values()) != self.case_state:
            raise cases.CaseConflict("library_case_changed")
        if any(_version_state(pk) != state for pk, state in self.versions.items()):
            raise cases.CaseConflict("library_source_changed")
        if any(head_fingerprint(case_id) != state for case_id, state in self.heads.items()):
            raise cases.CaseConflict("library_head_changed")
        if any(timezone.now() >= deadline for deadline in self.deadlines):
            raise cases.CaseConflict("library_permission_expired")


@mutation_context
@contextmanager
def staff_boundary(
    *,
    case_id,
    subject_id,
    provider,
    synthetic_fixtures_only=False,
    expected_revision=None,
    expected_evidence_version=None,
    **unused,
):
    enabled()
    with delivery._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
        case,
        actor,
    ):
        if expected_revision is not None:
            cases._versions(case, expected_revision, expected_evidence_version)
        boundary = Boundary(case, actor, provider)
        token = _SCOPES.set((*_SCOPES.get(), boundary))
        try:
            yield case, actor
            boundary.finish()
        finally:
            _SCOPES.reset(token)


def _permit_raw(authority, values):
    try:
        allowed = authority.permits(**values)
    except Exception as exc:
        raise cases.CaseConflict("library_authority_unavailable") from exc
    if allowed is not True:
        raise cases.CaseConflict("library_action_denied")


def _permit(case, actor, provider, action, *, namespace="", external_id="", version_digest=""):
    values = dict(
        provider_id=provider.provider_id,
        subject_id=actor.subject_id,
        auth_epoch=actor.auth_epoch,
        case_ref=case.public_ref,
        action=action,
        namespace=namespace,
        external_id=external_id,
        version_digest=version_digest,
    )
    snapshot = policy_snapshot()
    for scope in _SCOPES.get():
        if scope.case.pk == case.pk:
            scope.permissions.append(values)
    _permit_raw(snapshot[0], values)
    assert_policy_snapshot(snapshot)
    if version_digest and action in {"VIEW", "READ", "CITE", "DOWNLOAD", "OFFLINE", "EXPORT", "REVIEW", "APPROVE", "RELEASE"}:
        from apps.data_privacy.integration import staff as privacy

        identifier = LibraryVersion.objects.filter(item__case=case, digest=version_digest).values_list("pk", flat=True).get()
        privacy(
            "LIBRARY_VERSION", identifier, provider=provider, actor=actor,
            action="EXPORT" if action in {"DOWNLOAD", "OFFLINE", "EXPORT"}
            else "PUBLISH" if action == "RELEASE" else "READ",
        )


def _watch(row, *, file=False):
    _verify(row)
    for decision in row.decisions.order_by("sequence"):
        _verify(decision)
    for scope in _SCOPES.get():
        scope.watch(row)
        if file and row.blob_id:
            scope.files[row.blob_id] = row.blob


def _fields(row):
    return {
        "namespace": row.item.namespace,
        "external_id": row.item.external_id,
        "version_digest": row.digest,
    }


def _dto(row):
    actions = list(row.decisions.order_by("sequence"))
    return {
        "item_id": str(row.item_id),
        "public_id": str(row.item.public_id),
        "version_id": str(row.pk),
        "namespace": row.item.namespace,
        "external_id": row.item.external_id,
        "number": row.number,
        "digest": row.digest,
        "payload": row.payload,
        "file": (
            {
                "sha256": row.blob_id,
                "size": row.blob.size,
                "media_type": row.blob.media_type,
                "filename": row.filename,
                **{
                    k: row.blob.validation[k]
                    for k in ("duration_seconds", "page_count")
                    if k in row.blob.validation
                },
            }
            if row.blob_id
            else None
        ),
        "action_count": len(actions),
        "state": actions[-1].action if actions else "DRAFT",
        "history": [
            {
                "action": d.action,
                "note": d.note,
                "uses": d.uses,
                "valid_until": d.valid_until,
                "created_at": d.created_at,
            }
            for d in actions
        ],
    }


@mutation_service
def current_material(*, namespace, external_id, **base):
    _identity(namespace), _identity(external_id)
    with staff_boundary(**base) as (case, actor):
        _SCOPES.get()[-1].heads[str(case.pk)] = head_fingerprint(case.pk)
        _permit(case, actor, base["provider"], "VIEW", namespace=namespace, external_id=external_id)
        row = (
            LibraryVersion.objects.filter(
                item__case=case, item__namespace=namespace, item__external_id=external_id
            )
            .select_related("item", "blob")
            .order_by("-number")
            .first()
        )
        if row is None:
            return None
        _watch(row, file=True)
        _permit(case, actor, base["provider"], "VIEW", **_fields(row))
        if row.blob_id:
            _raw(row.blob)
        return _dto(row)


@mutation_service
def write_material(
    *,
    namespace,
    external_id,
    payload,
    file_bytes=b"",
    filename="",
    media_type="",
    expected_version=0,
    request_key,
    **base,
):
    cases._mutation_versions(base.get("expected_revision"), base.get("expected_evidence_version"))
    _identity(namespace), _identity(external_id)
    key = cases._uuid(request_key)
    if type(expected_version) is not int or not 0 <= expected_version < 64:
        raise cases.CaseConflict("library_expected_version_invalid")
    parsed = validate_material(payload, file_bytes, filename, media_type)
    request_hash = _digest(
        {
            "case_id": str(base["case_id"]),
            "namespace": namespace,
            "external_id": external_id,
            "payload": payload,
            "file": sha256(file_bytes).hexdigest() if file_bytes else "",
            "filename": filename,
            "media_type": media_type,
            "expected_version": expected_version,
        }
    )
    with material_bindings([file_bytes] if parsed else []) as storage, staff_boundary(**base) as (
        case,
        actor,
    ):
        provider = base["provider"]
        _permit(case, actor, provider, "EDIT", namespace=namespace, external_id=external_id)
        old_request = (
            LibraryVersion.objects.filter(
                provider_id=provider.provider_id, subject_id=actor.subject_id, request_key=key
            )
            .select_related("item", "blob")
            .first()
        )
        if old_request:
            if old_request.request_sha256 != request_hash or old_request.item.case_id != case.pk:
                raise cases.CaseConflict("library_request_conflict")
            _watch(old_request, file=True)
            _permit(case, actor, provider, "VIEW", **_fields(old_request))
            return _dto(old_request)
        item = LibraryItem.objects.filter(
            case=case, namespace=namespace, external_id=external_id
        ).first()
        previous = item.versions.order_by("-number").first() if item else None
        if (previous.number if previous else 0) != expected_version:
            raise cases.CaseConflict("library_version_changed")
        if previous:
            _watch(previous, file=True)
            _permit(case, actor, provider, "EDIT", **_fields(previous))
            if previous.payload["kind"] != payload["kind"]:
                raise cases.CaseConflict("library_kind_changed")
        if not item:
            if LibraryItem.objects.filter(case=case).count() >= 64:
                raise cases.CaseConflict("library_item_capacity")
            item = LibraryItem.objects.create(
                case=case, namespace=namespace, external_id=external_id
            )
        blob = previous.blob if previous and parsed is None else None
        selected_filename = previous.filename if previous and parsed is None else filename
        if parsed:
            blob = LibraryBlob.objects.filter(pk=parsed.sha256).first()
            if blob is None:
                stored = storage.put(parsed)
                if stored.sha256 != parsed.sha256 or stored.size != parsed.size:
                    raise cases.CaseConflict("library_storage_mismatch")
                blob = LibraryBlob.objects.create(
                    sha256=parsed.sha256,
                    original=stored.inline,
                    storage_backend=stored.backend,
                    storage_key=stored.key,
                    size=parsed.size,
                    media_type=parsed.media_type,
                    validation=parsed.metadata,
                )
            elif blob.media_type != parsed.media_type or _raw(blob) != parsed.raw:
                raise cases.CaseConflict("library_blob_conflict")
        row = _seal(
            LibraryVersion(
                item=item,
                number=expected_version + 1,
                previous=previous,
                payload=payload,
                blob=blob,
                filename=selected_filename,
                request_key=key,
                request_sha256=request_hash,
                subject_id=actor.subject_id,
                provider_id=provider.provider_id,
                auth_epoch=actor.auth_epoch,
                case_revision=case.revision,
                evidence_version=case.evidence_version,
            )
        )
        _watch(row, file=True)
        return _dto(row)


def _row(case, version_id):
    row = (
        LibraryVersion.objects.filter(pk=cases._uuid(version_id), item__case=case)
        .select_related("item", "blob")
        .first()
    )
    if row is None:
        raise cases.CaseConflict("library_material_unavailable")
    return row


@mutation_service
def read_material(*, version_id=None, item_id=None, version_number=None, **base):
    with staff_boundary(**base) as (case, actor):
        if version_id is None and version_number is None:
            _SCOPES.get()[-1].heads[str(case.pk)] = head_fingerprint(case.pk)
        if version_id is None:
            query = LibraryVersion.objects.filter(item_id=cases._uuid(item_id), item__case=case)
            if version_number is not None:
                query = query.filter(number=version_number)
            row = query.order_by("-number").first()
            if row is None:
                raise cases.CaseConflict("library_material_unavailable")
        else:
            row = _row(case, version_id)
        _watch(row, file=True)
        _permit(case, actor, base["provider"], "VIEW", **_fields(row))
        if row.blob_id:
            _raw(row.blob)
        return _dto(row)


def _approval(row, usage):
    actions = {d.action: d for d in row.decisions.order_by("sequence")}
    approval = actions.get("APPROVE")
    review = actions.get("REVIEW")
    if (
        not approval
        or not review
        or "WITHDRAW" in actions
        or usage not in approval.uses
        or approval.valid_until <= timezone.now()
        or len(
            {
                (row.provider_id, row.subject_id),
                (review.provider_id, review.subject_id),
                (approval.provider_id, approval.subject_id),
            }
        )
        != 3
    ):
        raise cases.CaseConflict("library_use_unavailable")
    for scope in _SCOPES.get():
        scope.deadlines.append(approval.valid_until)
    return approval


@mutation_service
def authorize_material(*, version_id, usage, **base):
    """Exact-version text/metadata use, including a descriptive source without a file."""
    if usage not in {"READ", "DOWNLOAD", "EXPORT", "OFFLINE", "CITE"}:
        raise cases.CaseConflict("library_use_invalid")
    with staff_boundary(**base) as (case, actor):
        row = _row(case, version_id)
        _watch(row, file=True)
        _permit(case, actor, base["provider"], usage, **_fields(row))
        _approval(row, usage)
        if row.blob_id:
            _raw(row.blob)
        return _dto(row)


@mutation_service
def file_content(*, version_id, usage="READ", **base):
    if usage not in {"READ", "DOWNLOAD", "EXPORT", "OFFLINE", "CITE"}:
        raise cases.CaseConflict("library_use_invalid")
    with staff_boundary(**base) as (case, actor):
        row = _row(case, version_id)
        _watch(row, file=True)
        _permit(case, actor, base["provider"], usage, **_fields(row))
        _approval(row, usage)
        if row.blob_id is None:
            raise cases.CaseConflict("library_descriptive_reference_only")
        return {
            "raw": _raw(row.blob),
            "sha256": row.blob_id,
            "media_type": row.blob.media_type,
            "filename": row.filename,
            "version_id": str(row.pk),
            "number": row.number,
            "digest": row.digest,
        }


@mutation_service
def decide(
    *,
    version_id,
    action,
    note,
    expected_actions,
    request_key,
    uses=None,
    minutes=0,
    confirmed=False,
    **base,
):
    cases._mutation_versions(base.get("expected_revision"), base.get("expected_evidence_version"))
    if (
        action not in {"REVIEW", "APPROVE", "RELEASE", "REVOKE", "WITHDRAW"}
        or confirmed is not True
        or type(expected_actions) is not int
        or not 0 <= expected_actions < 5
    ):
        raise cases.CaseConflict("library_decision_invalid")
    _text(note, 1000, required=True)
    key = cases._uuid(request_key)
    uses = [] if uses is None else uses
    if (
        type(uses) is not list
        or any(type(u) is not str for u in uses)
        or len(uses) != len(set(uses))
        or not set(uses) <= USES
    ):
        raise cases.CaseConflict("library_uses_invalid")
    if (action == "APPROVE" and not uses) or (action != "APPROVE" and uses):
        raise cases.CaseConflict("library_uses_invalid")
    if (
        type(minutes) is not int
        or (action in {"APPROVE", "RELEASE"} and not 1 <= minutes <= 60)
        or (action not in {"APPROVE", "RELEASE"} and minutes != 0)
    ):
        raise cases.CaseConflict("library_expiry_invalid")
    request_hash = _digest(
        {
            "version_id": str(version_id),
            "action": action,
            "note": note,
            "uses": sorted(uses),
            "minutes": minutes,
            "expected_actions": expected_actions,
        }
    )
    with staff_boundary(**base) as (case, actor):
        row = _row(case, version_id)
        _watch(row, file=True)
        provider = base["provider"]
        _permit(case, actor, provider, action, **_fields(row))
        old_request = LibraryDecision.objects.filter(
            provider_id=provider.provider_id, subject_id=actor.subject_id, request_key=key
        ).first()
        if old_request:
            if old_request.request_sha256 != request_hash or old_request.version_id != row.pk:
                raise cases.CaseConflict("library_request_conflict")
            return _dto(row)
        actions = list(row.decisions.order_by("sequence"))
        names = {d.action: d for d in actions}
        if len(actions) != expected_actions or action in names or "WITHDRAW" in names:
            raise cases.CaseConflict("library_decision_changed")
        subject = (provider.provider_id, actor.subject_id)
        author = (row.provider_id, row.subject_id)
        until = timezone.now() + timedelta(minutes=minutes) if minutes else None
        if action == "REVIEW" and (actions or subject == author):
            raise cases.CaseConflict("library_independent_review_required")
        if action == "APPROVE":
            if set(names) != {"REVIEW"} or subject in {
                author,
                (names["REVIEW"].provider_id, names["REVIEW"].subject_id),
            }:
                raise cases.CaseConflict("library_independent_approval_required")
            if "PUBLIC_CONTENT" in uses and "PUBLIC_METADATA" not in uses:
                raise cases.CaseConflict("library_public_metadata_required")
            if row.blob_id is None and any(u in uses for u in {"READ", "DOWNLOAD"}):
                raise cases.CaseConflict("library_descriptive_reference_only")
        if action == "RELEASE":
            approval = _approval(row, "PUBLIC_METADATA")
            if set(names) != {"REVIEW", "APPROVE"} or until > approval.valid_until:
                raise cases.CaseConflict("library_release_invalid")
        if action == "REVOKE" and ("RELEASE" not in names or "REVOKE" in names):
            raise cases.CaseConflict("library_release_unavailable")
        previous = actions[-1].digest if actions else row.digest
        decision = _seal(
            LibraryDecision(
                version=row,
                sequence=len(actions) + 1,
                action=action,
                uses=sorted(uses),
                valid_until=until,
                note=note,
                request_key=key,
                request_sha256=request_hash,
                previous_digest=previous,
                subject_id=actor.subject_id,
                provider_id=provider.provider_id,
                auth_epoch=actor.auth_epoch,
                case_revision=case.revision,
                evidence_version=case.evidence_version,
            )
        )
        # Only this service's declared decision changes its local expected state.
        # An outer reader keeps its earlier pins, so late nested revocation aborts it.
        _SCOPES.get()[-1].versions[str(row.pk)] = _version_state(row.pk)
        _verify(decision)
        return _dto(row)


@mutation_service
def browse(*, query="", kind="", page=1, **base):
    from apps.data_privacy.integration import staff as privacy
    from apps.data_privacy.services import PrivacyDenied

    _text(query, 160)
    if kind not in {"", *KINDS} or type(page) is not int or not 1 <= page <= 8:
        raise cases.CaseConflict("library_filter_invalid")
    with staff_boundary(**base) as (case, actor):
        privacy("CASE", case.pk, provider=base["provider"], actor=actor, action="SEARCH")
        _SCOPES.get()[-1].heads[str(case.pk)] = head_fingerprint(case.pk)
        _permit(case, actor, base["provider"], "VIEW")
        items = list(
            LibraryItem.objects.filter(case=case).order_by("namespace", "external_id")[:65]
        )
        if len(items) > 64:
            raise cases.CaseConflict("library_item_capacity")
        rows = []
        for item in items:
            row = item.versions.order_by("-number").first()
            if row is None:
                raise cases.CaseConflict("library_integrity_failed")
            _watch(row)
            try:
                _permit(case, actor, base["provider"], "VIEW", **_fields(row))
                privacy("LIBRARY_VERSION", row.pk, provider=base["provider"], actor=actor, action="SEARCH")
            except cases.CaseConflict as exc:
                if str(exc) != "library_action_denied" and not isinstance(exc, PrivacyDenied):
                    raise
                # A denied item contributes neither text nor counts. Remove the
                # declined check from final callbacks; identity/epoch stays pinned.
                for scope in _SCOPES.get():
                    scope.permissions = [
                        v
                        for v in scope.permissions
                        if not (v["version_digest"] == row.digest and v["action"] == "VIEW")
                    ]
                continue
            if (not kind or row.payload["kind"] == kind) and (
                not query
                or query.casefold()
                in (
                    row.payload["title"]
                    + " "
                    + row.payload["work_title"]
                    + " "
                    + row.payload["creator"]
                ).casefold()
            ):
                rows.append(_dto(row))
        return {
            "rows": rows[(page - 1) * 8 : page * 8],
            "total": len(rows),
            "page": page,
            "has_next": len(rows) > page * 8,
            "query": query,
            "kind": kind,
            "case_id": str(case.pk),
            "case_ref": case.public_ref,
            "revision": case.revision,
            "evidence_version": case.evidence_version,
        }


def head_fingerprint(case_id):
    """Pure material identities/current editions, including absence, for composition."""
    from django.db.models import OuterRef, Subquery

    latest = LibraryVersion.objects.filter(item_id=OuterRef("pk")).order_by("-number")
    values = (
        LibraryItem.objects.filter(case_id=case_id)
        .annotate(
            latest_id=Subquery(latest.values("id")[:1]),
            latest_number=Subquery(latest.values("number")[:1]),
            latest_digest=Subquery(latest.values("digest")[:1]),
        )
        .order_by("pk")
    )
    return tuple(
        (
            str(pk),
            namespace,
            external_id,
            str(latest_id) if latest_id else "",
            number or 0,
            digest or "",
        )
        for pk, namespace, external_id, latest_id, number, digest in values.values_list(
            "id", "namespace", "external_id", "latest_id", "latest_number", "latest_digest"
        )
    )


def public_case_ids():
    rows = list(
        LibraryDecision.objects.filter(
            action="RELEASE", valid_until__gt=timezone.now()
        ).values_list("version__item__case_id", flat=True)[:65]
    )
    if len(rows) > 64:
        raise cases.CaseConflict("library_public_capacity")
    return list(set(rows))


def public_fingerprint():
    candidates = LibraryVersion.objects.filter(
        decisions__action="RELEASE", decisions__valid_until__gt=timezone.now()
    )
    versions = list(candidates.values_list("pk", flat=True)[:65])
    if len(versions) > 64:
        raise cases.CaseConflict("library_public_capacity")
    policy = policy_snapshot()
    return (
        (id(policy[0]), policy[1], policy[2]),
        identity_snapshot(getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)),
        list(LibraryItem.objects.filter(versions__in=versions).distinct().order_by("pk").values()),
        list(LibraryVersion.objects.filter(pk__in=versions).order_by("pk").values()),
        list(LibraryDecision.objects.filter(version_id__in=versions).order_by("pk").values()),
        list(
            LibraryBlob.objects.filter(libraryversion__in=versions)
            .distinct()
            .order_by("pk")
            .values("sha256", "storage_backend", "storage_key", "size", "media_type", "validation")
        ),
        list(Case.objects.filter(pk__in=public_case_ids()).order_by("pk").values()),
    )
