"""Explicit authorized human review, never an automatic gold-benchmark promotion."""

import json
from abc import ABC, abstractmethod
from hashlib import sha256
from pathlib import Path

from django.conf import settings

from apps.casework import services as cases
from apps.platform_recovery.integration import mutation_service
from apps.research_workspace import services as workspace

from .evaluation import authorized
from .models import EvaluationDecision, EvaluationRevision
from .ranking import VERSION, query_tokens


class EvaluationAuthority(ABC):
    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action):
        """Explicit policy for VIEW/PROPOSE/APPROVE/REJECT; no inferred role grant."""
        raise NotImplementedError


def ranker_identity():
    return VERSION + ":" + sha256(Path(__file__).with_name("ranking.py").read_bytes()).hexdigest()


def _permit(case, actor, provider, action):
    workspace._enabled()
    authority = getattr(settings, "FATWA_ARABIC_SEARCH_REVIEW_AUTHORITY", None)
    if getattr(settings, "FATWA_ARABIC_SEARCH_REVIEW_ENABLED", False) is not True or not isinstance(
        authority, EvaluationAuthority
    ):
        raise cases.CaseConflict("evaluation_review_disabled")
    try:
        allowed = authority.permits(
            provider_id=provider.provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
            case_ref=case.public_ref,
            action=action,
        )
    except Exception as exc:
        raise cases.CaseConflict("evaluation_authority_unavailable") from exc
    if allowed is not True:
        raise cases.CaseConflict("evaluation_action_denied")


def _text(value, maximum=1000):
    cases._text(value)
    if len(value) > maximum:
        raise cases.CaseConflict("evaluation_text_invalid")


def validate_bundle(bundle):
    """Only explicit bounded synthetic corpus + authored expectations, no generated truth."""
    try:
        raw = json.dumps(bundle, ensure_ascii=False, allow_nan=False).encode()
        if len(raw) > 150000 or type(bundle) is not dict:
            raise ValueError()
        if (
            set(bundle) != {"synthetic_only", "clock", "records", "queries"}
            or bundle["synthetic_only"] is not True
        ):
            raise ValueError()
        records, queries = bundle["records"], bundle["queries"]
        if (
            type(records) is not list
            or type(queries) is not list
            or not 1 <= len(records) <= 64
            or not 1 <= len(queries) <= 64
        ):
            raise ValueError()
        from datetime import datetime

        if datetime.fromisoformat(bundle["clock"]).tzinfo is None:
            raise ValueError()
        ids, qids = set(), set()
        for row in records:
            if (
                set(row) != {"id", "title", "scope", "edition", "read", "expires"}
                or type(row["read"]) is not bool
            ):
                raise ValueError()
            for name in ("id", "scope", "edition"):
                _text(row[name], 80)
            _text(row["title"], 2000)
            if row["id"] in ids or datetime.fromisoformat(row["expires"]).tzinfo is None:
                raise ValueError()
            ids.add(row["id"])
        for q in queries:
            if set(q) not in (
                {"id", "query", "expected", "rationale", "scope", "edition"},
                {"id", "query", "expected", "rationale", "scope", "edition", "expected_error"},
            ):
                raise ValueError()
            for key in ("id", "scope", "edition"):
                _text(q[key], 80)
            _text(q["rationale"])
            if q["id"] in qids or type(q["query"]) is not str or len(q["query"]) > 200:
                raise ValueError()
            qids.add(q["id"])
            if (
                type(q["expected"]) is not list
                or len(q["expected"]) > 64
                or any(type(i) is not str for i in q["expected"])
            ):
                raise ValueError()
            if len(q["expected"]) != len(set(q["expected"])) or set(q["expected"]) - {
                r["id"] for r in authorized(bundle, q)
            }:
                raise ValueError()
            try:
                query_tokens(q["query"])
            except ValueError:
                if q.get("expected_error") != "invalid_search_query" or q["expected"]:
                    raise ValueError()
            else:
                if "expected_error" in q:
                    raise ValueError()
        return {k: bundle[k] for k in ("synthetic_only", "clock", "records")}, queries
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
        raise cases.CaseConflict("evaluation_bundle_invalid") from exc


def _current(case):
    return (
        EvaluationRevision.objects.filter(case=case, engine="TITLE_WORDS")
        .order_by("-number")
        .first()
    )


def _verify(row):
    if (
        workspace._digest(row.corpus) != row.corpus_sha256
        or workspace._digest(row.judgements) != row.judgements_sha256
    ):
        raise cases.CaseConflict("evaluation_digest_changed")


