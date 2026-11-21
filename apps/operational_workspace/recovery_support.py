"""Real failed/pending source states; restored records never restore operational grants."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta

from django.db import connection
from django.test import override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.delivery_queue.models import DeliveryAuditHead

from . import services
from .boundary import digest, source_rows
from .test_support import FEATURES, Authority, Directory, Profiles, seed

TABLES = ()
FUNCTIONS = ()
TRIGGERS = ()


def row_pins(receipts):
    return {
        table: digest(values)
        for table, values in source_rows([row["case_id"] for row in receipts.values()]).items()
    }


@contextmanager
def current_trust(receipts):
    directory = Directory([row["public_ref"] for key, row in receipts.items() if key != "unscoped"])
    authority, profiles = Authority(receipts), Profiles()
    with override_settings(
        **{
            **FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_OPERATIONAL_WORKSPACE_AUTHORITY": authority,
            "FATWA_COMPOSITE_DELIVERY_CAPABILITIES": profiles,
        }
    ):
        yield (
            dict(subject_id="operator", provider=directory, synthetic_fixtures_only=True),
            authority,
        )


def projection(receipts, common):
    with services.queue_projection(**common) as result:
        counts = result["counts"]
        assert result["role"] == "ORGANIZER"
        refs = sorted(row["public_ref"] for row in result["rows"])
        assert receipts["hidden"]["public_ref"] not in refs
        assert receipts["unscoped"]["public_ref"] not in refs
    details = {}
    for section in services.SECTION_ACTIONS:
        with services.detail_projection(
            **common, case_ref=receipts[section]["public_ref"], section=section
        ) as result:
            assert result["role"] == "ORGANIZER" and result["section"]["pending"]
            details[section] = digest(result["section"])
    assert counts == {
        "all": 5,
        "metadata": 5,
        "delivery": 1,
        "publication": 1,
        "transcript": 1,
        "capability": 3,
    }
    return {"counts": counts, "case_refs": refs, "detail_digests": details}


def populate():
    with override_settings(**FEATURES):
        receipts = seed()
        with current_trust(receipts) as (common, _authority):
            expected = projection(receipts, common)
        return {"cases": receipts, "tables": row_pins(receipts), "expected": expected}


def verify_restored(pins):
    connection.close()
    receipts = pins["cases"]
    before = row_pins(receipts)
    audit_before = digest(list(DeliveryAuditHead.objects.order_by("pk").values()))
    assert before == pins["tables"]
    denied = {}
    with current_trust(receipts) as (common, authority):
        assert projection(receipts, common) == pins["expected"]

        def refusal(kind, section="metadata"):
            try:
                with services.detail_projection(
                    **common, case_ref=receipts[section]["public_ref"], section=section
                ):
                    pass
            except cases.CaseConflict:
                denied[kind] = denied.get(kind, 0) + 1
            else:
                raise AssertionError("restored queue inferred a current operational grant")

        for key, name, value in (
            ("disabled_workspace", "FATWA_OPERATIONAL_WORKSPACE_ENABLED", False),
            ("missing_authority", "FATWA_OPERATIONAL_WORKSPACE_AUTHORITY", None),
            ("missing_identity_provider", "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
        ):
            with override_settings(**{name: value}):
                refusal(key)
        directory = common["provider"]
        original = directory.identities["operator"]
        directory.identities["operator"] = replace(original, active=False)
        refusal("revoked_current_identity")
        directory.identities["operator"] = original
        grants = set(authority.grants)
        authority.revoke(action="READ_CASE", case_ref=receipts["metadata"]["public_ref"])
        refusal("revoked_case_read")
        authority.grants = set(grants)
        authority.revoke(action="READ_TRANSCRIPT")
        refusal("revoked_transcript_read", "transcript")
        authority.grants = set(grants)
        until = authority.until
        authority.until = timezone.now() - timedelta(seconds=1)
        refusal("expired_operational_grant")
        authority.until = until
        assert projection(receipts, common) == pins["expected"]
    assert row_pins(receipts) == before == pins["tables"]
    assert digest(list(DeliveryAuditHead.objects.order_by("pk").values())) == audit_before
    return {
        "status": "PASS",
        "new_table_count": 0,
        "actual_operational_role": "ORGANIZER",
        "case_count": 7,
        "visible_cases": 5,
        "real_failed_delivery_parts": 1,
        "real_pending_transcript_review": True,
        "all_five_queue_lanes": True,
        "denial_checks": denied,
        "denied_read_count": sum(denied.values()),
        "positive_reads_after_denial": True,
        "canonical_source_and_delivery_history_unchanged": True,
        "restored_rows_are_not_current_grants": True,
    }
