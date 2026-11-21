"""Fresh-process original-text match navigation; restoration does not restore grants."""

import uuid
from dataclasses import replace

from django.conf import settings
from django.test import override_settings

from apps.casework import services as cases
from apps.casework.models import Case, CaseEvent
from apps.mufti_review.identity import IdentityUnavailable

from . import matches, policy, recovery_support, services, sources
from .text import digest, text_digest

# Every persistent row belongs to the existing casework and canonical-search
# recovery inventory. This projection introduces no schema or byte-object owner.
TABLES = ()
QUERY = "المعاملات"


def _snapshot(case_id):
    return digest(
        {
            "source": sources.fingerprint([case_id]),
            "index": policy.history([case_id]),
            "events": sources.frozen_rows(
                CaseEvent.objects.filter(case_id=case_id)
                .order_by("pk")
                .values_list(
                    "pk",
                    "sequence",
                    "action",
                    "stage",
                    "evidence_version",
                    "answer_revision",
                    "subject_id",
                    "note",
                    "answer_id",
                    "decision_id",
                    "created_at",
                )
            ),
        }
    )


def _open(base, selected, *, index=0):
    return matches.open_match(
        **base,
        generation_id=selected["generation_id"],
        document_id=selected["document_id"],
        value=QUERY,
        mode="FTS",
        index=index,
    )


def populate():
    key = "match-navigation-recovery-" + uuid.uuid4().hex
    question = "  المُعاملاتِ المالية\r\nسؤال اصطناعي عن المعاملات ثم المُعاملات  "
    answer = "جواب اصطناعي: المُعاملات، ثم المعاملات\r\nوموضع ثالث: المُعاملات"
    receipt = cases.intake_case(
        original_question=question,
        source_event_id=key,
        requester_id=key,
        idempotency_key=key,
        synthetic_fixtures_only=True,
    )
    pins = {name: str(receipt[name]) for name in ("case_id", "public_ref")}
    with recovery_support.configuration(pins) as base:
        case = Case.objects.get(pk=pins["case_id"])
        cases.save_answer(
            **base,
            text=answer,
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
        )
        case.refresh_from_db()
        services.rebuild(
            **base,
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
            expected_generation=0,
            request_key=uuid.uuid4(),
        )
        pins["selections"] = []
        for kind, original in (("QUESTION", question), ("ANSWER", answer)):
            found = services.search(**base, value=QUERY, mode="FTS", kind=kind)
            assert found["total"] == 1
            selected = found["results"][0]
            opened = _open(base, selected)
            assert opened["text"] == original and opened["navigation"]["count"] == 3
            pins["selections"].append(
                {
                    "kind": kind,
                    "generation_id": selected["generation_id"],
                    "document_id": selected["document_id"],
                    "text_sha256": text_digest(original),
                    "spans": opened["navigation"]["matches"],
                }
            )
        pins["source_snapshot"] = _snapshot(pins["case_id"])
    return pins


def verify_restored(pins):
    denials = {}
    with recovery_support.configuration(pins) as base:
        assert _snapshot(pins["case_id"]) == pins["source_snapshot"]

        def verify_all():
            for selected in pins["selections"]:
                for index in (0, 1, 2, 1, 0):
                    opened = _open(base, selected, index=index)
                    navigation = opened["navigation"]
                    assert text_digest(opened["text"]) == selected["text_sha256"]
                    assert navigation["matches"] == selected["spans"]
                    assert navigation["active"] == selected["spans"][index]
                    assert "".join(row["text"] for row in navigation["parts"]) == opened["text"]

        def must_deny(name, changed=None):
            try:
                _open(changed or base, pins["selections"][0])
            except (cases.CaseConflict, IdentityUnavailable):
                denials[name] = 1
            else:
                raise AssertionError(f"Restored match view accepted {name}")

        verify_all()
        with override_settings(FATWA_CANONICAL_SEARCH_ENABLED=False):
            must_deny("disabled_search")
        with override_settings(FATWA_CANONICAL_SEARCH_AUTHORITY=None):
            must_deny("missing_authority")
        must_deny("missing_identity", {**base, "provider": None})
        authority = settings.FATWA_CANONICAL_SEARCH_AUTHORITY
        for action in ("OPEN", "SEARCH"):
            authority.denied.add(action)
            try:
                must_deny("revoked_" + action.lower())
            finally:
                authority.denied.remove(action)
        provider = base["provider"]
        actor = provider.identities["editor"]
        provider.identities["editor"] = replace(actor, case_keys=frozenset())
        try:
            must_deny("revoked_case_scope")
        finally:
            provider.identities["editor"] = actor
        verify_all()
        assert _snapshot(pins["case_id"]) == pins["source_snapshot"]
    return {
        "status": "PASS",
        "new_table_count": 0,
        "exact_question_and_answer_spans": True,
        "previous_and_next_positions": True,
        "original_text_bytes_preserved": True,
        "canonical_source_and_index_unchanged": True,
        "denial_checks": denials,
        "denied_read_count": sum(denials.values()),
        "positive_reads_after_denial": True,
        "restored_rows_are_not_current_grants": True,
    }
