"""Retain exact quarantined bytes; a scanner result never grants domain access."""

import json
import math
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import timedelta
from functools import wraps
from hashlib import sha256
from time import monotonic

from django.apps import apps
from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.casework import services as cases
from apps.delivery_queue.services import _postgres_only, synthetic_queue_atomic
from apps.platform_recovery.integration import mutation_service

from .contract import (
    MAX_BYTES,
    MAX_FILES,
    PURPOSES,
    Admission,
    FileScanner,
    ScanInput,
    ScannerSpec,
    ScanPolicy,
    ScanVerdict,
)
from .execution import invoke

ZERO = "0" * 64
REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
HASH = re.compile(r"[a-f0-9]{64}\Z")
SCOPES = ContextVar("upload_security_projections", default=())


class UploadSecurityDenied(cases.CaseConflict):
    def __init__(self, status):
        self.status = status
        super().__init__("upload_security_" + status.lower())


def enabled():
    return getattr(settings, "FATWA_UPLOAD_SECURITY_ENABLED", False) is True


def models():
    if not apps.is_installed("apps.upload_security"):
        raise UploadSecurityDenied("APPLICATION_REQUIRED")
    from .models import QuarantinedFile, ScanAttempt, UploadAdmission

    return QuarantinedFile, UploadAdmission, ScanAttempt


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def body(row):
    result = {}
    for field in row._meta.fields:
        if field.name in {"canonical_payload", "digest", "created_at", "original"}:
            continue
        value = getattr(row, field.attname)
        if hasattr(value, "isoformat"):
            value = value.isoformat(timespec="microseconds")
        elif value is not None and not isinstance(value, (str, int, bool, list, dict)):
            value = str(value)
        result[field.attname] = value
    return result


def seal(row):
    row.canonical_payload = canonical(body(row))
    row.digest = sha256(row.canonical_payload.encode()).hexdigest()
    row.save(force_insert=True)
    return row


def verify(row):
    if (
        json.loads(row.canonical_payload) != body(row)
        or sha256(row.canonical_payload.encode()).hexdigest() != row.digest
    ):
        raise UploadSecurityDenied("INTEGRITY")
    if hasattr(row, "original"):
        raw = bytes(row.original)
        if len(raw) != row.size or sha256(raw).hexdigest() != row.sha256:
            raise UploadSecurityDenied("INTEGRITY")


def recorded(identifier):
    if apps.is_installed("apps.upload_security"):
        return models()[0].objects.filter(pk=identifier).exists()
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('upload_security_quarantinedfile')")
        if cursor.fetchone()[0] is None:
            return False
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM upload_security_quarantinedfile WHERE sha256=%s)",
            [identifier],
        )
        return cursor.fetchone()[0]


def applicable(identifier):
    if enabled():
        return True
    if recorded(identifier):
        raise UploadSecurityDenied("RECORDED_POLICY_REQUIRED")
    return False


def specification(scanner):
    if not isinstance(scanner, FileScanner):
        return None
    try:
        spec = scanner.spec
    except Exception:
        return None
    if (
        type(spec) is not ScannerSpec
        or spec.mode not in {"CONFIGURED", "SYNTHETIC"}
        or any(
            type(value) is not str or REF.fullmatch(value) is None
            for value in (spec.key, spec.engine_version, spec.signature_version)
        )
        or any(
            type(value) is not str or HASH.fullmatch(value) is None
            for value in (spec.signature_digest, spec.configuration_digest)
        )
        or (
            spec.mode == "SYNTHETIC"
            and getattr(settings, "FATWA_UPLOAD_SECURITY_ALLOW_SYNTHETIC", False) is not True
        )
    ):
        return None
    return spec


def configuration():
    if not enabled() or os.environ.get("FATWA_PRODUCTION") != "0":
        raise UploadSecurityDenied("POLICY_REQUIRED")
    models()
    policy = getattr(settings, "FATWA_UPLOAD_SCAN_POLICY", None)
    if (
        type(policy) is not ScanPolicy
        or type(policy.key) is not str
        or REF.fullmatch(policy.key) is None
        or type(policy.timeout_seconds) not in {int, float}
        or not math.isfinite(policy.timeout_seconds)
        or not 0.01 <= policy.timeout_seconds <= 30
        or type(policy.validity_seconds) is not int
        or not 1 <= policy.validity_seconds <= 86400
        or type(policy.max_quarantined_files) is not int
        or not 1 <= policy.max_quarantined_files <= 10000
    ):
        raise UploadSecurityDenied("POLICY_REQUIRED")
    scanner = getattr(settings, "FATWA_UPLOAD_SCANNER", None)
    return (
        id(policy),
        policy,
        id(scanner),
        scanner,
        specification(scanner),
        getattr(settings, "FATWA_UPLOAD_SECURITY_ALLOW_SYNTHETIC", False) is True,
    )


