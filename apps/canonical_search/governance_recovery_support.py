"""Nonempty real governance records; fresh current trust and no restoration writes."""

import uuid
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256

from django.test import override_settings

from apps.casework import services as cases
from apps.casework.models import Case, CaseSource
from apps.mufti_review.identity import IdentityUnavailable

from . import governance, recovery_support, services
from .governance_pins import MODELS
from .governance_test_support import ENTRIES, TERM, GovernanceAuthority
from .models import ShadowComparison, SynonymDecision, SynonymRevision

TABLES = tuple(model._meta.db_table for model in MODELS)
FUNCTIONS = (
    "cs_governance_result_valid",
    "cs_governance_difference",
    "cs_governance_insert",
)
TRIGGERS = (
    "cs_synonym_insert",
    "cs_synonym_immutable",
    "cs_preview_insert",
    "cs_preview_immutable",
    "cs_decision_insert",
    "cs_decision_immutable",
    "cs_shadow_insert",
    "cs_shadow_immutable",
)


@contextmanager
def configuration(pins):
    with recovery_support.configuration(pins) as base:
        with override_settings(
            FATWA_SEARCH_GOVERNANCE_ENABLED=True,
            FATWA_CANONICAL_SEARCH_AUTHORITY=GovernanceAuthority(pins["public_ref"]),
        ):
            yield base


def _history(case_id):
    return {
        model._meta.db_table: [
            [str(row.pk), row.digest]
            for row in model.objects.filter(case_id=case_id).order_by("pk")
        ]
        for model in MODELS
    }


def populate():
    key = "search-governance-recovery-" + uuid.uuid4().hex
    receipt = cases.intake_case(
        original_question="سُؤال اصطناعي عن المُعاملات المالية لاستعادة القاموس والمقارنة",
        source_event_id=key,
        requester_id=key,
        idempotency_key=key,
        synthetic_fixtures_only=True,
    )
    pins = {name: str(receipt[name]) for name in ("case_id", "public_ref")}
    with configuration(pins) as base:
        case = Case.objects.get(pk=pins["case_id"])
        versions = dict(
            expected_revision=case.revision, expected_evidence_version=case.evidence_version
        )
        services.rebuild(**base, **versions, expected_generation=0, request_key=uuid.uuid4())
        revision = governance.create_revision(
            **base,
            **versions,
            expected_number=0,
            request_key=uuid.uuid4(),
            title="قاموس استعادة اصطناعي",
            provenance="ألفاظ مصنوعة لاختبار الاستعادة فقط",
            entries=ENTRIES,
            mapping=[],
        )
        preview = governance.prepare_preview(
            **base,
            **versions,
            revision_id=revision["id"],
            queries=[TERM, "المعاملات"],
            request_key=uuid.uuid4(),
        )
        reviewed = governance.decide(
            **{**base, "subject_id": "publisher"},
            **versions,
            revision_id=revision["id"],
            preview_id=preview["id"],
            action="APPROVE",
            note="مراجعة مستقلة للبيانات الاصطناعية",
            ttl_minutes=1440,
            expected_sequence=0,
            confirmed=True,
            request_key=uuid.uuid4(),
        )
        observation = governance.run_shadow(
            **base,
            **versions,
            revision_id=revision["id"],
            value=TERM,
            request_key=uuid.uuid4(),
        )
        newer = governance.create_revision(
            **base,
            **versions,
            expected_number=1,
            request_key=uuid.uuid4(),
            title="نسخة لاحقة غير معتمدة",
            provenance="ربط صريح لا يغير النسخة المراجعة",
            entries=[
                {"key": "new-synthetic", "term": "مصطنعللاستعادة", "alternatives": ["المعاملات"]}
            ],
            mapping=[
                {
                    "from": ENTRIES[0]["key"],
                    "kind": "RENAMED",
                    "to": ["new-synthetic"],
                    "reason": "تسمية اصطناعية جديدة مع حفظ السابق",
                }
            ],
        )
        source = CaseSource.objects.get(case_id=pins["case_id"])
        pins.update(
            dictionary_id=revision["id"],
            dictionary_digest=revision["digest"],
            newer_dictionary_id=newer["id"],
            preview_id=preview["id"],
            comparison_id=observation["comparison"]["id"],
            comparison_digest=observation["comparison"]["digest"],
            reviewer=reviewed["reviewer"],
            original_question_sha256=sha256(source.original_question.encode()).hexdigest(),
            governance_history=_history(pins["case_id"]),
        )
    return pins


def verify_restored(pins):
    denials, counts = {}, {}
    initial = _history(pins["case_id"])
    assert initial == pins["governance_history"]
    for model in MODELS:
        for row in model.objects.filter(case_id=pins["case_id"]):
            services._verify(row)
    with configuration(pins) as base:

        def search():
            return governance.search(**base, revision_id=pins["dictionary_id"], value=TERM)

        def comparison():
            return governance.read_shadow(**base, comparison_id=pins["comparison_id"])

        def denied(name):
            count = 0
            for read in (search, comparison):
                try:
                    read()
                except (cases.CaseConflict, IdentityUnavailable):
                    count += 1
                else:
                    raise AssertionError(f"Restored governed search ignored {name}")
            denials[name], counts[name] = True, count

        result, observed = search(), comparison()
        assert result["total"] == 1
        assert result["dictionary"]["digest"] == pins["dictionary_digest"]
        assert result["dictionary"]["reviewer"] == pins["reviewer"]
        assert observed["digest"] == pins["comparison_digest"]
        assert observed["baseline"]["total"] == 0 and observed["candidate"]["total"] == 1
        assert observed["baseline_retained"] is True and observed["promotion_performed"] is False
        assert services.search(**base, value=TERM, mode="FTS")["total"] == 0
        assert services.search(**base, value=TERM, mode="LITERAL")["total"] == 0
        current = result["results"][0]
        opened = services.open_source(
            **base, generation_id=current["generation_id"], document_id=current["document_id"]
        )
        assert sha256(opened["text"].encode()).hexdigest() == pins["original_question_sha256"]
        assert SynonymRevision.objects.get(pk=pins["newer_dictionary_id"]).previous_id == uuid.UUID(
            pins["dictionary_id"]
        )
        assert not SynonymDecision.objects.filter(revision_id=pins["newer_dictionary_id"]).exists()
        with override_settings(FATWA_CANONICAL_SEARCH_AUTHORITY=None):
            denied("missing_authority")
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=None):
            denied("missing_identity_provider")
        with override_settings(FATWA_SEARCH_GOVERNANCE_ENABLED=False):
            denied("disabled_feature")
        directory = base["provider"]
        editor = directory.identities["editor"]
        directory.identities["editor"] = replace(editor, active=False)
        try:
            denied("revoked_current_reader")
        finally:
            directory.identities["editor"] = editor
        assert search()["total"] == 1
        assert comparison()["digest"] == pins["comparison_digest"]
    assert _history(pins["case_id"]) == initial
    assert (
        ShadowComparison.objects.get(pk=pins["comparison_id"]).digest == pins["comparison_digest"]
    )
    return {
        "tables": TABLES,
        "verified_dictionary_versions": 2,
        "actual_fts_expansion_after_restore": True,
        "literal_and_baseline_unchanged": True,
        "exact_shadow_source_pins": True,
        "baseline_retained": True,
        "promotion_performed": False,
        "dictionary_digest": pins["dictionary_digest"],
        "comparison_digest": pins["comparison_digest"],
        "denials": denials,
        "denial_checks": counts,
        "denied_read_count": sum(counts.values()),
        "positive_reads_after_denial": True,
        "governance_history_unchanged": True,
    }
