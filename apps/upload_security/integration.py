"""Internal preflight over each real domain authority; no scanner grants access."""

from hashlib import sha256

from apps.casework import services as cases

from . import services
from .contract import MAX_BYTES, MAX_FILES, Admission


def active(raw_files):
    if not raw_files:
        return False
    if (
        type(raw_files) not in {list, tuple}
        or not 1 <= len(raw_files) <= MAX_FILES
        or any(type(raw) is not bytes or not 1 <= len(raw) <= MAX_BYTES for raw in raw_files)
    ):
        raise services.UploadSecurityDenied("INPUT_INVALID")
    return any(services.applicable(sha256(raw).hexdigest()) for raw in raw_files)


def staff_admission(case, actor, provider, purpose):
    return Admission(
        str(case.pk),
        provider.provider_id,
        actor.subject_id,
        actor.auth_epoch,
        purpose,
        case.revision,
        case.evidence_version,
    )


def requester_admission(case, token, purpose):
    return Admission(
        str(case.pk),
        "casework-requester",
        case.requester_id,
        cases._digest(token),
        purpose,
        case.revision,
        case.evidence_version,
    )


def prepare_authorized(raw_files, authorize):
    """Capture actual current authority twice, outside the engine invocation.

    `authorize` is a closed local function supplied by a domain service, never a
    request/provider callback. It opens and closes the existing owned boundary.
    Canonical writes still run their original authorization/CAS afterward.
    """
    if not active(raw_files):
        return
    initial = authorize()
    services.prepare_many(raw_files, admission=initial)
    if authorize() != initial:
        raise services.UploadSecurityDenied("ADMISSION_CHANGED")


def requester_files(
    *, raw_files, token, expected_revision, synthetic_fixtures_only=False, allow_clarification=False
):
    def authorize():
        from apps.case_attachments import services as attachments

        attachments._enabled()
        with cases._token_case(token, synthetic_fixtures_only) as case:
            cases._versions(case, expected_revision)
            if not allow_clarification and case.stage == "NEEDS_CLARIFICATION":
                raise cases.CaseConflict("requester_clarification_still_required")
            if (
                attachments.CaseAttachment.objects.filter(case=case).count()
                >= attachments.MAX_ATTACHMENTS
            ):
                raise cases.CaseConflict("attachment_capacity")
            return requester_admission(case, token, "CASE_ATTACHMENT")

    prepare_authorized(raw_files, authorize)


def answer_files(
    *,
    files,
    case_id,
    subject_id,
    provider,
    expected_revision,
    expected_evidence_version,
    synthetic_fixtures_only=False,
):
    if type(files) not in {list, tuple} or any(
        type(file) is not dict or set(file) != {"raw", "filename", "media_type"} for file in files
    ):
        raise cases.CaseConflict("answer_file_invalid")

    def authorize():
        from apps.answer_media import services as answers

        answers._enabled()
        with cases._staff_case(
            case_id,
            subject_id,
            provider,
            synthetic_fixtures_only,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
        ) as (case, actor):
            if case.stage == "NEEDS_CLARIFICATION":
                raise cases.CaseConflict("requester_clarification_still_required")
            return staff_admission(case, actor, provider, "ANSWER_FILE")

    prepare_authorized([file["raw"] for file in files], authorize)


def library_file(*, raw, namespace, external_id, expected_version, **base):
    if not raw:
        return

    def authorize():
        from apps.research_library import services as library

        with library.staff_boundary(**base) as (case, actor):
            library._permit(
                case, actor, base["provider"], "EDIT", namespace=namespace, external_id=external_id
            )
            previous = (
                library.LibraryVersion.objects.filter(
                    item__case=case,
                    item__namespace=namespace,
                    item__external_id=external_id,
                )
                .order_by("-number")
                .first()
            )
            if (previous.number if previous else 0) != expected_version:
                raise cases.CaseConflict("library_version_changed")
            if previous is not None:
                library._permit(case, actor, base["provider"], "EDIT", **library._fields(previous))
            return staff_admission(case, actor, base["provider"], "LIBRARY_FILE")

    prepare_authorized([raw], authorize)


def import_source(*, raw, filename, namespace, **base):
    from apps.material_import import formats, policy

    formats.identifier(namespace)

    def authorize():
        with policy.boundary(**base, action="STAGE", namespace=namespace) as (case, actor):
            from apps.material_import.services import _pins

            _pins(case, base)
            return staff_admission(case, actor, base["provider"], "IMPORT_FILE")

    prepare_authorized([raw], authorize)
    # Only an admitted envelope reaches the bounded ZIP/record parser. Every
    # extracted manifest file receives an independent receipt before any use.
    parsed = formats.parse(raw, filename)
    prepare_authorized([file.raw for file in parsed.files.values()], authorize)
    return parsed


def require_bytes(raw):
    if type(raw) is not bytes:
        raise services.UploadSecurityDenied("INPUT_INVALID")
    return services.require(sha256(raw).hexdigest(), len(raw))


def transcript_bundle(*, raw, case_id, subject_id, provider, synthetic_fixtures_only=False):
    from apps.fast8_transcript_queue.workbench.services import _read_archive
    from apps.transcript_case_links.models import TranscriptUpload

    def authorize():
        with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
            case,
            actor,
        ):
            if TranscriptUpload.objects.filter(case=case).count() >= 32:
                # Existing exact replay remains available; only new sources consume capacity.
                if not TranscriptUpload.objects.filter(
                    case=case, sha256=sha256(raw).hexdigest()
                ).exists():
                    raise cases.CaseConflict("transcript_upload_capacity")
            return staff_admission(case, actor, provider, "TRANSCRIPT_BUNDLE")

    prepare_authorized([raw], authorize)
    if active([raw]):
        # The existing bounded stored-member reader precedes all text/manifest
        # interpretation. Every member is separately scanned before reconstruction.
        prepare_authorized(list(_read_archive(raw).values()), authorize)


def owner_file(row):
    """Only canonical authored text/validated links are not uploaded files."""
    if row._meta.label_lower == "answer_media.answerpart":
        if row.kind == "TEXT":
            raw = row.manifest.answer.text.encode()
            if (
                row.ordinal == 1
                and row.source == "MUFTI_AUTHORED"
                and row.media_type == "text/plain"
                and not row.filename
                and row.metadata == {}
                and row.storage_backend == "inline-database-v1"
                and row.original is not None
                and bytes(row.original) == raw
                and row.size == len(raw)
                and row.sha256 == sha256(raw).hexdigest()
            ):
                return
            raise services.UploadSecurityDenied("INTEGRITY")
        from apps.answer_media import youtube

        if row.kind == youtube.KIND:
            if (
                row.original is None
                or row.storage_backend != "inline-database-v1"
                or row.source != "MUFTI_AUTHORED"
            ):
                raise services.UploadSecurityDenied("INTEGRITY")
            youtube.verify(row, bytes(row.original))
            return
    services.require(row.sha256, row.size)