def _lock(identifier):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,384))", [identifier])


def latest(identifier):
    row = models()[2].objects.filter(file_id=identifier).order_by("-sequence").first()
    if row is not None:
        verify(row)
    return row


def _current(identifier, size, selected):
    files, _, attempts = models()
    if selected[4] is None:
        raise UploadSecurityDenied("UNAVAILABLE")
    source = files.objects.filter(pk=identifier, size=size).first()
    if source is None:
        raise UploadSecurityDenied("UNSCANNED")
    verify(source)
    if attempts.objects.filter(file_id=identifier, status="BLOCKED").exists():
        raise UploadSecurityDenied("BLOCKED")
    row = latest(identifier)
    if row is None:
        raise UploadSecurityDenied("UNSCANNED")
    if row.status != "CLEAN":
        raise UploadSecurityDenied(row.status)
    if row.scanner != asdict(selected[4]) or row.policy != asdict(selected[1]):
        raise UploadSecurityDenied("STALE")
    if row.valid_until is None or row.valid_until <= timezone.now():
        raise UploadSecurityDenied("EXPIRED")
    if not row.complete or row.scanned_files != 1 or row.loaded_signatures < 1:
        raise UploadSecurityDenied("INCOMPLETE")
    return row


@dataclass(frozen=True, slots=True)
class Use:
    identifier: str
    size: int
    selected: tuple
    attempt_id: object
    digest: str
    deadline: object

    def check(self):
        if configuration() != self.selected or timezone.now() >= self.deadline:
            raise UploadSecurityDenied("REVOKED")
        row = _current(self.identifier, self.size, self.selected)
        if row.pk != self.attempt_id or row.digest != self.digest:
            raise UploadSecurityDenied("REVOKED")


class Projection:
    def __init__(self):
        self.flag = (type(getattr(settings, "FATWA_UPLOAD_SECURITY_ENABLED", None)), enabled())
        self.uses = []

    def check(self):
        if (type(getattr(settings, "FATWA_UPLOAD_SECURITY_ENABLED", None)), enabled()) != self.flag:
            raise UploadSecurityDenied("REVOKED")
        for use in self.uses:
            use.check()


@contextmanager
def projection():
    guard = Projection()
    token = SCOPES.set((*SCOPES.get(), guard))
    try:
        yield guard
        guard.check()
    finally:
        SCOPES.reset(token)


@contextmanager
def boundary():
    """Call after external digest locks and before the domain's owned DB unit."""
    with synthetic_queue_atomic(), projection() as guard:
        yield guard


