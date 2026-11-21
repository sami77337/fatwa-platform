"""Two short authorization transactions, with provider execution between them.

Only exact candidate locations cross this boundary. The module cannot call an
answer-writing, citation-saving, approval, publication or delivery service.
"""

import json
import os
import re
from contextlib import contextmanager
from hashlib import sha256
from time import monotonic

from django.conf import settings
from django.db import connection

from apps.casework import services as cases
from apps.data_privacy import integration as privacy
from apps.data_privacy import services as privacy_policy
from apps.data_privacy.catalog import locate as classified_source
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.mufti_review.identity import IdentityUnavailable
from apps.platform_recovery.integration import mutation_context, mutation_service
from apps.precise_citations import sources
from apps.precise_citations.boundary import digest, scope, seal, verify
from apps.research_library import services as library

from .authority import GatewayAuthority
from .contract import (
    PROMPT,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    TASK,
    TASK_VERSION,
    CitationProvider,
    CitationRequest,
    ProviderSpec,
    SourceWindow,
)
from .execution import invoke
from .models import CandidateBatch, GatewayOutcome, GatewayRun

MAX_QUERY = 240
MAX_WINDOW = 4000
MAX_SOURCE = 16000
MAX_OUTPUT = 8192
MAX_CANDIDATES = 5
DEADLINE_SECONDS = 20
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_AI_GATEWAY_ENABLED", False) is not True
        or getattr(settings, "FATWA_AI_CITATION_CANDIDATES_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("ai_gateway_disabled")


def configuration():
    enabled()
    authority = getattr(settings, "FATWA_AI_GATEWAY_AUTHORITY", None)
    if not isinstance(authority, GatewayAuthority):
        raise cases.CaseConflict("ai_gateway_authority_required")
    try:
        epoch = authority.projection_epoch()
    except Exception as exc:
        raise cases.CaseConflict("ai_gateway_epoch_required") from exc
    if type(epoch) is not str or not 1 <= len(epoch) <= 131072:
        raise cases.CaseConflict("ai_gateway_epoch_required")
    provider = getattr(settings, "FATWA_AI_CITATION_PROVIDER", None)
    spec = None
    if provider is not None:
        try:
            spec = provider.spec
        except Exception as exc:
            raise cases.CaseConflict("ai_gateway_provider_contract_required") from exc
        if not isinstance(provider, CitationProvider) or type(spec) is not ProviderSpec:
            raise cases.CaseConflict("ai_gateway_provider_contract_required")
        if spec.mode not in {"SYNTHETIC", "CONFIGURED"} or any(
            type(value) is not str or IDENTIFIER.fullmatch(value) is None
            for value in (spec.key, spec.model_id, spec.model_version, spec.adapter_version)
        ):
            raise cases.CaseConflict("ai_gateway_provider_version_required")
        killed = getattr(settings, "FATWA_AI_DISABLED_PROVIDERS", frozenset())
        if type(killed) not in {set, frozenset} or spec.key in killed:
            raise cases.CaseConflict("ai_gateway_provider_disabled")
    return authority, epoch, provider, spec


def provider_fields(spec):
    return dict(
        provider_key=spec.key if spec else "",
        model_id=spec.model_id if spec else "",
        model_version=spec.model_version if spec else "",
        adapter_version=spec.adapter_version if spec else "",
        provider_mode=spec.mode if spec else "UNCONFIGURED",
    )


class Grants:
    def __init__(self, guard, case_id):
        self.guard, self.case_id = guard, case_id
        self.config = configuration()
        self.permissions = []
        self.case, self.actor = guard.permit(case_id, "EDIT")

    def permit(self, action, kind, identifier, source_digest):
        spec = self.config[3]
        values = dict(
            provider_id=self.guard.provider.provider_id,
            subject_id=self.actor.subject_id,
            auth_epoch=self.actor.auth_epoch,
            case_ref=self.case.public_ref,
            action=action,
            task=TASK,
            destination_provider=spec.key if spec else "",
            model_id=spec.model_id if spec else "",
            model_version=spec.model_version if spec else "",
            resource_kind=kind,
            resource_id=identifier,
            resource_digest=source_digest,
        )
        self.call(values)
        self.permissions.append(values)

    def call(self, values):
        try:
            permitted = self.config[0].permits(**values)
        except Exception as exc:
            raise cases.CaseConflict("ai_gateway_authority_unavailable") from exc
        if permitted is not True:
            raise cases.CaseConflict("ai_gateway_processing_denied")

    def pure_check(self):
        if configuration() != self.config:
            raise cases.CaseConflict("ai_gateway_projection_changed")

    def callbacks(self):
        for values in self.permissions:
            self.call(values)
        self.pure_check()


def privacy_context(guard, case, actor, kind, identifier):
    """Classify only existing sources, before their text becomes a provider input.

    Source ownership is internal lookup metadata. Reading or citing that source
    never substitutes for the independently configured AI processing grant.
    """
    target = classified_source("LIBRARY_VERSION" if kind == "LIBRARY" else "ANSWER", identifier)
    resources = [("CASE", str(case.pk))]
    if target.case_id != str(case.pk):
        resources.append(("CASE", target.case_id))
    resources.append((target.kind, target.identifier))
    pins = tuple(
        (
            resource_kind,
            resource_id,
            action,
            privacy.staff(
                resource_kind,
                resource_id,
                provider=guard.provider,
                actor=actor,
                action=action,
            ),
        )
        for resource_kind, resource_id in resources
        for action in ("READ", "AI")
    )
    if all(pin[3] is None for pin in pins):
        return None
    authority, epoch = privacy_policy.policy()
    # Preserve the configured authority and its complete pure epoch across the
    # provider gap, in addition to each exact source/classification digest.
    return id(authority), authority, epoch, pins


@privacy.contextual
@contextmanager
def authorized(
    base, *, revision, evidence, query_digest, selection=None, start=None, end=None, run=None
):
    # The outer transaction remains open until AI's pure final check AFTER the
    # citation/library boundary's final callbacks. Late callbacks cannot commit
    # candidates and then revoke processing before the response is returned.
    with synthetic_queue_atomic():
        with scope(**base) as guard:
            grants = Grants(guard, base["case_id"])
            case, actor = grants.case, grants.actor
            cases._versions(case, revision, evidence)
            grants.permit("USE", "CASE", str(case.pk), "")
            if run is not None:
                verify(run)
                if (
                    run.case_id != case.pk
                    or run.identity_provider != guard.provider.provider_id
                    or run.subject_id != actor.subject_id
                    or run.auth_epoch != actor.auth_epoch
                    or any(
                        getattr(run, key) != value
                        for key, value in provider_fields(grants.config[3]).items()
                    )
                ):
                    raise cases.CaseConflict("ai_gateway_run_audience_changed")
                pin = run.source
                privacy_snapshot = privacy_context(guard, case, actor, pin["kind"], pin["id"])
                live = sources.read(guard, pin, owner_case_id=case.pk)
            else:
                if (
                    type(selection) is not str
                    or selection.count(":") != 1
                    or not selection.startswith(("LIBRARY:", "ANSWER:"))
                ):
                    raise cases.CaseConflict("ai_gateway_source_unsupported")
                if (
                    type(start) is not int
                    or type(end) is not int
                    or not 0 <= start < end
                    or end - start > MAX_WINDOW
                ):
                    raise cases.CaseConflict("ai_gateway_window_invalid")
                source_kind, source_id = selection.split(":")
                privacy_snapshot = privacy_context(guard, case, actor, source_kind, source_id)
                pin, live = sources.select(
                    guard,
                    selection,
                    owner_case_id=case.pk,
                    location=sources.locator("TEXT", start, end),
                )
            if (
                pin["kind"] not in {"LIBRARY", "ANSWER"}
                or pin["part_id"]
                or pin["locator"]["mode"] != "TEXT"
                or not 1 <= len(live["text"]) <= MAX_SOURCE
                or (
                    live["file"] is not None
                    and live["file"]["media_type"]
                    not in {"text/plain", "text/plain; charset=utf-8"}
                )
            ):
                raise cases.CaseConflict("ai_gateway_exact_text_required")
            if grants.config[3] is not None:
                grants.permit("PROCESS_CONTEXT", "DRAFT_FRAGMENT", query_digest, query_digest)
                grants.permit("PROCESS_CONTEXT", pin["kind"], pin["id"], pin["digest"])
            context_digest = digest(
                [
                    TASK_VERSION,
                    PROMPT_VERSION,
                    SCHEMA_VERSION,
                    provider_fields(grants.config[3]),
                    query_digest,
                    pin,
                    sha256(live["selected"].encode()).hexdigest(),
                ]
            )
            if run is not None and context_digest != run.context_digest:
                raise cases.CaseConflict("ai_gateway_source_changed")
            snapshot = (
                grants.config,
                guard.authority,
                guard.epoch,
                library.identity_snapshot(guard.provider),
                library.identity_snapshot(guard.directory),
                library.policy_snapshot() if pin["kind"] == "LIBRARY" else None,
                privacy_snapshot,
            )
            grants.pure_check()
            yield dict(
                guard=guard,
                grants=grants,
                actor=actor,
                case=case,
                pin=pin,
                live=live,
                context_digest=context_digest,
                snapshot=snapshot,
            )
            grants.callbacks()
        grants.pure_check()


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def validate_output(raw, run):
    if type(raw) is not bytes or len(raw) > MAX_OUTPUT:
        raise ValueError("bounded bytes required")
    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=strict_object,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("constant")),
    )
    if type(value) is not dict or set(value) != {"candidates"}:
        raise ValueError("schema")
    entries = value["candidates"]
    if type(entries) is not list or len(entries) > MAX_CANDIDATES:
        raise ValueError("candidate bound")
    seen = set()
    window = run.source["locator"]
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"source_id", "start", "end"}:
            raise ValueError("candidate schema")
        start, end = entry["start"], entry["end"]
        if (
            entry["source_id"] != run.source["id"]
            or type(start) is not int
            or type(end) is not int
            or not window["start"] <= start < end <= window["end"]
            or end - start > 1000
            or (start, end) in seen
        ):
            raise ValueError("candidate source or range")
        seen.add((start, end))
    return entries


