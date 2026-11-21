"""Human reviewed navigation over existing publication/citation/transcript services."""

import json
from contextlib import contextmanager
from hashlib import sha256

from django.conf import settings

from apps.case_citations import services as citations
from apps.casework import services as cases
from apps.editorial_search.query_terms import normalize_editorial_search
from apps.experimental_publication import services as publications
from apps.experimental_publication.models import PublicationEdition
from apps.platform_recovery.integration import mutation_service
from apps.reference.models import ReferenceHeading
from apps.transcript_case_links import services as transcripts
from apps.transcript_case_links.models import TranscriptLink

from .authority import KnowledgeAuthority
from .models import KnowledgeAction, KnowledgeRevision


def _enabled():
    publications._enabled()
    if getattr(settings, "FATWA_KNOWLEDGE_LINKS_ENABLED", False) is not True:
        raise cases.CaseConflict("knowledge_links_disabled")


def _digest(value):
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _permit(actor, provider, case, action, kind):
    authority = getattr(settings, "FATWA_KNOWLEDGE_LINKS_AUTHORITY", None)
    if not isinstance(authority, KnowledgeAuthority):
        raise cases.CaseConflict("knowledge_authority_required")
    try:
        allowed = authority.permits(
            provider_id=provider.provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
            case_ref=case.public_ref,
            action=action,
            kind=kind,
        )
    except Exception as exc:
        raise cases.CaseConflict("knowledge_authority_unavailable") from exc
    if allowed is not True:
        raise cases.CaseConflict("knowledge_action_denied")


def _recheck(case, actor, provider):
    if cases._identity(provider, actor.subject_id, case).auth_epoch != actor.auth_epoch:
        raise cases.CaseConflict("knowledge_identity_changed")


@contextmanager
def _edition(publication_id, subject_id, provider, synthetic_fixtures_only):
    _enabled()
    # Direct open retains the exact current case and publication checks below.
    # It must not borrow search permission or reveal unrelated library rows.
    edition = PublicationEdition.objects.filter(pk=cases._uuid(publication_id)).first()
    if edition is None:
        raise cases.CaseConflict("knowledge_publication_unavailable")
    with (
        cases._staff_case(edition.case_id, subject_id, provider, synthetic_fixtures_only) as (
            case, actor,
        ),
        citations._projection_expiry_guard(),
    ):
        # Revalidate under canonical lock (withdrawal/correction share this lock).
        publications._approved(case, edition)
        publications._verify(edition)
        latest = (
            PublicationEdition.objects.filter(case=case, actions__action="APPROVE")
            .order_by("-number")
            .first()
        )
        if (
            latest is None
            or latest.pk != edition.pk
            or edition.actions.filter(action="WITHDRAW").exists()
            or edition.citations != publications._citation_snapshot(edition.answer)
        ):
            raise cases.CaseConflict("knowledge_publication_unavailable")
        # The exact read replaces the old whole-library selector, while retaining
        # its uniform unavailable result when the publication's current source
        # rights have lapsed. Do not expose an internal source denial as a new
        # contract or silently grant the publication through metadata rights.
        from apps.data_privacy.services import PrivacyDenied

        try:
            public = publications._projection(edition)
        except PrivacyDenied:
            raise
        except cases.CaseConflict as exc:
            raise cases.CaseConflict("knowledge_publication_unavailable") from exc
        yield edition, public, case, actor
        _recheck(case, actor, provider)


@contextmanager
def _withdrawal_edition(publication_id, subject_id, provider, synthetic_fixtures_only):
    """Revocation must remain possible after publication/source availability lapses."""
    _enabled()
    edition = PublicationEdition.objects.filter(pk=cases._uuid(publication_id)).first()
    if edition is None:
        raise cases.CaseConflict("knowledge_publication_unavailable")
    with cases._staff_case(edition.case_id, subject_id, provider, synthetic_fixtures_only) as (
        case,
        actor,
    ):
        publications._verify(edition)
        yield edition, None, case, actor
        _recheck(case, actor, provider)


