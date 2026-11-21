"""Independent clearance floor, fresh grants and actual restored payload consumers."""

import json
import shutil
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

from django.db import DatabaseError, transaction
from django.test import override_settings

from apps.ai_gateway import recovery_support as ai_recovery
from apps.ai_gateway import services as gateway
from apps.ai_gateway.models import CandidateBatch, GatewayOutcome, GatewayRun
from apps.canonical_search import services as search
from apps.canonical_search.models import SearchDocument, SearchGeneration
from apps.canonical_search.test_support import FixtureAuthority as SearchAuthority
from apps.casework import services as cases
from apps.casework.models import (
    AnswerRevision,
    Case,
    CaseDecision,
    CaseEvent,
    CaseEvidence,
    CaseSource,
)
from apps.data_privacy import integration as privacy
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.mufti_review.identity import IdentityUnavailable
from apps.precise_citations.models import CitationAnchor, CitationReview, CitationSet
from apps.research_library.models import LibraryBlob, LibraryDecision, LibraryItem, LibraryVersion

from . import catalog, services, store
from .journal import DerivedJournal
from .models import DerivativeClear, DerivativeRebuild
from .test_support import FEATURES, Authority, Fixture

TABLES = (DerivativeClear._meta.db_table, DerivativeRebuild._meta.db_table)
FUNCTIONS = (
    "dm_clear_guard()",
    "dm_payload_delete_guard()",
    "dm_prevent_payload_revival()",
    "dm_clear_payload()",
    "dm_rebuild_guard()",
)
TRIGGERS = (
    "dm_clear_guard",
    "dm_clear_payload",
    "dm_rebuild_guard",
    "dm_candidate_delete",
    "dm_candidate_revival",
    "dm_document_revival",
)
DENIALS = (
    "feature_disabled",
    "journal_absent",
    "floor_stale",
    "floor_missing",
    "directory_absent",
    "management_mandate_revoked",
    "cleared_search_identifier",
    "cleared_ai_identifier",
    "search_permission_revoked",
    "source_read_revoked",
    "source_processing_revoked",
    "provider_absent",
    "late_projection_floor_change",
    "newer_floor_blocks_old_sql",
    "reconciled_identifier_remains_cleared",
)


def fingerprint(values):
    return catalog.text_hash(json.dumps(list(values), sort_keys=True, default=str))


def rows(pins):
    queries = (
        DerivativeClear.objects.filter(ledger_id=pins["ledger_id"]),
        DerivativeRebuild.objects.filter(clearance__ledger_id=pins["ledger_id"]),
    )
    result = {}
    for query in queries:
        values = list(query.order_by("pk").values())
        if len(values) != 2:
            raise AssertionError("Both payload owners need nonempty restored maintenance history")
        result[query.model._meta.db_table] = fingerprint(values)
    return result


def originals(pins):
    case_id = pins["case"]["case_id"]
    queries = [
        model.objects.filter(**{field: case_id})
        for model, field in (
            (Case, "pk"),
            (CaseSource, "case_id"),
            (CaseEvidence, "case_id"),
            (CaseEvent, "case_id"),
            (AnswerRevision, "case_id"),
            (CaseDecision, "case_id"),
            (CitationSet, "answer__case_id"),
            (CitationAnchor, "citation_set__answer__case_id"),
            (CitationReview, "citation_set__answer__case_id"),
            (LibraryItem, "case_id"),
            (LibraryVersion, "item__case_id"),
            (LibraryDecision, "version__item__case_id"),
        )
    ]
    queries.append(
        LibraryBlob.objects.filter(
            pk__in=LibraryVersion.objects.filter(item__case_id=case_id).values("blob_id")
        )
    )
    return {
        query.model._meta.db_table: fingerprint(query.order_by("pk").values()) for query in queries
    }


