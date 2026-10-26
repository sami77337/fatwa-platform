"""Adapt the existing FAST6 composed verifier into actionable evidence requirements.

Only fixed development fixtures are executed. Owner documents cannot be supplied
to this adapter. A successful replay never constitutes owner or policy acceptance.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256

from apps.editorial_export.services import HOLDS, encode_json, require_development

SCHEMA = "fatwa.fast8-acceptance-evidence.v1"
REVIEWED_BASE = "92fa517ecdefe3f1a92a1ab145ff55943474df44"
MAX_REPORT_BYTES = 1_000_000
MAX_ROWS = 40
STATUSES = ("PASS", "FAIL", "BLOCKED", "NOT_RUN", "NOT_SUPPLIED", "NOT_CONNECTED")
PRODUCER = "apps.fast6_journey.integration.run_integration"
CONNECTIONS = {
    "transcript_to_stock_queue": "NOT_CONNECTED",
    "prepared_to_rehearsal": "CONNECTED",
    "rehearsal_to_export": "CONNECTED",
    "permission_to_case": "NOT_CONNECTED",
    "transcript_to_prepared": "CONNECTED",
    "queue_to_triage_packet_export": "CONNECTED",
    "original_to_rehearsal": "CONNECTED",
}
EXPECTED_COVERAGE = {
    "historical_actions": {"expected": 70, "supplied": 0},
    "historical_transitions": {"expected": 58, "supplied": 0},
    "U03": {"expected": 48, "supplied": 0, "approved": 0},
    "U10": {"expected": 28, "supplied": 0, "approved": 0},
}
# Metadata expectations from AGENTS.md only. No archive is opened or reconstructed.
ARCHIVES = (
    (
        "FATWA_BUILD_SPRINT_01_R2_20261011.zip",
        "2b50ef138d2890156121e784618715e9992e04bed7d437bbf13e5d6250d0e78b",
    ),
    (
        "FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip",
        "82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce",
    ),
)


class EvidenceError(ValueError):
    """Evidence cannot establish the bounded contract."""


@dataclass(frozen=True, slots=True)
class EvidenceReport:
    json_bytes: bytes

    def payload(self) -> dict:
        return json.loads(self.json_bytes)

    @property
    def sha256(self) -> str:
        return sha256(self.json_bytes).hexdigest()


def _require(condition: bool) -> None:
    if not condition:
        raise EvidenceError("upstream_contract_mismatch")


def _collect() -> bytes:
    # This composed service already reuses source_readiness, policy_gap_engine,
    # workflow_invariants and the FAST6 journey's exact identity checks.
    from apps.fast6_journey.integration import run_integration

    return run_integration(synthetic_fixtures_only=True).json_bytes


def _validate(raw: bytes) -> dict:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_REPORT_BYTES)
    data = json.loads(raw)
    # Reject duplicate keys, alternate encodings, NaN and unbounded structures by
    # comparing to the existing bounded canonical encoder, before using statuses.
    _require(encode_json(data) == raw)
    _require(data["schema"] == "fatwa.fast6-integration.v1")
    _require(data["synthetic_only"] is True and data["result"] == "PASS_WITH_GAPS")
    _require(data["holds"] == list(HOLDS))
    execution = data["execution"]
    _require(execution["services"] == "PASS")
    _require(execution["writes"] is False and execution["network_requests"] is False)
    for key in ("http", "browser", "postgres", "owner_archives"):
        _require(execution[key] == "NOT_RUN")
    _require(execution["catalog"] == "fixed_synthetic_snapshot")
    edges = data["connections"]
    _require(len(edges) == len(CONNECTIONS))
    _require({edge["id"]: edge["status"] for edge in edges} == CONNECTIONS)

    policy = data["permission_gaps"]
    _require(policy["report_version"] == "fatwa.policy-gap.v1")
    _require(policy["status"] == "SYNTHETIC_EVALUATED")
    _require(policy["effect"] == "DENY" and policy["allowed"] is False)
    _require(type(policy["active_grants"]) is int and policy["active_grants"] == 0)
    _require(policy["runtime_executable"] is False)
    _require(bool(policy["requests"]))
    _require(all(row["effect"] == "DENY" and row["allowed"] is False for row in policy["requests"]))
    probes = policy["adversarial_checks"]
    _require(probes["status"] == "PASS" and type(probes["failed"]) is int)
    _require(probes["failed"] == 0 and type(probes["evaluated"]) is int)
    _require(probes["evaluated"] == len(probes["checks"]) > 0)
    _require(all(check["passed"] is True for check in probes["checks"]))
    evidence = policy["evidence"]
    _require(evidence["status"] == "SYNTHETIC_ONLY")
    _require(evidence["policy_approval_verified"] is False)
    _require(evidence["source_acceptance_passed"] is False)
    _require(evidence["provenance"]["hashes_verified"] is True)
    _require(evidence["provenance"]["fixture_kind"] == "SYNTHETIC")
    for key, expected in EXPECTED_COVERAGE.items():
        # Canonical comparison also rejects bool/int equality aliases.
        _require(encode_json(evidence["coverage"][key]) == encode_json(expected))

    workflow = data["workflow_invariants"]
    _require(workflow["schema"] == "fatwa.workflow-invariants.v1.result")
    _require(workflow["invariants_passed"] is True)
    _require(workflow["synthetic_fixtures_only"] is True and bool(workflow["steps"]))
    _require(workflow["owner_transitions"] == "NOT_SUPPLIED")
    source = data["source_readiness"]
    _require(source["schema"] == "fatwa.source-readiness.report.v1")
    _require(source["status"] == "BLOCKED" and source["source_kind"] == "owner_supplied")
    _require(source["owner_acceptance"] == source["database_verification"] == "NOT_RUN")
    _require(source["observed_sha256"] == {})
    _require(source["expected_sha256"]["archive"] == ARCHIVES[1][1])
    _require(source["checks"]["manifest"]["status"] == "PASS")
    _require(
        all(
            check["status"] in STATUSES and check["status"] != "FAIL"
            for check in source["checks"].values()
        )
    )
    _require(bool(data["projections"]))
    for item in data["projections"]:
        _require(item["persisted"] is False and item["scholarly_approval"] is False)
        _require(item["packet"]["scholarly_decision"] is None)
    return data


def build_report(*, synthetic_fixtures_only: bool = False) -> EvidenceReport:
    """Return a deterministic matrix, retaining the complete upstream report.

    Missing producers/files fail closed with distinct diagnostic statuses. The
    reviewed base is context, never a claim about the running checkout or CI SHA.
    """
    require_development(synthetic_fixtures_only)
    data = None
    raw = None
    producer_status = "PASS"
    reason = "fixed_synthetic_replay_verified"
    try:
        raw = _collect()
        data = _validate(raw)
    except ImportError:
        producer_status, reason = "NOT_CONNECTED", "producer_unavailable"
    except OSError:
        producer_status, reason = "NOT_SUPPLIED", "fixed_fixture_unavailable"
    except (ValueError, TypeError, KeyError, IndexError, RecursionError):
        producer_status, reason = "FAIL", "upstream_verification_failed"

    rows = []

    def add(identifier, domain, status, requirement_ar, pointer=None, expected=None, depends=()):
        _require(status in STATUSES)
        rows.append(
            {
                "id": identifier,
                "domain": domain,
                "status": status,
                "requirement_ar": requirement_ar,
                "expected_artifact": {"id": identifier, **(expected or {})},
                "evidence": {"artifact_id": "fast6.integration", "json_pointer": pointer}
                if data is not None and pointer is not None
                else None,
                "depends_on": list(depends),
            }
        )

    add(
        "technical.synthetic_replay",
        "technical",
        producer_status,
        "إعادة تشغيل الخدمات على السجلات الاصطناعية الثابتة فقط.",
        "",
        {"producer": PRODUCER, "reason": reason},
    )
    for name, pointer in (
        ("policy_negatives", "/permission_gaps/adversarial_checks"),
        ("workflow_invariants", "/workflow_invariants"),
    ):
        add(
            f"technical.{name}",
            "technical",
            "PASS" if data is not None else producer_status,
            "توفير تقرير تحقق اصطناعي سليم؛ نجاحه لا يمنح صلاحيات أو اعتمادًا.",
            pointer,
        )
    add(
        "source.preflight",
        "source",
        "BLOCKED" if data is not None else producer_status,
        "استكمال إثبات المصدر في بيئة المالك المعزولة؛ بصمات التوقع ليست دليل فحص.",
        "/source_readiness",
        depends=("owner.archive.2",),
    )
    for key in ("http", "browser", "postgres"):
        add(
            f"technical.{key}",
            "technical",
            "NOT_RUN",
            "توفير نتيجة تشغيل مستقلة مرتبطة ببصمة الالتزام والمدخلات؛ لم ينفذها هذا المجمع.",
            f"/execution/{key}",
        )
    for name in ("B6", "C6", "D6"):
        add(
            f"ci.{name}",
            "technical_ci",
            "NOT_RUN",
            "إرفاق نتيجة CI الفعلية مع SHA الالتزام ومعرف التشغيل والمهام؛ لا اتصال بالشبكة هنا.",
            expected={"workflow": name, "execution_sha": None, "run_id": None},
        )
    for index, (name, digest) in enumerate(ARCHIVES, 1):
        add(
            f"owner.archive.{index}",
            "owner",
            "NOT_SUPPLIED",
            "يتولى المالك التحقق من الأرشيف الأصلي خارج المستودع العام؛ لا تقبل نسخة اصطناعية بديلًا.",
            expected={
                "name": name,
                "sha256": digest,
                "hash_kind": "expected_only",
                "observed_sha256": None,
                "basis": "AGENTS.md",
            },
        )
    for key, expected in EXPECTED_COVERAGE.items():
        acceptance = key in ("U03", "U10")
        add(
            f"owner.{key}",
            "owner",
            "NOT_SUPPLIED",
            "توفير بنود السياسة الأصلية وقبول المالك الموثق؛ لا استنتاج للموافقة من الاختبارات."
            if acceptance
            else "توفير السجلات التاريخية الأصلية المراجعة مع هويتها وبصمتها؛ العدد المتوقع وحده لا يثبت التغطية.",
            f"/permission_gaps/evidence/coverage/{key}",
            {**expected, "approval": "OWNER_APPROVAL_PENDING"} if acceptance else expected,
        )
    for key in CONNECTIONS:
        status = CONNECTIONS[key] if data is not None else "NOT_CONNECTED"
        # Only unresolved connections are requirements; successful bridges remain
        # available with complete original identities in the upstream artifact.
        if status != "CONNECTED":
            index = (
                next((i for i, edge in enumerate(data["connections"]) if edge["id"] == key), None)
                if data
                else None
            )
            add(
                f"connection.{key}",
                "integration",
                "NOT_CONNECTED",
                "توفير محول موثق يطابق الهوية الكاملة ويحفظ دليل الطرفين؛ لا يكفي تشابه المعرفات.",
                f"/connections/{index}" if index is not None else None,
            )
    add(
        "acceptance.policy",
        "owner",
        "BLOCKED",
        "قبول المالك المستقل مطلوب؛ جميع الصلاحيات تبقى مرفوضة افتراضيًا.",
        depends=tuple(f"owner.{key}" for key in EXPECTED_COVERAGE),
    )
    add(
        "acceptance.scholarly",
        "scholarly",
        "BLOCKED",
        "المراجعة العلمية خارج نطاق هذا النموذج؛ النجاح التقني لا يثبت صحة علمية.",
        depends=("acceptance.policy", "owner.archive.2"),
    )
    add(
        "acceptance.production",
        "production",
        "BLOCKED",
        "القبول الإنتاجي والبوابات الرسمية خارج صلاحية المجمع؛ لا نشر ولا تغيير سياسة.",
        depends=("acceptance.policy", "acceptance.scholarly", "ci.B6", "ci.C6", "ci.D6"),
    )
    _require(len(rows) <= MAX_ROWS and len({row["id"] for row in rows}) == len(rows))
    result = {
        "schema": SCHEMA,
        "status": "FAIL" if producer_status == "FAIL" else "BLOCKED",
        "scope": "OFFLINE_SYNTHETIC_READINESS_ONLY",
        "reviewed_base_sha": REVIEWED_BASE,
        "execution_commit": {"status": "NOT_SUPPLIED", "sha": None},
        "artifact_id_namespace": "FAST8_LOCAL_REQUIREMENTS_NOT_OWNER_ISSUED_IDENTIFIERS",
        "holds": list(HOLDS) + ["U03/U10 OWNER_APPROVAL_PENDING"],
        "authorization": {"allowed": False, "active_grants": 0, "policy_changed": False},
        "acceptance": {"owner": "BLOCKED", "scholarly": "BLOCKED", "production": "BLOCKED"},
        "producer": {"name": PRODUCER, "status": producer_status, "reason": reason},
        "artifacts": [
            {
                "id": "fast6.integration",
                "producer": PRODUCER,
                "sha256": sha256(raw).hexdigest(),
                "bytes": len(raw),
                "hash_kind": "exact_upstream_utf8_bytes",
                "encoding": "apps.editorial_export.services.encode_json",
                "payload": data,
            }
        ]
        if data is not None
        else [],
        "matrix": rows,
        "counts": {status: Counter(row["status"] for row in rows)[status] for status in STATUSES},
    }
    encoded = encode_json(result)
    _require(len(encoded) <= MAX_REPORT_BYTES)
    return EvidenceReport(encoded)


def verify_report(raw: bytes, *, synthetic_fixtures_only: bool = False) -> None:
    """Bound first, then replay exact bytes; never trust submitted acceptance flags."""
    require_development(synthetic_fixtures_only)
    if type(raw) is not bytes or len(raw) > MAX_REPORT_BYTES:
        raise EvidenceError("invalid_report_size_or_type")
    if raw != build_report(synthetic_fixtures_only=True).json_bytes:
        raise EvidenceError("evidence_replay_mismatch")