def _transcripts_locked(edition):
    """Internal read adapter: caller holds the authorized canonical case lock.

    Public read_links opens its own pre-transaction ownership guard, so cannot
    be nested. Reuse its source parser and binding validator without bypassing
    the outer case/identity/ownership gate or editing that application's API.
    """
    result = []
    for link in TranscriptLink.objects.filter(case_id=edition.case_id).select_related(
        "upload", "evidence", "event"
    ):
        from apps.data_privacy.resource_hooks import transcript as privacy
        from apps.data_privacy.services import PrivacyDenied

        try:
            privacy(edition.case, link.pk)
        except PrivacyDenied:
            continue
        raw = bytes(link.upload.bundle)
        if sha256(raw).hexdigest() != link.upload.sha256:
            raise cases.CaseConflict("transcript_binding_inconsistent")
        entry = next(
            (entry for entry in transcripts._entries(raw) if entry.external_id == link.external_id),
            None,
        )
        if entry is None:
            raise cases.CaseConflict("transcript_binding_inconsistent")
        transcripts._check_link(link, entry)
        result.append(
            {
                "id": str(link.pk),
                "version": link.evidence.version,
                "entry": entry,
                "bundle_sha256": link.upload.sha256,
            }
        )
    return result


def _permits_material(case, *, source=None, transcript_id=None, usage):
    if source is not None:
        return citations._permits_source(case, source, usage)
    try:
        from apps.data_privacy.resource_hooks import transcript as privacy

        privacy(case, transcript_id)
        rights = citations._rights_services()
        return (
            rights is None
            or rights.permits_transcript_for_locked_case(
                case=case, transcript_id=transcript_id, usage=usage
            )
            is True
        )
    except cases.CaseConflict:
        return False


def _row_permitted(case, row, usage):
    from apps.data_privacy.integration import allowed as privacy_allowed

    if not privacy_allowed("KNOWLEDGE_REVISION", row.pk):
        return False
    return _permits_material(
        case,
        source={key: row.snapshot[key] for key in ("source", "source_sha256")}
        if row.heading_id
        else None,
        transcript_id=row.transcript_id,
        usage=usage,
    )


def _target(edition, kind, target_id, subject_id, provider):
    if kind == "REFERENCE":
        if type(target_id) is not int or not 1 <= target_id <= 2**63 - 1:
            raise cases.CaseConflict("knowledge_target_unavailable")
        heading = ReferenceHeading.objects.filter(pk=target_id).first()
        if heading is None:
            raise cases.CaseConflict("knowledge_target_unavailable")
        citations._enabled()
        source = citations._source(heading.edition_id, heading.source_row_id)
        citations._require_source(edition.case, source, "RELATE")
        if source not in edition.citations:
            raise cases.CaseConflict("knowledge_publication_citation_required")
        return {"kind": kind, **source}, heading, None
    if kind == "TRANSCRIPT":
        link = TranscriptLink.objects.filter(
            pk=cases._uuid(target_id), case_id=edition.case_id
        ).first()
        if link is None or link.evidence.version > edition.evidence_version:
            raise cases.CaseConflict("knowledge_target_unavailable")
        if not _permits_material(edition.case, transcript_id=link.pk, usage="RELATE"):
            raise cases.CaseConflict("current_source_rights_required")
        rows = _transcripts_locked(edition)
        row = next((row for row in rows if row["id"] == str(link.pk)), None)
        if row is None:
            raise cases.CaseConflict("knowledge_target_unavailable")
        entry = row["entry"]
        # These pins remain private. Neither transcript text nor source identifiers
        # are copied into the library projection/search index.
        return (
            {
                "kind": kind,
                "link_id": row["id"],
                "bundle_sha256": row["bundle_sha256"],
                "source_id": entry.source_id,
                "source_sha256": entry.source_sha256,
                "pair_id": entry.pair_id,
                "question_sha256": entry.question.sha256,
                "start_ms": entry.question.start_ms,
                "end_ms": entry.question.end_ms,
            },
            None,
            link,
        )
    raise cases.CaseConflict("knowledge_kind_invalid")


