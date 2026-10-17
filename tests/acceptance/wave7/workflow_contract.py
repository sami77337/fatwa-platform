"""Actual E1/E2/E3 preparation outside HTTP; E5 registers real GET integration."""
from dataclasses import dataclass
from importlib.util import find_spec
import json
from urllib.parse import urlencode
from uuid import uuid4


class WorkflowIntegrationPending(RuntimeError):
    pass


EXPECTED_VERIFIED_CITATION = (
    "إحالة إلى عنوان في فهرس مرجع اصطناعي لتجارب Wave7: كِتَابٌ اصطناعي / بابٌ اصطناعي أول"
    "، ج الأول، ص 8 (عنوان فهرس، وليس نص فتوى)."
)


@dataclass(frozen=True, slots=True)
class VerifiedReferenceExpectation:
    batch_id: str
    row_id: str
    question: str
    reference_ordinal: int
    original_pointer: str
    citation_text: str
    locator: str


@dataclass(frozen=True, slots=True)
class WorkflowScenario:
    """Prepared outside HTTP by actual E1/E2/E3 services, then read by the browser.

    Values are real persisted UUIDs/GET paths/selectors/expected synthetic text.
    No arbitrary callable, source map, path, or private input comes from the UI.
    """
    worklist_path: str
    batch_ids: tuple[str, str]
    repeated_external_id: str
    detail_paths: tuple[str, str]
    original_questions: tuple[str, str]
    blocked_detail_path: str
    reviewed_detail_path: str
    missing_media_detail_path: str
    invalid_media_detail_path: str
    unresolved_detail_path: str
    review_target_id: str
    batch_keys: tuple[str, str]
    event_reasons: tuple[str, ...]
    verified_reference: VerifiedReferenceExpectation


def require_producer_services():
    for name in ("intake", "review", "references"):
        if find_spec("apps.intake_workflow." + name) is None:
            raise WorkflowIntegrationPending("ACTUAL_WAVE7_SERVICE_MISSING:" + name)


