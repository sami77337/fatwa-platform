"""Compare the reviewer's last seen source text to the last event in a verified snapshot."""

import re
from difflib import SequenceMatcher

from apps.fast9_case_source_join.source_history import SourceEvent


def reading_diff(events: tuple[SourceEvent, ...], baseline_count: int | None) -> dict | None:
    if type(baseline_count) is not int or not 1 <= baseline_count < len(events):
        return None

    before = events[baseline_count - 1].body_utf8
    after = events[-1].body_utf8
    result = {"kind": "omitted", "baseline_count": baseline_count, "segments": []}
    if max(len(before or b""), len(after or b"")) > 16 * 1024:
        return result

    old = (before or b"").decode("utf-8")
    new = (after or b"").decode("utf-8")
    if before == after:
        result["kind"] = "same"
        if old:
            result["segments"].append({"kind": "kept", "text": old})
        return result
    if after is None:
        result["kind"] = "deleted"
        if old:
            result["segments"].append({"kind": "removed", "text": old})
        return result

    # Whitespace runs are tokens too. Combining marks stay with their Arabic word.
    old_tokens = re.findall(r"\s+|\S+", old)
    new_tokens = re.findall(r"\s+|\S+", new)
    if len(old_tokens) * len(new_tokens) > 256 * 256:
        return result
    result["kind"] = "restored" if after == events[0].body_utf8 else "edited"
    diff = SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)
    for tag, i, j, k, end in diff.get_opcodes():
        if tag != "insert":
            kind = "kept" if tag == "equal" else "removed"
            result["segments"].append({"kind": kind, "text": "".join(old_tokens[i:j])})
        if tag in {"insert", "replace"}:
            result["segments"].append({"kind": "added", "text": "".join(new_tokens[k:end])})
    return result