def projected(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with projection():
            return function(*args, **kwargs)

    return wrapped


def contextual(function):
    @wraps(function)
    @contextmanager
    def wrapped(*args, **kwargs):
        with projection():
            with function(*args, **kwargs) as value:
                yield value

    return wrapped


def require(identifier, size):
    """Current byte admission only. It cannot substitute for a domain permission."""
    if (
        type(identifier) is not str
        or HASH.fullmatch(identifier) is None
        or type(size) is not int
        or not 1 <= size <= MAX_BYTES
    ):
        raise UploadSecurityDenied("INTEGRITY")
    if not applicable(identifier):
        return None
    _postgres_only()
    selected = configuration()
    row = _current(identifier, size, selected)
    use = Use(identifier, size, selected, row.pk, row.digest, row.valid_until)
    use.check()
    for guard in SCOPES.get():
        guard.uses.append(use)
    from apps.private_media.links import retain_projection

    retain_projection(use.check)
    return {"id": str(row.pk), "digest": row.digest, "mode": row.scanner["mode"]}


def _admission(raw, admission, selected):
    if (
        type(admission) is not Admission
        or admission.purpose not in PURPOSES
        or any(
            type(value) is not str or REF.fullmatch(value) is None
            for value in (admission.provider_id, admission.subject_id, admission.auth_epoch)
        )
        or len(admission.auth_epoch) > 64
        or type(admission.case_revision) is not int
        or admission.case_revision < 1
        or type(admission.evidence_version) is not int
        or admission.evidence_version < 1
    ):
        raise UploadSecurityDenied("ADMISSION_REQUIRED")
    case_id = cases._uuid(admission.case_id)
    identifier = sha256(raw).hexdigest()
    files, admissions, _ = models()
    with synthetic_queue_atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(546384,1)")
        case = cases.Case.objects.filter(pk=case_id).first()
        if case is None:
            raise UploadSecurityDenied("ADMISSION_REQUIRED")
        cases._versions(case, admission.case_revision, admission.evidence_version)
        source = files.objects.filter(pk=identifier).first()
        if source is None:
            if files.objects.count() >= selected[1].max_quarantined_files:
                raise UploadSecurityDenied("CAPACITY")
            source = seal(files(sha256=identifier, size=len(raw), original=raw))
        else:
            verify(source)
            if bytes(source.original) != raw:
                raise UploadSecurityDenied("INTEGRITY")
        fields = {**asdict(admission), "file_id": identifier}
        request_digest = digest(fields)
        if not admissions.objects.filter(request_digest=request_digest).exists():
            seal(admissions(**fields, request_digest=request_digest))
    return identifier


def _terminal(identifier, selected, status, verdict=None):
    with synthetic_queue_atomic():
        _lock(identifier)
        attempts = models()[2]
        old = latest(identifier)
        if attempts.objects.filter(file_id=identifier, status="BLOCKED").exists():
            status, verdict = "BLOCKED", None
        try:
            if configuration() != selected:
                status, verdict = "REVOKED", None
        except UploadSecurityDenied:
            status, verdict = "REVOKED", None
        scanner = asdict(selected[4]) if selected[4] else {}
        policy = asdict(selected[1])
        if (
            old is not None
            and old.status == status
            and status != "CLEAN"
            and old.scanner == scanner
            and old.policy == policy
        ):
            return old
        return seal(
            attempts(
                file_id=identifier,
                sequence=old.sequence + 1 if old else 1,
                previous_digest=old.digest if old else ZERO,
                status=status,
                scanner=scanner,
                policy=policy,
                complete=verdict.complete if verdict else False,
                scanned_files=verdict.scanned_files if verdict else 0,
                loaded_signatures=verdict.loaded_signatures if verdict else 0,
                valid_until=(timezone.now() + timedelta(seconds=selected[1].validity_seconds))
                if status == "CLEAN"
                else None,
            )
        )


def _verdict(answer, selected, identifier, size):
    if (
        type(answer) is not ScanVerdict
        or answer.spec != selected[4]
        or answer.sha256 != identifier
        or type(answer.size) is not int
        or answer.size != size
        or answer.status not in {"CLEAN", "BLOCKED", "UNAVAILABLE", "INCOMPLETE"}
        or type(answer.complete) is not bool
        or type(answer.scanned_files) is not int
        or not 0 <= answer.scanned_files <= MAX_FILES
        or type(answer.loaded_signatures) is not int
        or not 0 <= answer.loaded_signatures <= 100000000
    ):
        return "INCOMPLETE", None
    if answer.status == "CLEAN" and (
        not answer.complete or answer.scanned_files != 1 or answer.loaded_signatures < 1
    ):
        return "INCOMPLETE", None
    return answer.status, answer


@mutation_service
def prepare_many(raw_files, *, admission):
    """Internal primitive. The caller first runs its original domain preflight.

    Each input is retained independently; no canonical owner is created here.
    Nested callers may reuse a current exact receipt, never start a new scan.
    """
    if (
        type(raw_files) not in {list, tuple}
        or not 1 <= len(raw_files) <= MAX_FILES
        or any(type(raw) is not bytes or not 1 <= len(raw) <= MAX_BYTES for raw in raw_files)
    ):
        raise UploadSecurityDenied("INPUT_INVALID")
    deadline = None
    results = []
    for raw in raw_files:
        identifier = sha256(raw).hexdigest()
        if not applicable(identifier):
            results.append(None)
            continue
        cases._guard(True)
        selected = configuration()
        if deadline is None:
            deadline = monotonic() + selected[1].timeout_seconds
        try:
            current = require(identifier, len(raw))
        except UploadSecurityDenied as exc:
            if exc.status == "BLOCKED":
                raise
            current = None
        if current is not None:
            _admission(raw, admission, selected)
            results.append(current)
            continue
        if connection.in_atomic_block:
            raise UploadSecurityDenied("PREFLIGHT_REQUIRED")
        _admission(raw, admission, selected)
        status, answer = "UNAVAILABLE", None
        if selected[4] is not None:
            remaining = deadline - monotonic()
            if remaining <= 0:
                status = "TIMED_OUT"
            else:
                state, value = invoke(
                    selected[3], ScanInput(raw, identifier, len(raw), deadline), remaining
                )
                status, answer = (
                    _verdict(value, selected, identifier, len(raw))
                    if state == "RETURNED" and monotonic() <= deadline
                    else ("TIMED_OUT" if state == "RETURNED" else state, None)
                )
        outcome = _terminal(identifier, selected, status, answer)
        if outcome.status != "CLEAN":
            raise UploadSecurityDenied(outcome.status)
        results.append(require(identifier, len(raw)))
    return results
