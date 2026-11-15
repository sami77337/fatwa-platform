"""Exact synthetic journal handoff. Requests are not approvals; nothing sends."""
from dataclasses import asdict, fields
from hashlib import sha256
from hmac import compare_digest
import json
from pathlib import Path
import re

from apps.delivery_planner.planner import Capabilities
from apps.delivery_planner.trusted_identity import SignedApprovalReceipt, Ed25519ApprovalVerifier, canonical_plan_sha256
from apps.editorial_export.services import require_development
from apps.fast9_case_source_join.answer_drafts import CASE_KEY
from apps.fast9_case_source_join.return_handoff import read_return_candidate
from .approval_adapter import prepare_text_return, commit_signed_approved_plan

SHA = re.compile(r'[a-f0-9]{64}')
SCHEMA = 'fatwa.author-approval-request.v1'
MAX_RESPONSE_BYTES = 16384


class HandoffBlocked(ValueError):
    """Current source/draft no longer permits preparing an approval request."""


class InvalidSignedResponse(ValueError):
    """Bounded fixed errors; never echo untrusted signed input."""


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _build(directory: Path, *, case_key: str, max_chars: int, split: bool,
           synthetic_fixtures_only: bool):
    require_development(synthetic_fixtures_only)
    if (not isinstance(directory, Path) or type(case_key) is not str or case_key != CASE_KEY
        or type(max_chars) is not int or not 1 <= max_chars <= 6000 or type(split) is not bool):
        raise InvalidSignedResponse('invalid_author_handoff_context')
    candidate = read_return_candidate(directory, synthetic_fixtures_only=True)
    if candidate.blockers or candidate.draft is None or candidate.evidence is None:
        raise HandoffBlocked('current_journal_not_ready')
    target = dict(channel=candidate.source_channel, account=candidate.source_account,
                  conversation=candidate.source_conversation, reference=candidate.source_reference)
    if any(type(value) is not str or not value for value in target.values()):
        raise HandoffBlocked('origin_identity_missing')
    # The target is reconstructed only from the journal, including account and
    # message identity. Browser input cannot supply a destination or capability.
    peer = 'origin:' + sha256(_canonical(target)).hexdigest()
    capabilities = Capabilities(candidate.source_channel, 'author-desk-synthetic.v1',
                                frozenset({'text'}), max_chars, True)
    prepared = prepare_text_return(title=candidate.draft.title, body=candidate.draft.body,
        evidence=candidate.evidence, source_peer_key=peer, capabilities=capabilities,
        explicit_human_choice=split)
    request = dict(schema=SCHEMA, status='REQUEST_NOT_APPROVED',
        evidence=asdict(candidate.evidence),
        answer={'title': candidate.draft.title, 'body': candidate.draft.body},
        target=target, plan=asdict(prepared.plan), plan_sha256=canonical_plan_sha256(prepared.plan),
        segments=[asdict(segment) for segment in prepared.segments],
        explicit_split=split, max_chars=max_chars)
    request = json.loads(_canonical(request))
    request['request_sha256'] = sha256(_canonical(request)).hexdigest()
    return request, prepared


def build_approval_request(directory: Path, *, case_key: str, max_chars: int,
                           split: bool, synthetic_fixtures_only: bool = False) -> dict:
    """Read-only deterministic export; no receipt, nonce, signer or key is issued."""
    return _build(directory, case_key=case_key, max_chars=max_chars, split=split,
                  synthetic_fixtures_only=synthetic_fixtures_only)[0]


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidSignedResponse('duplicate_json_field')
        result[key] = value
    return result


def _reject_constant(value):
    raise InvalidSignedResponse('non_json_numeric_constant')


def decode_signed_response(text: str) -> tuple[str, SignedApprovalReceipt]:
    """Decode an existing provider receipt; no private key is ever requested."""
    try:
        if type(text) is not str or not 1 <= len(text.encode('utf-8')) <= MAX_RESPONSE_BYTES:
            raise InvalidSignedResponse('signed_response_size_invalid')
        data = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if type(data) is not dict or set(data) != {'request_sha256', 'receipt'}:
            raise InvalidSignedResponse('signed_response_fields_invalid')
        digest, values = data['request_sha256'], data['receipt']
        if type(digest) is not str or SHA.fullmatch(digest) is None:
            raise InvalidSignedResponse('request_identity_invalid')
        expected = {field.name for field in fields(SignedApprovalReceipt)}
        if type(values) is not dict or set(values) != expected:
            raise InvalidSignedResponse('receipt_fields_invalid')
        for name, value in values.items():
            if name == 'answer_revision':
                if type(value) is not int or not 1 <= value <= 2147483647:
                    raise InvalidSignedResponse('receipt_revision_invalid')
            elif type(value) is not str or len(value.encode('utf-8')) > 1024:
                raise InvalidSignedResponse('receipt_field_type_invalid')
        return digest, SignedApprovalReceipt(**values)
    except (TypeError, UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise InvalidSignedResponse('signed_response_json_invalid') from exc


def stage_signed_response(directory: Path, *, case_key: str, max_chars: int, split: bool,
                          response_json: str, verifier: Ed25519ApprovalVerifier,
                          synthetic_fixtures_only: bool = False) -> dict:
    require_development(synthetic_fixtures_only)
    if not isinstance(verifier, Ed25519ApprovalVerifier):
        raise InvalidSignedResponse('trusted_server_verifier_required')
    requested_digest, receipt = decode_signed_response(response_json)
    request, prepared = _build(directory, case_key=case_key, max_chars=max_chars,
                              split=split, synthetic_fixtures_only=True)
    if not compare_digest(request['request_sha256'], requested_digest):
        raise HandoffBlocked('approval_request_is_stale')

    def current_evidence(requested_case):
        # Called by PR204's signed bridge inside the PostgreSQL transaction,
        # after receipt/nonce locks. Rebuild full technical readiness as well
        # as the CurrentEvidence booleans; neither a browser hash nor an old
        # signed context can substitute for reading the actual source journal.
        current, fresh = _build(directory, case_key=requested_case, max_chars=max_chars,
                                split=split, synthetic_fixtures_only=True)
        if not compare_digest(current['request_sha256'], requested_digest):
            raise HandoffBlocked('approval_request_changed_during_commit')
        return fresh.evidence

    rows = commit_signed_approved_plan(receipt=receipt, evidence=prepared.evidence,
        plan=prepared.plan, verify_receipt=verifier, read_current_evidence=current_evidence)
    states = tuple(row.state for row in rows)
    return {'status': 'STAGED_NOT_SENT' if all(state == 'STAGED' for state in states) else 'ALREADY_RECORDED',
            'request_sha256': requested_digest, 'plan_sha256': request['plan_sha256'],
            'part_count': len(rows), 'parts': [{'ordinal': row.ordinal, 'state': row.state} for row in rows]}
