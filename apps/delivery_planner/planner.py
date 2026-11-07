"""Side-effect-free return-to-origin planning for versioned answers.

No network, sending, automatic publication, or scholarly approval. A trusted
adapter must supply verified authorization and current channel capabilities.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit

_HEX = re.compile(r"^[a-f0-9]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_KINDS = frozenset({"text", "audio", "video", "image", "document", "link"})


class InvalidPlan(ValueError):
    """Reject an unsafe or unsupported delivery proposal."""


@dataclass(frozen=True, slots=True)
class Part:
    ordinal: int
    media_type: str
    sha256: str
    length: int  # characters for text, bytes for media


@dataclass(frozen=True, slots=True)
class Capabilities:
    provider: str
    profile_version: str
    supported: frozenset[str]
    max_text_chars: int
    delivery_receipts: bool


@dataclass(frozen=True, slots=True)
class Authority:
    answer_revision: int
    answer_sha256: str
    evidence_verified: bool  # checked by trusted identity/approval adapter


@dataclass(frozen=True, slots=True)
class Choice:
    use_public_link: bool = False
    publication_verified: bool = False
    published_url: str | None = None


@dataclass(frozen=True, slots=True)
class Step:
    ordinal: int
    action: str
    reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class Plan:
    case_key: str
    source_provider: str
    answer_revision: int
    steps: tuple[Step, ...]
    status: str


def _bounded(value: str, limit: int) -> bool:
    return type(value) is str and 0 < len(value) <= limit and not any(ord(c) < 32 for c in value)


def _valid_url(url: str | None) -> bool:
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 for c in url):
        return False
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
        and port in (None, 443)
    )


def plan_delivery(
    *,
    case_key: str,
    source_peer_key: str,
    parts: tuple[Part, ...],
    capabilities: Capabilities,
    authority: Authority,
    choice: Choice,
) -> Plan:
    """Return a bounded plan; never change a delivery channel implicitly."""
    if not (
        _bounded(case_key, 128)
        and _ID.fullmatch(case_key)
        and _bounded(source_peer_key, 128)
        and _ID.fullmatch(source_peer_key)
        and isinstance(authority, Authority)
        and authority.evidence_verified is True
        and type(authority.answer_revision) is int
        and authority.answer_revision > 0
        and type(authority.answer_sha256) is str
        and _HEX.fullmatch(authority.answer_sha256)
        and isinstance(capabilities, Capabilities)
        and _bounded(capabilities.provider, 64)
        and _bounded(capabilities.profile_version, 64)
        and type(capabilities.max_text_chars) is int
        and 1 <= capabilities.max_text_chars <= 100000
        and type(capabilities.delivery_receipts) is bool
        and type(capabilities.supported) is frozenset
        and capabilities.supported <= _KINDS
        and isinstance(choice, Choice)
        and type(choice.use_public_link) is bool
        and type(choice.publication_verified) is bool
        and type(parts) is tuple
        and 1 <= len(parts) <= 16
    ):
        raise InvalidPlan("invalid_or_unverified_delivery_context")
    if choice.use_public_link and not (
        choice.publication_verified and _valid_url(choice.published_url)
    ):
        raise InvalidPlan("public_link_requires_independent_publication_approval")
    if choice.published_url is not None and not _valid_url(choice.published_url):
        raise InvalidPlan("invalid_published_url")
    if choice.publication_verified and not choice.use_public_link:
        raise InvalidPlan("unused_publication_assertion")

    steps = []
    for number, part in enumerate(parts, 1):
        if not (
            isinstance(part, Part)
            and type(part.ordinal) is int
            and part.ordinal == number
            and part.media_type in _KINDS
            and type(part.sha256) is str
            and _HEX.fullmatch(part.sha256)
            and type(part.length) is int
            and 1 <= part.length <= 10**9
        ):
            raise InvalidPlan("invalid_part_identity")
        supported = part.media_type in capabilities.supported and (
            part.media_type != "text" or part.length <= capabilities.max_text_chars
        )
        if supported:
            action, reason = "READY_FOR_ADAPTER", "source_supports_part"
        elif part.media_type == "text" and part.length > capabilities.max_text_chars:
            action, reason = "HUMAN_ACTION_REQUIRED", "text_segmentation_required"
        elif choice.use_public_link and "link" in capabilities.supported:
            action, reason = "PUBLISHED_LINK_OPTION", "human_approved_public_link_only"
        else:
            action, reason = "HUMAN_ACTION_REQUIRED", "unsupported_source_media"
        evidence = [
            case_key, source_peer_key, capabilities.provider,
            capabilities.profile_version, authority.answer_revision,
            authority.answer_sha256, part.ordinal, part.sha256, action,
            choice.published_url if action == "PUBLISHED_LINK_OPTION" else None,
        ]
        key = sha256(json.dumps(evidence, separators=(",", ":")).encode()).hexdigest()
        steps.append(Step(number, action, reason, key))

    status = (
        "REQUIRES_HUMAN_DECISION"
        if any(s.action != "READY_FOR_ADAPTER" for s in steps)
        else "PLANNED_NOT_SENT"
    )
    return Plan(case_key, capabilities.provider, authority.answer_revision, tuple(steps), status)


def receipt_state(*, planned_step: Step, verified_adapter_receipt: bool, reported: str) -> str:
    """Provider ACCEPTED is not the same as DELIVERED."""
    if not isinstance(planned_step, Step) or planned_step.action != "READY_FOR_ADAPTER":
        raise InvalidPlan("no_adapter_send_for_step")
    if verified_adapter_receipt is not True:
        raise InvalidPlan("unverified_provider_receipt")
    states = {
        "QUEUED": "QUEUED",
        "ACCEPTED": "SENT_UNCONFIRMED",
        "DELIVERED": "DELIVERED",
        "FAILED": "FAILED_REQUIRES_REVIEW",
    }
    if reported not in states:
        raise InvalidPlan("invalid_provider_receipt")
    return states[reported]
