"""Pure, bounded presentation of immutable revisions; no normalization or writes."""

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from apps.fatwa_drafts.domain import Revision
from apps.fatwa_drafts.intake import ReferenceLink

MAX_TEXT_LENGTH = 10000
ChangeKind = Literal["unchanged", "added", "removed"]
_LABELS = {"unchanged": "دون تغيير", "added": "مضاف", "removed": "محذوف"}
_TEXT_FIELDS = (
    ("title", "العنوان"),
    ("answer", "نص المسودة — حقل التحرير البشري"),
    ("reviewer_notes", "ملاحظات المراجع"),
)
_REFERENCE_FIELDS = (
    ("source_namespace", "نطاق المصدر"),
    ("source_book_id", "معرّف الكتاب"),
    ("edition_key", "مفتاح الطبعة"),
    ("source_archive_sha256", "بصمة الأرشيف الاصطناعي"),
    ("source_input_sha256", "بصمة المدخل الاصطناعي"),
    ("source_id", "معرّف العنوان"),
)


@dataclass(frozen=True, slots=True)
class TextPart:
    kind: ChangeKind
    text: str

    @property
    def visible_whitespace(self) -> str:
        return (self.text.replace(" ", "·").replace("\t", "⇥")
                .replace("\r", "␍").replace("\n", "␊\n"))


@dataclass(frozen=True, slots=True)
class TextComparison:
    key: str
    label: str
    before: tuple[TextPart, ...]
    after: tuple[TextPart, ...]
    changed: bool


@dataclass(frozen=True, slots=True)
class ReferenceComparison:
    reference: ReferenceLink
    kind: ChangeKind
    position: int
    other_position: int | None

    @property
    def label(self) -> str:
        return _LABELS[self.kind]

    @property
    def position_changed(self) -> bool:
        return self.other_position is not None and self.position != self.other_position

    @property
    def identity_fields(self) -> tuple[tuple[str, str], ...]:
        return tuple((label, getattr(self.reference, name)) for name, label in _REFERENCE_FIELDS)


@dataclass(frozen=True, slots=True)
class ChangeTarget:
    anchor: str
    label: str


@dataclass(frozen=True, slots=True)
class RevisionComparison:
    fields: tuple[TextComparison, ...]
    before_references: tuple[ReferenceComparison, ...]
    after_references: tuple[ReferenceComparison, ...]
    references_changed: bool
    targets: tuple[ChangeTarget, ...]

    @property
    def changed(self) -> bool:
        return bool(self.targets)


def _validate(revision: Revision) -> None:
    if not isinstance(revision, Revision):
        raise TypeError("comparison_requires_revision")
    for name, _ in _TEXT_FIELDS:
        value = getattr(revision, name)
        if not isinstance(value, str) or len(value) > MAX_TEXT_LENGTH:
            raise ValueError("comparison_text_invalid_or_too_long")
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ValueError("comparison_text_invalid_unicode") from exc
    refs = revision.reference_links
    if (not isinstance(refs, tuple) or len(refs) > 100
            or any(not isinstance(ref, ReferenceLink) for ref in refs)):
        raise ValueError("comparison_references_invalid")
    if len(set(refs)) != len(refs):
        raise ValueError("comparison_references_duplicate")


def _text_comparison(key: str, label: str, before: str, after: str) -> TextComparison:
    old_parts: list[TextPart] = []
    new_parts: list[TextPart] = []
    # Code-point comparison: preserve every original character, including whitespace.
    for tag, i, j, k, end in SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        if tag == "equal":
            old_parts.append(TextPart("unchanged", before[i:j]))
            new_parts.append(TextPart("unchanged", after[k:end]))
        else:
            if i != j:
                old_parts.append(TextPart("removed", before[i:j]))
            if k != end:
                new_parts.append(TextPart("added", after[k:end]))
    return TextComparison(key, label, tuple(old_parts), tuple(new_parts), before != after)


def _references(
    source: tuple[ReferenceLink, ...], other: tuple[ReferenceLink, ...], missing: ChangeKind,
) -> tuple[ReferenceComparison, ...]:
    other_positions = {ref: index for index, ref in enumerate(other, 1)}
    return tuple(
        ReferenceComparison(ref, "unchanged" if ref in other_positions else missing,
                            index, other_positions.get(ref))
        for index, ref in enumerate(source, 1)
    )


def compare_revisions(before: Revision, after: Revision) -> RevisionComparison:
    """Compare text and all six identity fields; retain reference order and positions.

    A reference with the same identity but a new position remains unchanged in
    identity and explicitly reports its changed position. Metadata/state is not edited.
    Only this bounded synthetic preview consumes the result; it is not an approval API.
    """
    _validate(before)
    _validate(after)
    fields = tuple(_text_comparison(key, label, getattr(before, key), getattr(after, key))
                   for key, label in _TEXT_FIELDS)
    refs_changed = before.reference_links != after.reference_links
    targets = tuple(ChangeTarget("change-" + field.key, field.label)
                    for field in fields if field.changed)
    if refs_changed:
        targets += (ChangeTarget("change-references", "هويات المراجع وترتيبها"),)
    return RevisionComparison(
        fields, _references(before.reference_links, after.reference_links, "removed"),
        _references(after.reference_links, before.reference_links, "added"), refs_changed, targets,
    )
