"""Exact reviewed optional media, with an independently authorized text boundary."""

from contextlib import contextmanager

from django.conf import settings

from apps.casework import services as cases
from apps.casework.models import Case
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.experimental_publication.models import PublicationEdition
from apps.library_preview import services as preview
from apps.platform_recovery.integration import mutation_context
from apps.public_knowledge.services import _source_configuration

from . import services
from .boundaries import (
    Boundary,
    SourceChanged,
    assert_projection_state,
    assert_snapshot,
    core_state,
)
from .models import PublicMediaEdition


class OptionalMediaUnavailable(preview.PreviewUnavailable):
    """Only an independently revalidated text-only response may replace this view."""


def _base_state(case_id):
    from apps.knowledge_links.models import KnowledgeAction, KnowledgeRevision

    return (
        core_state(case_id),
        list(
            KnowledgeRevision.objects.filter(publication__case_id=case_id).order_by("pk").values()
        ),
        list(
            KnowledgeAction.objects.filter(revision__publication__case_id=case_id)
            .order_by("pk")
            .values()
        ),
    )


@contextmanager
def _unchanged_base(case_id, before, configuration):
    """Classify source revocation before the owning transaction rolls it back."""
    try:
        yield
    except Exception as exc:
        if _base_state(case_id) != before or _source_configuration() != configuration:
            raise preview.PreviewUnavailable() from exc
        raise
    if _base_state(case_id) != before or _source_configuration() != configuration:
        raise preview.PreviewUnavailable()


def _public_dto(row, part, transcript, actions):
    audio_url = f"/library-preview/recordings/{row.pk}/audio/"
    result = {
        "id": str(row.pk),
        "label": row.label,
        "number": row.number,
        "audio_url": audio_url,
        "media_type": part.media_type,
        "text": transcript.text if transcript else "",
        "transcript_reviewed": transcript is not None,
        "transcript_version": transcript.number if transcript else None,
        "segments": [],
    }
    if transcript:
        for index, segment in enumerate(transcript.segments):
            result["segments"].append(
                {
                    "index": index,
                    "text": transcript.text[segment["char_start"] : segment["char_end"]],
                    "start_ms": segment["start_ms"],
                    "end_ms": segment["end_ms"],
                    "seconds_label": f"{segment['start_ms'] / 1000:g}–{segment['end_ms'] / 1000:g}",
                    "url": f"/library-preview/recordings/{row.pk}/segments/{index}/",
                    "audio_url": audio_url
                    + f"#t={segment['start_ms'] / 1000:g},{segment['end_ms'] / 1000:g}",
                }
            )
    return result


def _candidate(guard, row):
    release = row.actions.filter(action="RELEASE").first()
    if release is None:
        raise cases.CaseConflict("recording_public_release_required")
    actor = guard.actor(release.subject_id, release.auth_epoch, release.provider_id)
    row, part, raw, transcript, actions = services._edition(guard, actor, row.pk, released=True)
    return (
        _public_dto(row, part, transcript, actions),
        raw,
        services.safe_filename(row.pk, part.media_type),
    )


def _check_optional(guard, *, callbacks=False, pure=False):
    try:
        if callbacks:
            guard.finish()
        elif pure:
            assert_projection_state(guard.pin)
        else:
            assert_snapshot(guard.pin)
    except SourceChanged as exc:
        raise preview.PreviewUnavailable() from exc
    except cases.CaseConflict as exc:
        # Classify before the enclosing canonical media boundary maps ordinary
        # case conflicts to whole-publication denials.
        raise OptionalMediaUnavailable() from exc