def prepare_workflow_scenario(*, require_get_registration=True) -> WorkflowScenario:
    """No outer atomic: each actual producer service owns its guarded unit.

    The explicit service-only label may omit GET registration; it never claims
    browser acceptance. Full browser always requires the actual E5 URL/flag.
    """
    require_producer_services()
    from django.conf import settings
    from django.urls import reverse, NoReverseMatch
    from apps.intake_workflow import contracts as c, fixtures as f, guards as g
    from apps.intake_workflow.intake import import_intake
    from apps.intake_workflow.review import transition_review, load_review_worklist, ReviewConflict
    from apps.intake_workflow.references import verify_batch_references
    from apps.intake_workflow.models import IntakeBatch, IntakeItem, IntakeReference, ReviewEvent
    context = g.require_synthetic_write(synthetic_fixtures_only=True)
    if context.database_name != settings.WAVE7_TEST_DATABASE_NAME:
        raise WorkflowIntegrationPending("E6_TEST_DATABASE_REQUIRED")
    path = "/dev/editorial-preview/persisted"  # actual published PR61 contract
    if require_get_registration:
        if getattr(settings, "WAVE7_REVIEW_READ_ENABLED", False) is not True:
            raise WorkflowIntegrationPending("E5_REVIEW_READ_OPT_IN_NOT_REGISTERED")
        try:
            actual = reverse("wave7_editorial_review")
        except NoReverseMatch:
            raise WorkflowIntegrationPending("E5_PERSISTED_GET_ROUTE_NOT_REGISTERED") from None
        assert actual == path, "Actual persisted route differs from published PR61"
    f.seed_reference_catalog(synthetic_fixtures_only=True)
    raw = f.synthetic_payload()
    # Controlled derived synthetic test input only; never decode/rewrite source
    # via float JSON. All received bytes are later persisted by the actual E1 API.
    needle = json.dumps(dict(external_id="W7-MISSING-MEDIA", question="سؤال اصطناعي بلا مقطع"),
                        ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert raw.count(needle) == 1, "Shared fixture shape changed; coordinate with E5"
    replacement = needle[:-1] + b',"reference_links":[{"source_id":"E6-UNMAPPED","heading_id":"E6-UNMAPPED"}]}'
    raw = raw.replace(needle, replacement, 1)
    original_token = json.dumps(f.ORIGINAL_QUESTION, ensure_ascii=False).encode("utf-8")
    alternate_question = "  سُؤَالٌ اصطناعي مستقل\t<سجل> & علامات\nفي دفعة أخرى  "
    alternate = raw.replace(original_token, json.dumps(alternate_question, ensure_ascii=False).encode("utf-8"))
    assert alternate != raw
    keys = ("E6-WORKFLOW-A", "E6-WORKFLOW-B")
    first = import_intake(raw, idempotency_key=keys[0], synthetic_fixtures_only=True)
    counts = lambda: tuple(model.objects.count() for model in (IntakeBatch, IntakeItem, IntakeReference, ReviewEvent))
    before = counts()
    replay = import_intake(raw, idempotency_key=keys[0], synthetic_fixtures_only=True)
    assert replay.batch_id == first.batch_id and replay.decision == c.IdempotencyDecision.REPLAY
    assert counts() == before, "Same-key replay duplicated persisted data"
    try:
        import_intake(alternate, idempotency_key=keys[0], synthetic_fixtures_only=True)
    except c.IdempotencyConflict as error:
        assert error.status_code == 409 and error.code == "IDEMPOTENCY_CONFLICT"
    else:
        raise AssertionError("Changed payload did not conflict")
    assert counts() == before
    second = import_intake(alternate, idempotency_key=keys[1], synthetic_fixtures_only=True)
    assert second.batch_id != first.batch_id
    for receipt in (first, second):
        verify_batch_references(receipt.batch_id, synthetic_fixtures_only=True)
        assert IntakeItem.objects.filter(batch_id=receipt.batch_id).count() == 8
    rows = tuple(IntakeItem.objects.get(batch_id=receipt.batch_id, row_ordinal=7)
                 for receipt in (first, second))
    assert rows[0].external_id == rows[1].external_id == "W7-READY-2"
    assert (rows[0].question_original, rows[1].question_original) == (f.ORIGINAL_QUESTION, alternate_question)
    reasons = tuple("E6 synthetic review " + name for name in ("start", "changes", "resume", "complete"))
    actions = ("start_review", "request_changes", "start_review", "complete_review")
    states = ("UNREVIEWED", "IN_REVIEW", "NEEDS_CHANGES", "IN_REVIEW")
    operations = tuple(uuid4() for _ in actions)
    results = []
    for action, state, operation, reason in zip(actions, states, operations, reasons, strict=True):
        results.append(transition_review(rows[0].pk, operation_id=operation, action=action,
            expected_status=state, reason=reason, synthetic_fixtures_only=True))
    repeated = transition_review(rows[0].pk, operation_id=operations[0], action=actions[0],
        expected_status=states[0], reason=reasons[0], synthetic_fixtures_only=True)
    assert repeated.replayed and repeated.event_id == results[0].event_id
    assert ReviewEvent.objects.filter(intake_item=rows[0]).count() == 4
    try:
        transition_review(rows[0].pk, operation_id=operations[0], action=actions[0],
            expected_status=states[0], reason="E6 changed reason", synthetic_fixtures_only=True)
    except ReviewConflict as error:
        assert error.code == "REVIEW_CONFLICT" and error.status_code == 409
    else:
        raise AssertionError("Conflicting review operation was accepted")
    rows[0].refresh_from_db()
    assert rows[0].review_status == "REVIEWED_INTERNAL"
    for receipt in (first, second):
        refs = IntakeReference.objects.filter(intake_item__batch_id=receipt.batch_id)
        assert refs.filter(intake_item__row_ordinal=2, reference_status="UNVERIFIED", citation_text="").exists()
        assert refs.filter(intake_item__row_ordinal=7, reference_status="VERIFIED").exclude(citation_text="").exists()
    for index, (receipt, row) in enumerate(zip((first, second), rows, strict=True)):
        stored = load_review_worklist(batch_id=receipt.batch_id, row_id=row.pk,
                                     page_size=2, synthetic_fixtures_only=True)
        assert stored.total_count == 8 and stored.row.id == row.pk
        assert stored.row.question == (f.ORIGINAL_QUESTION, alternate_question)[index]
        assert stored.row.review_status == ("REVIEWED_INTERNAL", "UNREVIEWED")[index]
        assert len(stored.row.events) == (4, 0)[index]
        # Current persisted E3 state, never historical E1 validation_results.
        assert any(ref.reference_status == "VERIFIED" and ref.citation_text for ref in stored.row.references)
    def detail(batch, row):
        return path + "?" + urlencode(dict(batch=str(batch), row=str(row), page_size=2))
    selected = {ordinal: IntakeItem.objects.get(batch_id=first.batch_id, row_ordinal=ordinal)
                for ordinal in (2, 3, 8)}
    assert selected[3].intake_status == "BLOCKED_INVALID"
    assert selected[8].original_row == "null"
    verified = IntakeReference.objects.get(intake_item=rows[0], reference_ordinal=1)
    pointer = c.parse_synthetic_payload(raw, synthetic_fixtures_only=True).reference_sources[6][0]
    assert verified.reference_status == "VERIFIED"
    assert verified.verified_identity == dict(c.VERIFIED_IDENTITIES[1])
    assert verified.original_pointer == pointer.text
    # Independent fixed-fixture expectation, not copied from a possibly wrong
    # stored/DTO citation and not obtained by calling the renderer under test.
    assert verified.citation_text == EXPECTED_VERIFIED_CITATION
    expected_reference = VerifiedReferenceExpectation(str(first.batch_id), str(rows[0].pk),
        f.ORIGINAL_QUESTION, 1, pointer.text, EXPECTED_VERIFIED_CITATION, "، ج الأول، ص 8 ")
    return WorkflowScenario(path, (str(first.batch_id), str(second.batch_id)), "W7-READY-2",
        tuple(detail(receipt.batch_id, row.pk) for receipt, row in zip((first, second), rows, strict=True)),
        (f.ORIGINAL_QUESTION, alternate_question), detail(first.batch_id, selected[8].pk),
        detail(first.batch_id, rows[0].pk), detail(first.batch_id, selected[2].pk),
        detail(first.batch_id, selected[3].pk), detail(first.batch_id, selected[2].pk),
        str(rows[1].pk), keys, reasons, expected_reference)