def _data(row):
    _verify(row)
    decision = (
        next(iter(row._review_decisions), None)
        if hasattr(row, "_review_decisions")
        else EvaluationDecision.objects.filter(revision=row).first()
    )
    return {
        "id": str(row.pk),
        "number": row.number,
        "corpus": row.corpus,
        "judgements": row.judgements,
        "corpus_sha256": row.corpus_sha256,
        "judgements_sha256": row.judgements_sha256,
        "ranker_version": row.ranker_version,
        "note": row.note,
        "author": row.subject_id,
        "created_at": row.created_at,
        "state": decision.action if decision else "PENDING",
        "decision": None
        if decision is None
        else {
            "action": decision.action,
            "reviews": decision.reviews,
            "note": decision.note,
            "reviewer": decision.subject_id,
            "created_at": decision.created_at,
        },
    }


@mutation_service
def propose(
    *, case_id, subject_id, provider, expected_number, bundle, note, synthetic_fixtures_only=False
):
    _text(note)
    corpus, judgements = validate_bundle(bundle)
    if type(expected_number) is not int or not 0 <= expected_number < 64:
        raise cases.CaseConflict("evaluation_version_invalid")
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor):
        _permit(case, actor, provider, "PROPOSE")
        previous = _current(case)
        if (previous.number if previous else 0) != expected_number:
            raise cases.CaseConflict("evaluation_revision_changed")
        row = EvaluationRevision.objects.create(
            case=case,
            number=expected_number + 1,
            corpus=corpus,
            judgements=judgements,
            corpus_sha256=workspace._digest(corpus),
            judgements_sha256=workspace._digest(judgements),
            ranker_version=ranker_identity(),
            note=note,
            subject_id=actor.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=actor.auth_epoch,
        )
        result = _data(row)
        workspace._recheck(case, actor, provider)
        _permit(case, actor, provider, "PROPOSE")
        # The authority callback may revoke the actor while returning its old grant.
        workspace._recheck(case, actor, provider)
        return result


@mutation_service
def decide(
    *,
    case_id,
    subject_id,
    provider,
    revision_id,
    corpus_sha256,
    judgements_sha256,
    action,
    confirmed,
    reviews,
    note,
    synthetic_fixtures_only=False,
):
    _text(note)
    if action not in {"APPROVE", "REJECT"} or confirmed is not True:
        raise cases.CaseConflict("evaluation_explicit_review_required")
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor):
        _permit(case, actor, provider, action)
        row = EvaluationRevision.objects.filter(
            case=case, engine="TITLE_WORDS", pk=cases._uuid(revision_id)
        ).first()
        if (
            row is None
            or _current(case).pk != row.pk
            or EvaluationDecision.objects.filter(revision=row).exists()
        ):
            raise cases.CaseConflict("evaluation_revision_changed")
        _verify(row)
        if (
            row.corpus_sha256 != corpus_sha256
            or row.judgements_sha256 != judgements_sha256
            or row.ranker_version != ranker_identity()
        ):
            raise cases.CaseConflict("evaluation_digest_changed")
        if (row.provider_id, row.subject_id) == (provider.provider_id, actor.subject_id):
            raise cases.CaseConflict("independent_evaluation_reviewer_required")
        try:
            ids = {q["id"] for q in row.judgements}
            if (
                type(reviews) is not list
                or len(reviews) != len(ids)
                or {r["id"] for r in reviews} != ids
            ):
                raise ValueError()
            for r in reviews:
                if set(r) != {"id", "verdict", "note"} or r["verdict"] not in {"AGREE", "DISAGREE"}:
                    raise ValueError()
                _text(r["note"])
            if action == "APPROVE" and any(r["verdict"] != "AGREE" for r in reviews):
                raise ValueError()
        except (ValueError, TypeError, KeyError) as exc:
            raise cases.CaseConflict("evaluation_judgements_required") from exc
        EvaluationDecision.objects.create(
            revision=row,
            action=action,
            reviews=reviews,
            note=note,
            subject_id=actor.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=actor.auth_epoch,
        )
        result = _data(row)
        workspace._recheck(case, actor, provider)
        _permit(case, actor, provider, action)
        workspace._recheck(case, actor, provider)
        return result


@mutation_service
def history(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor):
        _permit(case, actor, provider, "VIEW")
        rows = list(
            EvaluationRevision.objects.filter(case=case, engine="TITLE_WORDS").order_by("-number")
        )
        decisions = {r.revision_id: r for r in EvaluationDecision.objects.filter(revision__in=rows)}
        for r in rows:
            r._review_decisions = [decisions[r.pk]] if r.pk in decisions else []
        result = {
            "case_ref": case.public_ref,
            "versions": [_data(r) for r in rows],
            "current_number": rows[0].number if rows else 0,
            "synthetic_only": True,
        }
        workspace._recheck(case, actor, provider)
        _permit(case, actor, provider, "VIEW")
        workspace._recheck(case, actor, provider)
        return result
