"""Lossless, explicitly chosen text segmentation for Return-to-Origin planning.

A split changes channel-visible message boundaries, so the caller must record
an explicit human choice when a single text part exceeds the capability limit.
Nothing is published or sent. Stored original drafts are not changed.
"""
from dataclasses import dataclass
from hashlib import sha256
import unicodedata

from .planner import Capabilities, InvalidPlan, Part

MAX_SEGMENTS = 16
MAX_TEXT_CHARS = 6000


@dataclass(frozen=True, slots=True)
class TextSegment:
    ordinal: int
    exact_text: str
    sha256: str
    length: int


class SegmentationNeedsReview(InvalidPlan):
    """The proposed segmentation cannot be completed without human editing."""


def _safe_boundary(value: str, position: int) -> bool:
    if position <= 0 or position >= len(value):
        return True
    next_char = value[position]
    prev_char = value[position - 1]
    if prev_char == "\r" and next_char == "\n":
        return False
    if prev_char == "\u200d" or next_char == "\u200d":
        return False
    if unicodedata.category(next_char) in {"Mn", "Mc", "Me"}:
        return False
    if 0xFE00 <= ord(next_char) <= 0xFE0F:
        return False
    return True


def segment_text(
    original: str,
    *,
    max_chars: int,
    explicit_human_choice: bool = False,
    max_segments: int = MAX_SEGMENTS,
) -> tuple[TextSegment, ...]:
    """Preserve exact Unicode, whitespace, and punctuation through segmentation.

    Refuse to break a word/grapheme merely to satisfy the provider. No ellipsis,
    trimming, translation or inserted separators. An unbreakable token or too
    many segments is returned to the operator for an explicit new decision.
    """
    if (
        type(original) is not str
        or not 1 <= len(original) <= MAX_TEXT_CHARS
        or type(max_chars) is not int
        or not 1 <= max_chars <= 100000
        or type(max_segments) is not int
        or not 1 <= max_segments <= MAX_SEGMENTS
        or type(explicit_human_choice) is not bool
        or any(unicodedata.category(char) == "Cs" for char in original)
    ):
        raise InvalidPlan("invalid_text_segmentation_input")
    if len(original) > max_chars and not explicit_human_choice:
        raise SegmentationNeedsReview("split_requires_explicit_human_choice")

    raw_segments: list[str] = []
    start = 0
    end = len(original)
    while start < end:
        cut = min(start + max_chars, end)
        if cut < end:
            # Prefer a boundary immediately after whitespace. This leaves the
            # following word intact and keeps the separator in the prior part.
            candidates = (
                i for i in range(cut, start, -1)
                if original[i - 1].isspace() and _safe_boundary(original, i)
            )
            cut = next(candidates, 0)
            if not cut:
                raise SegmentationNeedsReview("unbreakable_token_requires_human_edit")
        raw_segments.append(original[start:cut])
        if len(raw_segments) > max_segments:
            raise SegmentationNeedsReview("too_many_delivery_parts")
        start = cut

    if "".join(raw_segments) != original:
        raise AssertionError("lossless_segmentation_invariant")
    return tuple(
        TextSegment(i, part, sha256(part.encode("utf-8")).hexdigest(), len(part))
        for i, part in enumerate(raw_segments, 1)
    )


def parts_for_delivery(
    text: str, capabilities: Capabilities, *, explicit_human_choice: bool = False
) -> tuple[tuple[Part, ...], tuple[TextSegment, ...]]:
    """Create bounded planner parts without altering or delivering the source."""
    if (
        not isinstance(capabilities, Capabilities)
        or "text" not in capabilities.supported
    ):
        raise SegmentationNeedsReview("source_does_not_support_text_delivery")
    segments = segment_text(
        text, max_chars=capabilities.max_text_chars,
        explicit_human_choice=explicit_human_choice,
    )
    return (
        tuple(Part(part.ordinal, "text", part.sha256, part.length) for part in segments),
        segments,
    )
