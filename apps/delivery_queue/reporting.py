"""Bounded, scoped, read-only projections. Never return signed or lease material."""
from django.db import transaction
from django.utils import timezone
from .models import ApprovalClaim, DeliveryIntent
from . import services as q

SCHEMA = 'fatwa.delivery-report.v1'


def export_scoped_report(*, case_keys, limit=50, after=None):
    if (type(case_keys) is not frozenset or not 1 <= len(case_keys) <= 128
        or any(not q._ref(case) for case in case_keys)
        or type(limit) is not int or not 1 <= limit <= 100
        or (after is not None and not q._hex(after))):
        raise q.QueueConflict('invalid_report_scope_or_page')
    q._postgres_only()
    with transaction.atomic():
        q._verify_locked_head(q._locked_head())
        claims = ApprovalClaim.objects.filter(case_key__in=case_keys).order_by('plan_fingerprint')
        if after is not None:
            claims = claims.filter(plan_fingerprint__gt=after)
        page = list(claims[:limit + 1])
        has_more = len(page) > limit
        page = page[:limit]
        plans = []
        now = timezone.now()
        for claim in page:
            rows = list(DeliveryIntent.objects.filter(approval=claim).order_by('ordinal'))
            summary = q._summary_from_rows(claim, rows)
            plans.append({
                'plan_fingerprint': claim.plan_fingerprint, 'case_key': claim.case_key,
                'provider': rows[0].provider, 'answer_revision': claim.answer_revision,
                'expected_parts': summary.expected_parts, 'delivered_parts': summary.delivered_parts,
                'failed_parts': summary.failed_parts, 'uncertain_parts': summary.uncertain_parts,
                'pending_parts': summary.staged_parts + summary.leased_parts + summary.accepted_parts,
                'state': summary.state, 'complete': summary.complete,
                'authorization_expired': claim.expires_at <= now,
                'parts': [{'ordinal': row.ordinal, 'state': row.state} for row in rows],
                'last_changed_at': max(row.updated_at for row in rows).isoformat(),
            })
        return {'schema': SCHEMA, 'generated_at': now.isoformat(), 'plans': plans,
                'has_more': has_more, 'next_cursor': page[-1].plan_fingerprint if has_more else None}