def owner_rows(pins):
    case_id = pins["case"]["case_id"]
    queries = (
        SearchGeneration.objects.filter(case_id=case_id),
        SearchDocument.objects.filter(generation__case_id=case_id),
        GatewayRun.objects.filter(case_id=case_id),
        GatewayOutcome.objects.filter(run__case_id=case_id),
        CandidateBatch.objects.filter(run__case_id=case_id),
    )
    return {
        query.model._meta.db_table: fingerprint(query.order_by("pk").values()) for query in queries
    }


def populate():
    class RecoveryFixture(Fixture, unittest.TestCase):
        pass

    fixture = RecoveryFixture()
    with override_settings(**FEATURES):
        try:
            fixture.setUp()
            # Keep real human work in the original owner tables. Neither clear
            # nor regeneration may rewrite it or manufacture a scholarly review.
            citation = fixture.save_citations()
            fixture.review_citations(citation)
            case = Case.objects.get(pk=fixture.receipt["case_id"])
            cases.record_decision(
                **fixture.common,
                answer_id=citation["answer_id"],
                expected_revision=case.revision,
                expected_evidence_version=case.evidence_version,
                action="APPROVE",
                note="اعتماد بشري اصطناعي سابق لمسح المشتقات",
            )
            original_document = str(
                SearchDocument.objects.filter(generation_id=fixture.built["generation_id"])
                .order_by("ordinal")
                .first()
                .pk
            )
            fixture.change()
            rebuilt_search = fixture.change("REBUILD")
            fixture.change(kind="AI_CANDIDATES")
            rebuilt_ai = fixture.change("REBUILD", "AI_CANDIDATES")
            root = (
                Path(".local/qa/functional-continuation/derived-maintenance-floor")
                / fixture.journal.ledger_id
            )
            root.mkdir(parents=True, mode=0o700, exist_ok=False)
            root = root.resolve()
            for name in ("decisions.json", "lock"):
                shutil.copyfile(fixture.journal.root / name, root / name)
                (root / name).chmod(0o600)
            pins = dict(
                ledger_id=fixture.journal.ledger_id,
                journal_root=str(root),
                floor=catalog.digest(fixture.journal.snapshot()),
                case={name: fixture.receipt[name] for name in ("case_id", "public_ref")},
                material={name: fixture.material[name] for name in ("version_id", "digest")},
                old_generation=fixture.built["generation_id"],
                old_document=original_document,
                old_run=fixture.run["id"],
                generation=rebuilt_search["child_id"],
                run_id=rebuilt_ai["child_id"],
                source_sha256=catalog.text_hash(fixture.source_text),
                question_sha256=case.source.question_sha256,
            )
            pins["tables"], pins["originals"], pins["owners"] = (
                rows(pins),
                originals(pins),
                owner_rows(pins),
            )
            return pins
        finally:
            fixture.doCleanups()


@contextmanager
def current_floor(pins):
    """Supply only the independent floor, never identities or permission grants.

    Populate after existing search/AI components and before record suppression.
    Wrap every subsequent search/AI reader and restored verifier with this scope;
    compose the separate suppression current_floor around the same consumers.
    """
    journal = DerivedJournal(root=pins["journal_root"], ledger_id=pins["ledger_id"])
    current = journal.snapshot()
    if catalog.digest(current) != pins["floor"]:
        raise catalog.DerivedDenied("derived_restore_floor_changed")
    with override_settings(
        FATWA_DERIVED_MAINTENANCE_ENABLED=True, FATWA_DERIVED_MAINTENANCE_JOURNAL=journal
    ):
        expected = store.configuration()
        yield journal
        if store.configuration() != expected or journal.snapshot() != current:
            raise catalog.DerivedDenied("derived_restore_floor_changed")


@contextmanager
def fresh_trust(pins):
    with ai_recovery.fixture_trust(pins) as (base, source, gateway_authority):
        search_authority = SearchAuthority(pins["case"]["public_ref"])
        authority = Authority(
            base["provider"],
            (
                ("SEARCH_INDEX", pins["old_generation"]),
                ("SEARCH_INDEX", pins["generation"]),
                ("AI_CANDIDATES", pins["old_run"]),
                ("AI_CANDIDATES", pins["run_id"]),
            ),
        )
        with (
            override_settings(
                FATWA_CANONICAL_SEARCH_ENABLED=True,
                FATWA_CANONICAL_SEARCH_AUTHORITY=search_authority,
                FATWA_DERIVED_MAINTENANCE_AUTHORITY=authority,
            ),
            current_floor(pins) as journal,
        ):
            yield base, authority, search_authority, source, gateway_authority, journal