def _latest(row):
    if KnowledgeRevision.objects.filter(series=row.series, number__gt=row.number).exists():
        raise cases.CaseConflict("knowledge_revision_changed")


def _verified(row, edition, subject_id, provider):
    if row.snapshot_sha256 != _digest(row.snapshot):
        raise cases.CaseConflict("knowledge_snapshot_changed")
    kind = "REFERENCE" if row.heading_id else "TRANSCRIPT"
    current, _, _ = _target(
        edition, kind, row.heading_id or row.transcript_id, subject_id, provider
    )
    if current != row.snapshot:
        raise cases.CaseConflict("knowledge_source_changed")
    return kind


def _state(row):
    actions = set(row.actions.values_list("action", flat=True))
    return (
        "WITHDRAWN"
        if "WITHDRAW" in actions
        else ("APPROVED" if "APPROVE" in actions else "PROPOSED")
    )


@mutation_service
def propose(
    *,
    publication_id,
    kind,
    target_id,
    reason,
    subject_id,
    provider,
    replaces_id=None,
    synthetic_fixtures_only=False,
):
    cases._text(reason)
    if len(reason) > 1000:
        raise cases.CaseConflict("knowledge_reason_too_long")
    with _edition(publication_id, subject_id, provider, synthetic_fixtures_only) as (
        edition,
        _,
        case,
        actor,
    ):
        snapshot, heading, transcript = _target(edition, kind, target_id, subject_id, provider)
        previous = None
        if replaces_id:
            previous = KnowledgeRevision.objects.filter(
                pk=cases._uuid(replaces_id), publication=edition
            ).first()
            if previous is None:
                raise cases.CaseConflict("knowledge_revision_unavailable")
            _latest(previous)
            if previous.number >= 64:
                raise cases.CaseConflict("knowledge_revision_capacity")
        elif KnowledgeRevision.objects.filter(publication=edition, number=1).count() >= 32:
            raise cases.CaseConflict("knowledge_link_capacity")
        _recheck(case, actor, provider)
        kwargs = {"series": previous.series} if previous else {}
        row = KnowledgeRevision.objects.create(
            publication=edition,
            number=previous.number + 1 if previous else 1,
            heading=heading,
            transcript=transcript,
            snapshot=snapshot,
            snapshot_sha256=_digest(snapshot),
            reason=reason,
            subject_id=actor.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=actor.auth_epoch,
            **kwargs,
        )
        return {"id": str(row.pk), "number": row.number, "state": "PROPOSED"}


@mutation_service
def act(
    *,
    publication_id,
    revision_id,
    action,
    confirmed,
    subject_id,
    provider,
    synthetic_fixtures_only=False,
):
    if action not in {"APPROVE", "WITHDRAW"} or confirmed is not True:
        raise cases.CaseConflict("knowledge_explicit_review_required")
    scope = _withdrawal_edition if action == "WITHDRAW" else _edition
    with scope(publication_id, subject_id, provider, synthetic_fixtures_only) as (
        edition,
        _,
        case,
        actor,
    ):
        row = KnowledgeRevision.objects.filter(
            pk=cases._uuid(revision_id), publication=edition
        ).first()
        if row is None:
            raise cases.CaseConflict("knowledge_revision_unavailable")
        _latest(row)
        state = _state(row)
        if state == "WITHDRAWN" or (action == "APPROVE" and state != "PROPOSED"):
            raise cases.CaseConflict("knowledge_transition_invalid")
        kind = "REFERENCE" if row.heading_id else "TRANSCRIPT"
        if action == "APPROVE":
            _verified(row, edition, subject_id, provider)
            if (row.provider_id, row.subject_id) == (provider.provider_id, subject_id):
                raise cases.CaseConflict("knowledge_independent_review_required")
        _permit(actor, provider, case, action, kind)
        _recheck(case, actor, provider)
        KnowledgeAction.objects.create(
            revision=row,
            action=action,
            subject_id=actor.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=actor.auth_epoch,
        )
        return {"id": str(row.pk), "state": _state(row)}