@mutation_context
@contextmanager
def publication_projection(publication_id, *, include_media=True, required_media_id=None):
    """Keep this context open through actual render or actual bounded file assembly.

    A failed optional attachment never supplies permission to retain stale text.
    Source changes raise the ordinary preview denial and prohibit the fallback.
    """
    selected = preview._start()
    guard, before, case_id = None, None, None
    try:
        with synthetic_queue_atomic():
            source = PublicationEdition.objects.filter(pk=cases._uuid(publication_id)).first()
            if source is None:
                raise preview.PreviewUnavailable()
            case_id = source.case_id
            from apps.precise_citations.integration import prelock_cases

            # Acquire the shared source graph and all citation dependencies in
            # UUID order before this reader takes its first canonical case lock.
            prelock_cases([case_id])
            case = Case.objects.select_for_update().get(pk=case_id)
            before = _base_state(case_id)
            configuration = _source_configuration()
            # This boundary owns the citation answer-use coordinator as well
            # as original-media guards through rendering and final callbacks.
            with preview._media_boundary():
                with (
                    _unchanged_base(case_id, before, configuration),
                    preview._current(selected, str(source.pk)) as source,
                ):
                    text = preview._projection(selected, source)
                    rows, files = [], {}
                    media_enabled = (
                        include_media
                        and getattr(settings, "FATWA_PUBLIC_ANSWER_MEDIA_ENABLED", False) is True
                        and getattr(settings, "FATWA_PUBLIC_ANSWER_MEDIA_PUBLIC_ENABLED", False)
                        is True
                    )
                    candidates = []
                    if media_enabled:
                        # The latest released edition for each original is authoritative;
                        # withdrawing it must never resurrect an earlier public edition.
                        seen = set()
                        for row in PublicMediaEdition.objects.filter(
                            publication=source, actions__action="RELEASE"
                        ).order_by("part_id", "-number"):
                            if row.part_id not in seen:
                                candidates.append(row)
                                seen.add(row.part_id)
                    if candidates:
                        try:
                            directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
                            guard = Boundary(case, directory)
                            for row in candidates:
                                dto, raw, filename = _candidate(guard, row)
                                rows.append(dto)
                                files[dto["id"]] = {
                                    "raw": raw,
                                    "filename": filename,
                                    "media_type": dto["media_type"],
                                }
                            guard.before_write()
                        except cases.CaseConflict as exc:
                            if _base_state(case_id) != before:
                                raise preview.PreviewUnavailable() from exc
                            raise OptionalMediaUnavailable() from exc
                    if required_media_id is not None and str(required_media_id) not in files:
                        raise preview.PreviewUnavailable()
                    yield {
                        "publication": text,
                        "recordings": rows,
                        "files": files,
                        "media_snapshot": guard.pin if guard else None,
                    }
                    if guard:
                        _check_optional(guard, callbacks=True)
                    # Re-resolve the exact independently authorized text after any
                    # template or optional-media callback. No private DTO is reused.
                    with preview._current(selected, str(source.pk)) as current:
                        if preview._projection(selected, current) != text:
                            raise preview.PreviewUnavailable()
                # The previous context's final source callbacks have also completed.
                if _base_state(case_id) != before or _source_configuration() != configuration:
                    raise preview.PreviewUnavailable()
                if guard:
                    _check_optional(guard)
                preview._recheck(selected)
            # Source/citation guards can call adapters during their own exit.
            # All bytes have already been consumed; only pure checks follow, so
            # a late source callback cannot revoke earlier media permission and
            # still let stale optional content leave this enclosing transaction.
            if _base_state(case_id) != before or _source_configuration() != configuration:
                raise preview.PreviewUnavailable()
            if guard:
                _check_optional(guard, pure=True)
            preview._recheck(selected)
    except SourceChanged as exc:
        raise preview.PreviewUnavailable() from exc
    except cases.CaseConflict as exc:
        if case_id and before is not None and _base_state(case_id) != before:
            raise preview.PreviewUnavailable() from exc
        raise OptionalMediaUnavailable() from exc


@contextmanager
def recording_projection(media_id):
    row = PublicMediaEdition.objects.filter(pk=cases._uuid(media_id)).first()
    if row is None:
        raise preview.PreviewUnavailable()
    with publication_projection(row.publication_id, required_media_id=row.pk) as result:
        recording = next(item for item in result["recordings"] if item["id"] == str(row.pk))
        yield {
            "recording": recording,
            "publication": result["publication"],
            "file": result["files"][str(row.pk)],
        }
