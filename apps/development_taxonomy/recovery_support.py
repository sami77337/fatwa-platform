"""Seven nonempty tables and exact restored bindings with fresh explicit trust."""

import unittest
from contextlib import contextmanager

from django.test import override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseDecision, CaseSource
from apps.experimental_publication.tests import Directory
from apps.research_library.test_support import bind_identity_snapshot

from . import services
from .boundary import digest
from .models import (
    CaseClassification,
    Concept,
    DevelopmentTree,
    HumanReview,
    MigrationExecution,
    MigrationPlan,
    TreeVersion,
)
from .test_support import FEATURES, Authority, TaxonomyFixture

MODELS = (
    DevelopmentTree,
    Concept,
    TreeVersion,
    HumanReview,
    MigrationPlan,
    MigrationExecution,
    CaseClassification,
)
TABLES = tuple(model._meta.db_table for model in MODELS)
FUNCTIONS = ("development_taxonomy_guard()", "development_taxonomy_complete()")
TRIGGERS = (
    "dt_tree_guard",
    "dt_concept_guard",
    "dt_version_guard",
    "dt_review_guard",
    "dt_plan_guard",
    "dt_execution_guard",
    "dt_binding_guard",
    "dt_execution_complete",
)


def rows(tree_id, case_ids):
    versions = TreeVersion.objects.filter(tree_id=tree_id)
    plans = MigrationPlan.objects.filter(tree_id=tree_id)
    queries = (
        DevelopmentTree.objects.filter(pk=tree_id),
        Concept.objects.filter(tree_id=tree_id),
        versions,
        HumanReview.objects.filter(version__in=versions)
        | HumanReview.objects.filter(plan__in=plans),
        plans,
        MigrationExecution.objects.filter(plan__in=plans),
        CaseClassification.objects.filter(case_id__in=case_ids),
    )
    result = {}
    for query in queries:
        values = list(query.order_by("pk").values())
        if not values:
            raise AssertionError("taxonomy recovery table is empty")
        result[query.model._meta.db_table] = digest(values)
    return result


def original_digest(case_ids):
    return digest(
        [
            list(Case.objects.filter(pk__in=case_ids).order_by("pk").values()),
            list(CaseSource.objects.filter(case_id__in=case_ids).order_by("pk").values()),
            list(AnswerRevision.objects.filter(case_id__in=case_ids).order_by("pk").values()),
            list(CaseDecision.objects.filter(case_id__in=case_ids).order_by("pk").values()),
        ]
    )


def populate():
    class Fixture(TaxonomyFixture, unittest.TestCase):
        pass

    fixture = Fixture()
    enabled = override_settings(**FEATURES)
    enabled.enable()
    try:
        fixture.setUp()
        source = fixture.review(fixture.save())
        fixture.bind(source)
        second, second_base = fixture.new_case()
        fixture.bind(source, second_base)
        target, mapping = fixture.renamed(source)
        plan = fixture.review(fixture.plan(source, target, mapping), "PLAN")
        for kind in ("APPLY", "ROLLBACK"):
            services.execute(
                **fixture.command(),
                plan_id=plan["id"],
                kind=kind,
                reason="نقل وعكس روابط اصطناعية للاستعادة",
                confirmed=True,
            )
        receipts = [fixture.receipt, second]
        case_ids = [row["case_id"] for row in receipts]
        return {
            "cases": [{key: row[key] for key in ("case_id", "public_ref")} for row in receipts],
            "source": source,
            "target": target,
            "mapping": mapping,
            "plan": plan["id"],
            "tree": source["tree_id"],
            "tables": rows(source["tree_id"], case_ids),
            "originals": original_digest(case_ids),
        }
    finally:
        fixture.doCleanups()
        enabled.disable()


@contextmanager
def fixture_trust(receipts):
    refs = [row["public_ref"] for row in receipts]
    directory = bind_identity_snapshot(Directory(refs))
    authority = Authority(refs)
    with override_settings(
        **{
            **FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_DEVELOPMENT_TAXONOMY_AUTHORITY": authority,
        }
    ):
        yield (
            dict(
                case_id=receipts[0]["case_id"],
                subject_id="editor",
                provider=directory,
                synthetic_fixtures_only=True,
            ),
            authority,
        )


def verify_restored(pins):
    case_ids = [row["case_id"] for row in pins["cases"]]
    if (
        rows(pins["tree"], case_ids) != pins["tables"]
        or original_digest(case_ids) != pins["originals"]
    ):
        raise AssertionError("restored taxonomy history or originals changed")
    with fixture_trust(pins["cases"]) as (base, authority):
        for receipt in pins["cases"]:
            data = services.desk(**{**base, "case_id": receipt["case_id"]})
            if (
                data["binding"]["version_id"] != pins["source"]["id"]
                or data["binding"]["sequence"] != 3
                or not data["plans"][0]["rolled_back"]
            ):
                raise AssertionError("restored exact taxonomy rollback changed")
        denial_checks = {
            "missing_authority": 0,
            "missing_identity_provider": 0,
            "revoked_current_reader": 0,
            "revoked_mapping_authority": 0,
        }
        for key, change in (
            ("missing_authority", {"FATWA_DEVELOPMENT_TAXONOMY_AUTHORITY": None}),
            ("missing_identity_provider", {"FATWA_CASEWORK_IDENTITY_PROVIDER": None}),
        ):
            with override_settings(**change):
                try:
                    services.desk(**base)
                except cases.CaseConflict:
                    denial_checks[key] += 1
                else:
                    raise AssertionError("restored taxonomy inferred trust")
        authority.denied.add("READ")
        try:
            services.desk(**base)
        except cases.CaseConflict:
            denial_checks["revoked_current_reader"] += 1
        else:
            raise AssertionError("restored taxonomy ignored reader revocation")
        authority.denied.clear()
        authority.denied.add("MAP")
        try:
            services.preview(
                **base,
                source_version_id=pins["source"]["id"],
                target_version_id=pins["target"]["id"],
                mapping=pins["mapping"],
            )
        except cases.CaseConflict:
            denial_checks["revoked_mapping_authority"] += 1
        else:
            raise AssertionError("restored review became a mapping capability")
        authority.denied.clear()
        if services.desk(**base)["binding"]["version_id"] != pins["source"]["id"]:
            raise AssertionError("positive taxonomy read failed after denial")
    return {
        "status": "PASS",
        "nonempty_tables": len(TABLES),
        "denial_checks": denial_checks,
        "denied_read_count": sum(denial_checks.values()),
        "positive_reads_after_denial": True,
        "actual_binding_rollback_preserved": True,
    }