def _public(row):
    data = {
        "id": str(row.pk),
        "number": row.number,
        "state": "APPROVED",
        "kind": row.snapshot["kind"],
    }
    if row.heading_id:
        source = row.snapshot["source"]
        data.update(title=source["heading_title"], source=source)
    else:
        data["title"] = "سؤال من درس / تفريغ مرتبط — فتح خاص مصرح"
    return data


@mutation_service
def browse(*, publication_id, subject_id, provider, query="", synthetic_fixtures_only=False):
    cases._text(query, optional=True)
    if len(query) > 80:
        raise cases.CaseConflict("knowledge_query_too_long")
    query = normalize_editorial_search(query)
    with _edition(publication_id, subject_id, provider, synthetic_fixtures_only) as (
        edition,
        public,
        case,
        _actor,
    ):
        from apps.data_privacy.integration import allowed as privacy_allowed
        from apps.data_privacy.integration import current as privacy

        privacy("CASE", case.pk, action="SEARCH")
        results = []
        rows = KnowledgeRevision.objects.filter(publication=edition).order_by("series", "-number")
        seen = set()
        for row in rows:
            if row.series in seen:
                continue
            seen.add(row.series)
            if _state(row) != "APPROVED":
                continue
            if not privacy_allowed("KNOWLEDGE_REVISION", row.pk, action="SEARCH"):
                continue
            try:
                _verified(row, edition, subject_id, provider)
                if not _row_permitted(case, row, "READ"):
                    continue
            except cases.CaseConflict:
                continue
            result = _public(row)
            # Whitelisted public source metadata only. No private notes/transcript text.
            source = result.get("source", {})
            search_text = (
                " ".join(
                    str(source.get(key, ""))
                    for key in (
                        "work_title",
                        "heading_title",
                        "edition_title",
                        "edition_key",
                        "publisher",
                        "printed_part",
                        "printed_page",
                    )
                )
                + " "
                + result["title"]
            )
            if not query or query in normalize_editorial_search(search_text):
                results.append(result)
        return {"publication": public, "links": results}


def _open_material(
    *,
    publication_id,
    revision_id,
    subject_id,
    provider,
    synthetic_fixtures_only=False,
    preview=False,
):
    with _edition(publication_id, subject_id, provider, synthetic_fixtures_only) as (
        edition,
        _,
        case,
        actor,
    ):
        row = KnowledgeRevision.objects.filter(
            pk=cases._uuid(revision_id), publication=edition
        ).first()
        if row is None:
            raise cases.CaseConflict("knowledge_revision_unavailable")
        from apps.data_privacy.integration import current as privacy

        privacy("KNOWLEDGE_REVISION", row.pk)
        _latest(row)
        if _state(row) not in ({"PROPOSED", "APPROVED"} if preview else {"APPROVED"}):
            raise cases.CaseConflict("knowledge_approved_relation_required")
        kind = _verified(row, edition, subject_id, provider)
        if not _row_permitted(case, row, "READ"):
            raise cases.CaseConflict("current_source_rights_required")
        result = _public(row)
        result["state"] = _state(row)
        if kind == "TRANSCRIPT":
            _permit(actor, provider, case, "OPEN_TRANSCRIPT", kind)
            entries = _transcripts_locked(edition)
            entry = next(item["entry"] for item in entries if item["id"] == str(row.transcript_id))
            result["material"] = {
                "source_id": entry.source_id,
                "pair_id": entry.pair_id,
                "text": entry.question.text,
                "start_ms": entry.question.start_ms,
                "end_ms": entry.question.end_ms,
            }
        return result