def terminal(run, status, entries=None):
    output_digest = digest(entries) if entries is not None else ""
    seal(GatewayOutcome(run=run, status=status, output_digest=output_digest))
    if entries is not None:
        seal(CandidateBatch(run=run, entries=entries))
    return {"id": str(run.pk), "status": status}


@mutation_service
def request_candidates(
    *,
    case_id,
    subject_id,
    provider,
    synthetic_fixtures_only=False,
    query,
    selection,
    start,
    end,
    expected_revision,
    expected_evidence_version,
    request_key,
    task=TASK,
):
    if connection.in_atomic_block:
        raise cases.CaseConflict("ai_gateway_outer_boundary_required")
    enabled()
    if (
        task != TASK
        or type(query) is not str
        or not query.strip()
        or len(query) > MAX_QUERY
        or any(ord(char) < 32 and char not in "\t\n\r" for char in query)
    ):
        raise cases.CaseConflict("ai_gateway_input_invalid")
    base = dict(
        case_id=case_id,
        subject_id=subject_id,
        provider=provider,
        synthetic_fixtures_only=synthetic_fixtures_only,
    )
    query_digest = sha256(query.encode()).hexdigest()
    key = cases._uuid(request_key)
    request_digest = digest(
        [
            str(cases._uuid(case_id)),
            provider.provider_id,
            subject_id,
            query_digest,
            selection,
            start,
            end,
            expected_revision,
            expected_evidence_version,
            TASK,
        ]
    )
    prior = None
    with authorized(
        base,
        revision=expected_revision,
        evidence=expected_evidence_version,
        query_digest=query_digest,
        selection=selection,
        start=start,
        end=end,
    ) as context:
        request_digest = digest([request_digest, provider_fields(context["grants"].config[3])])
        prior = GatewayRun.objects.filter(request_key=key).first()
        if prior is not None:
            verify(prior)
            if prior.request_digest != request_digest:
                raise cases.CaseConflict("ai_gateway_request_key_reused")
        else:
            spec = context["grants"].config[3]
            run = seal(
                GatewayRun(
                    case=context["case"],
                    identity_provider=provider.provider_id,
                    subject_id=subject_id,
                    auth_epoch=context["actor"].auth_epoch,
                    request_key=key,
                    request_digest=request_digest,
                    task=TASK,
                    task_version=TASK_VERSION,
                    prompt_version=PROMPT_VERSION,
                    schema_version=SCHEMA_VERSION,
                    **provider_fields(spec),
                    expected_revision=expected_revision,
                    expected_evidence_version=expected_evidence_version,
                    query_digest=query_digest,
                    context_digest=context["context_digest"],
                    source=context["pin"],
                )
            )
            if spec is None:
                unavailable = terminal(run, "PROVIDER_UNAVAILABLE")
            else:
                snapshot = context["snapshot"]
                source = SourceWindow(
                    run.source["id"],
                    run.source["digest"],
                    run.source["number"],
                    start,
                    end,
                    context["live"]["selected"],
                )
                configured_provider = context["grants"].config[2]
    if prior is not None:
        with read_boundary(**base, run_id=prior.pk) as result:
            return {"id": result["id"], "status": result["status"]}
    if spec is None:
        return unavailable
    deadline = monotonic() + DEADLINE_SECONDS
    request = CitationRequest(
        TASK, TASK_VERSION, PROMPT_VERSION, SCHEMA_VERSION, PROMPT, query, source, deadline
    )
    entries, status = None, "PROVIDER_FAILED"
    try:
        returned, raw = invoke(configured_provider, request, timeout=DEADLINE_SECONDS)
        if returned and monotonic() <= deadline:
            try:
                entries = validate_output(raw, run)
                status = "SUCCEEDED"
            except (ValueError, TypeError, UnicodeError, RecursionError):
                status = "OUTPUT_REJECTED"
    except Exception:
        # No provider exception body or rejected raw output reaches logs, DB or UI.
        status = "PROVIDER_FAILED"
    try:
        with authorized(
            base,
            revision=expected_revision,
            evidence=expected_evidence_version,
            query_digest=query_digest,
            run=run,
        ) as context:
            if context["snapshot"] != snapshot:
                raise cases.CaseConflict("ai_gateway_trust_changed_during_provider")
            result = terminal(run, status, entries if status == "SUCCEEDED" else None)
        return result
    except (cases.CaseConflict, IdentityUnavailable) as exc:
        # Finalize only the already-admitted attempt, with no output/context body.
        # This internal audit effect grants no rights and cannot expose a candidate.
        with synthetic_queue_atomic():
            terminal(run, "REVOKED")
        raise cases.CaseConflict("ai_gateway_current_trust_revoked") from exc