def verify_restored(pins):
    def unchanged():
        if (
            rows(pins) != pins["tables"]
            or originals(pins) != pins["originals"]
            or owner_rows(pins) != pins["owners"]
        ):
            raise AssertionError("Restored derivative history or human originals changed")

    unchanged()
    denials = dict.fromkeys(DENIALS, 0)
    with fresh_trust(pins) as (base, authority, search_authority, source, ai_authority, journal):
        management = {key: value for key, value in base.items() if key != "case_id"}

        def search_read():
            return search.search(**base, value="اصطناعي", mode="FTS")

        def ai_read(identifier=None):
            with gateway.read_boundary(**base, run_id=identifier or pins["run_id"]) as value:
                return value

        def positive(generation=None):
            found = search_read()
            if found["total"] < 1:
                raise AssertionError("Restored current text search is empty")
            selected = found["results"][0]
            if selected["generation_id"] != (generation or pins["generation"]):
                raise AssertionError("Restored search revived a cleared generation")
            opened = search.open_source(
                **base,
                generation_id=selected["generation_id"],
                document_id=selected["document_id"],
            )
            if catalog.text_hash(opened["text"]) != pins["question_sha256"]:
                raise AssertionError("Current source question changed")
            result = ai_read()
            if result["status"] != "SUCCEEDED" or result["provider_mode"] != "SYNTHETIC":
                raise AssertionError("Restored regenerated candidate status changed")
            entry = result["candidates"][0]
            if (
                catalog.text_hash(entry["before"] + entry["selected"] + entry["after"])
                != pins["source_sha256"]
            ):
                raise AssertionError("Current original citation source changed")

        def deny(name, call):
            try:
                call()
            except (cases.CaseConflict, IdentityUnavailable):
                denials[name] += 1
            else:
                raise AssertionError("Restored derivative inferred permission: " + name)

        def audit():
            with services.inspect(
                kind="SEARCH_INDEX", identifier=pins["old_generation"], **management
            ):
                pass

        positive()
        for name, setting, value in (
            ("feature_disabled", "FATWA_DERIVED_MAINTENANCE_ENABLED", False),
            ("journal_absent", "FATWA_DERIVED_MAINTENANCE_JOURNAL", None),
            ("directory_absent", "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
        ):
            with override_settings(**{setting: value}):
                deny(name, audit if name == "directory_absent" else search_read)
        authority.denied.add(("editor", "ENTER"))
        deny("management_mandate_revoked", audit)
        authority.denied.clear()
        deny(
            "cleared_search_identifier",
            lambda: search.open_source(
                **base,
                generation_id=pins["old_generation"],
                document_id=pins["old_document"],
            ),
        )
        deny("cleared_ai_identifier", lambda: ai_read(pins["old_run"]))
        search_authority.denied.add("SEARCH")
        deny("search_permission_revoked", search_read)
        search_authority.denied.clear()
        source.denied.add("READ")
        deny("source_read_revoked", ai_read)
        source.denied.clear()
        ai_authority.denied.add(("PROCESS_CONTEXT", "LIBRARY"))
        deny("source_processing_revoked", ai_read)
        ai_authority.denied.clear()
        with override_settings(FATWA_AI_CITATION_PROVIDER=None):
            deny("provider_absent", ai_read)
        with tempfile.TemporaryDirectory(prefix="derived-restore-denials-") as temporary:
            scratch = DerivedJournal(root=temporary, ledger_id=journal.ledger_id)
            scratch.initialize()
            with override_settings(FATWA_DERIVED_MAINTENANCE_JOURNAL=scratch):
                deny("floor_stale", search_read)
                (scratch.root / "decisions.json").unlink()
                deny("floor_missing", search_read)

            def late():
                with privacy.projection():
                    search_read()
                    with override_settings(FATWA_DERIVED_MAINTENANCE_JOURNAL=scratch):
                        from apps.data_privacy.services import SCOPES

                        SCOPES.get()[-1].final_pins()

            deny("late_projection_floor_change", late)

        # Simulate a genuinely older SQL state, retaining the newer external
        # floor. Isolate this destructive derivative-only drill and roll back
        # every database change before returning to the captured checkpoint.
        with tempfile.TemporaryDirectory(prefix="derived-newer-floor-") as temporary:
            newer = DerivedJournal(root=temporary, ledger_id=journal.ledger_id)
            newer.initialize()
            expected = []
            for value in journal.snapshot():
                expected = newer.append(expected, value)

            def change(action):
                if action == "RECONCILE":
                    proposal = dict(
                        kind="",
                        identifier="",
                        header_digest="",
                        payload_digest="",
                        clearance="",
                        watermark=store.snapshot(allow_pending=True).watermark,
                    )
                else:
                    with services.inspect(
                        kind="SEARCH_INDEX", identifier=pins["generation"], **management
                    ) as current:
                        resource = current["item"]
                        proposal = dict(
                            kind="SEARCH_INDEX",
                            identifier=resource["id"],
                            **{
                                key: resource[key]
                                for key in ("header_digest", "payload_digest", "clearance")
                            },
                            watermark=current["watermark"],
                        )
                proposal.update(
                    action=action,
                    reason="مصالحة مشتق ممسوح بعد النسخة المستعادة",
                    request_key=str(uuid.uuid4()),
                    parameters={},
                )
                with services.preview(proposal=proposal, **management) as plan:
                    pass
                with services.apply(plan=plan, confirmed=True, **management) as result:
                    return result

            selected = search_read()["results"][0]
            with (
                override_settings(FATWA_DERIVED_MAINTENANCE_JOURNAL=newer),
                synthetic_queue_atomic(),
                transaction.atomic(),
            ):

                class OlderSQL(Exception):
                    pass

                try:
                    with transaction.atomic():
                        change("CLEAR")
                        raise OlderSQL
                except OlderSQL:
                    pass
                if (
                    DerivativeClear.objects.filter(ledger_id=pins["ledger_id"]).count() != 2
                    or len(newer.snapshot()) != 3
                    or not SearchDocument.objects.filter(generation_id=pins["generation"]).exists()
                ):
                    raise AssertionError("Newer clearance did not survive older SQL restoration")
                deny("newer_floor_blocks_old_sql", search_read)
                change("RECONCILE")
                if not DerivativeClear.objects.get(sequence=3).recovered:
                    raise AssertionError("Missing current clearance was not reapplied with audit")
                deny(
                    "reconciled_identifier_remains_cleared",
                    lambda: search.open_source(
                        **base,
                        generation_id=selected["generation_id"],
                        document_id=selected["document_id"],
                    ),
                )
                positive(change("REBUILD")["child_id"])
                transaction.set_rollback(True)
        for model in (DerivativeClear, DerivativeRebuild):
            try:
                with synthetic_queue_atomic(), transaction.atomic():
                    model.objects.update(reason="تعديل تاريخ مستعاد")
            except DatabaseError:
                pass
            else:
                raise AssertionError("Restored maintenance audit accepted mutation")
        positive()  # Actual source and derivative readers after every named denial.
    unchanged()
    return dict(
        status="PASS",
        nonempty_tables=2,
        denial_checks=denials,
        denied_read_count=sum(denials.values()),
        positive_reads_after_denial=True,
        human_edits_and_approval_preserved=True,
        original_bytes_preserved=True,
        independent_current_floor_required=True,
        newer_floor_reapplied_before_availability=True,
        cleared_identifiers_not_reactivated=True,
        immutable_audit=True,
        implemented_payload_owners=["SearchDocument", "CandidateBatch"],
        semantic_search="NOT_IMPLEMENTED",
        real_provider_quality="NOT_EVALUATED",
    )