@mutation_service
def desk(*, publication_id, subject_id, provider, synthetic_fixtures_only=False):
    with _edition(publication_id, subject_id, provider, synthetic_fixtures_only) as (
        edition,
        public,
        case,
        _actor,
    ):
        candidates = []
        for item in edition.citations:
            if not all(
                citations._permits_source(case, item, usage) for usage in ("READ", "RELATE")
            ):
                continue
            source = item["source"]
            heading = ReferenceHeading.objects.get(
                edition_id=source["edition_id"], source_row_id=source["source_row_id"]
            )
            candidates.append(
                {
                    "kind": "REFERENCE",
                    "target_id": str(heading.pk),
                    "title": source["heading_title"],
                }
            )
        for row in _transcripts_locked(edition):
            if row["version"] <= edition.evidence_version and all(
                _permits_material(case, transcript_id=row["id"], usage=usage)
                for usage in ("READ", "RELATE")
            ):
                candidates.append(
                    {
                        "kind": "TRANSCRIPT",
                        "target_id": row["id"],
                        "title": "سؤال تفريغ مرتبط بالقضية",
                    }
                )
        history = []
        for row in KnowledgeRevision.objects.filter(publication=edition).order_by(
            "series", "-number"
        ):
            from apps.data_privacy.integration import allowed as privacy_allowed

            if not privacy_allowed("KNOWLEDGE_REVISION", row.pk):
                continue
            history.append(
                {
                    "id": str(row.pk),
                    "number": row.number,
                    "state": _state(row),
                    "reason": row.reason if _row_permitted(case, row, "READ") else "",
                    "actor": row.subject_id,
                    "created_at": row.created_at,
                    "kind": "REFERENCE" if row.heading_id else "TRANSCRIPT",
                    "actions": list(row.actions.values("action", "subject_id", "created_at")),
                }
            )
        return {"publication": public, "candidates": candidates, "history": history}


@mutation_service
def open_material(
    *, publication_id, revision_id, subject_id, provider, synthetic_fixtures_only=False
):
    return _open_material(
        publication_id=publication_id,
        revision_id=revision_id,
        subject_id=subject_id,
        provider=provider,
        synthetic_fixtures_only=synthetic_fixtures_only,
    )


@mutation_service
def preview_material(
    *, publication_id, revision_id, subject_id, provider, synthetic_fixtures_only=False
):
    """Private review only: never emits a proposed link in library search."""
    return _open_material(
        publication_id=publication_id,
        revision_id=revision_id,
        subject_id=subject_id,
        provider=provider,
        preview=True,
        synthetic_fixtures_only=synthetic_fixtures_only,
    )


@mutation_service
def history(*, publication_id, subject_id, provider, synthetic_fixtures_only=False):
    """Private audit stays readable after publication withdrawal/correction."""
    _enabled()
    edition = PublicationEdition.objects.filter(pk=cases._uuid(publication_id)).first()
    if edition is None:
        raise cases.CaseConflict("knowledge_publication_unavailable")
    with cases._staff_case(edition.case_id, subject_id, provider, synthetic_fixtures_only) as (
        case,
        actor,
    ):
        rows = []
        for row in KnowledgeRevision.objects.filter(publication=edition).order_by(
            "series", "-number"
        ):
            from apps.data_privacy.integration import allowed as privacy_allowed

            if not privacy_allowed("KNOWLEDGE_REVISION", row.pk):
                continue
            if row.snapshot_sha256 != _digest(row.snapshot):
                raise cases.CaseConflict("knowledge_snapshot_changed")
            rows.append(
                {
                    "id": str(row.pk),
                    "series": str(row.series),
                    "number": row.number,
                    "state": _state(row),
                    "reason": row.reason if _row_permitted(case, row, "READ") else "",
                    "snapshot": row.snapshot if _row_permitted(case, row, "READ") else None,
                    "rights_restricted": not _row_permitted(case, row, "READ"),
                    "subject_id": row.subject_id,
                    "provider_id": row.provider_id,
                    "auth_epoch": row.auth_epoch,
                    "created_at": row.created_at,
                    "actions": list(
                        row.actions.values(
                            "action", "subject_id", "provider_id", "auth_epoch", "created_at"
                        )
                    ),
                }
            )
        _recheck(case, actor, provider)
        return {"publication_id": str(edition.pk), "history": rows}