@mutation_context
@contextmanager
def read_boundary(
    *, case_id, subject_id, provider, run_id, synthetic_fixtures_only=False, selected_index=None
):
    run = GatewayRun.objects.filter(pk=cases._uuid(run_id), case_id=cases._uuid(case_id)).first()
    if run is None:
        raise cases.CaseConflict("ai_gateway_run_unavailable")
    base = dict(
        case_id=case_id,
        subject_id=subject_id,
        provider=provider,
        synthetic_fixtures_only=synthetic_fixtures_only,
    )
    with authorized(
        base,
        revision=run.expected_revision,
        evidence=run.expected_evidence_version,
        query_digest=run.query_digest,
        run=run,
    ) as context:
        outcome = GatewayOutcome.objects.filter(run=run).first()
        if outcome is None:
            raise cases.CaseConflict("ai_gateway_attempt_incomplete")
        verify(outcome)
        result = dict(
            id=str(run.pk),
            status=outcome.status,
            provider_mode=run.provider_mode,
            provider_key=run.provider_key,
            model_id=run.model_id,
            model_version=run.model_version,
            candidates=[],
        )
        if outcome.status == "SUCCEEDED":
            batch = CandidateBatch.objects.filter(run=run).first()
            if batch is None:
                raise cases.CaseConflict("ai_gateway_derivative_unavailable")
            verify(batch)
            if digest(batch.entries) != outcome.output_digest:
                raise cases.CaseConflict("ai_gateway_derivative_changed")
            validate_output(json.dumps({"candidates": batch.entries}).encode(), run)
            for index, entry in enumerate(batch.entries):
                pin = {
                    **run.source,
                    "locator": sources.locator("TEXT", entry["start"], entry["end"]),
                }
                live = sources.read(context["guard"], pin, owner_case_id=case_id)
                result["candidates"].append({**live, "pin": pin, "index": index})
        if selected_index is not None:
            if type(selected_index) is not int or not 0 <= selected_index < len(
                result["candidates"]
            ):
                raise cases.CaseConflict("ai_gateway_selection_invalid")
            result["selected"] = result["candidates"][selected_index]
        yield result
