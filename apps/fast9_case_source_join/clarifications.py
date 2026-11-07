"""Clarification conversation for the fixed training case. Request and reply text is preserved as entered in the local training desk."""

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

REPLY_OPTIONS = {
    "order": "في هذه الحالة التدريبية وقع الأمر الأول قبل الثاني.",
    "time": "وقع الأمر المذكور صباح اليوم التالي في المثال التدريبي.",
    "detail": "التفصيل الإضافي في هذه الحالة التدريبية يخص الواقعة الثانية وحدها.",
}
MAX_TURNS = 64  # 32 requests and 32 replies, so the final request can always be answered.
_HEX = re.compile(r"[0-9a-f]{64}")
_BIDI_CONTROLS = frozenset(
    "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
)


class ClarificationInput(ValueError):
    """A malformed prompt, reply choice or version was supplied."""


@dataclass(frozen=True, slots=True)
class ClarificationEvent:
    number: int
    kind: str
    text: str
    recorded_at: str
    digest: str
    source_count: int
    source_digest: str
    draft_digest: str
    actor: str = "synthetic-reviewer"

    @property
    def reply_reference(self) -> str:
        return f"R-{self.number:03d}-{self.digest[:12].upper()}"


def validate_value(kind, value):
    if type(kind) is not str or type(value) is not str:
        raise ClarificationInput("invalid_clarification_value")
    if kind not in {"request", "reply"} or not 1 <= len(value) <= 500 or not value.strip():
        raise ClarificationInput("invalid_clarification_value")
    if any(
        c in _BIDI_CONTROLS or (unicodedata.category(c) in {"Cc", "Cs"} and c not in "\n\r\t")
        for c in value
    ):
        raise ClarificationInput("invalid_clarification_value")


def valid_timestamp(value):
    if type(value) is not str:
        return False
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return False
    return stamp.tzinfo == UTC and stamp.isoformat(timespec="microseconds") == value


def turn_digest(
    previous,
    number,
    kind,
    value,
    recorded_at,
    count,
    source_digest,
    draft_digest,
    actor="synthetic-reviewer",
):
    # Scope and the complete prior dialogue are part of each version, including its prompt.
    data = [
        "intake-7",
        actor,
        previous,
        number,
        kind,
        value,
        recorded_at,
        count,
        source_digest,
        draft_digest,
    ]
    return sha256(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def last_reply_digest(thread):
    return next((e.digest for e in reversed(thread) if e.kind == "reply"), "")


SCHEMA = {
    "clarification_turns": "CREATE TABLE clarification_turns (number INTEGER PRIMARY KEY, "
    "kind TEXT NOT NULL,value TEXT NOT NULL,recorded_at TEXT NOT NULL,source_count INTEGER NOT NULL,"
    "source_digest TEXT NOT NULL,draft_digest TEXT NOT NULL,digest TEXT NOT NULL) WITHOUT ROWID",
    "clarification_head": "CREATE TABLE clarification_head (case_key TEXT PRIMARY KEY, "
    "number INTEGER NOT NULL,digest TEXT NOT NULL) WITHOUT ROWID",
    "clarified_reviews": "CREATE TABLE clarified_reviews (count INTEGER NOT NULL,source_digest TEXT NOT NULL,"
    "draft_digest TEXT NOT NULL,reply_digest TEXT NOT NULL,recorded_at TEXT NOT NULL,reviewer TEXT NOT NULL,"
    "PRIMARY KEY(count,draft_digest,reply_digest)) WITHOUT ROWID",
}
for _table, _key in (
    ("clarification_turns", ("number",)),
    ("clarified_reviews", ("count", "draft_digest", "reply_digest")),
):
    _trigger = "no_replace_" + _table
    _match = " AND ".join(f"{k}=NEW.{k}" for k in _key)
    SCHEMA[_trigger] = (
        f"CREATE TRIGGER {_trigger} BEFORE INSERT ON {_table} "
        f"WHEN EXISTS (SELECT 1 FROM {_table} WHERE {_match}) "
        "BEGIN SELECT RAISE(ABORT, 'append_only'); END"
    )
    for _action in ("UPDATE", "DELETE"):
        _trigger = "no_" + _action.lower() + "_" + _table
        SCHEMA[_trigger] = (
            f"CREATE TRIGGER {_trigger} BEFORE {_action} ON {_table} "
            "BEGIN SELECT RAISE(ABORT, 'append_only'); END"
        )


def read_thread(con, *, requester_enabled=False):
    rows = con.execute(
        "SELECT t.*,e.digest FROM clarification_turns t LEFT JOIN source_events e "
        "ON e.case_key='intake-7' AND t.source_count=e.seq ORDER BY t.number LIMIT ?",
        (MAX_TURNS + 1,),
    ).fetchall()
    if not 1 <= len(rows) <= MAX_TURNS:
        raise ValueError("invalid_clarification_count")
    previous = ""
    thread = []
    for i, (n, kind, value, recorded, count, source, draft, digest, event_digest) in enumerate(
        rows, 1
    ):
        actor = "synthetic-reviewer"
        if kind == "requester_reply" and requester_enabled:
            kind, actor = "reply", "synthetic-requester"
        validate_value(kind, value)
        if (
            n != i
            or kind != ("request" if i % 2 else "reply")
            or source != event_digest
            or (thread and count < thread[-1].source_count)
            or not valid_timestamp(recorded)
            or type(draft) is not str
            or not _HEX.fullmatch(draft)
            or turn_digest(previous, n, kind, value, recorded, count, source, draft, actor)
            != digest
        ):
            raise ValueError("invalid_clarification_record")
        thread.append(
            ClarificationEvent(n, kind, value, recorded, digest, count, source, draft, actor)
        )
        previous = digest
    if con.execute("SELECT * FROM clarification_head LIMIT 2").fetchall() != [
        ("intake-7", len(rows), previous)
    ]:
        raise ValueError("invalid_clarification_head")
    return tuple(thread)
