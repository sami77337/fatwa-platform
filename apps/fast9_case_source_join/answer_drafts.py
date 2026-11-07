"""Unpublished answer versions for one synthetic case and one independent training author."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from apps.fatwa_drafts.intake import ValidationError, text

from .clarifications import valid_timestamp

AUTHOR = "synthetic-mufti-author"
TITLE_LIMIT = 160
BODY_LIMIT = 6000
MAX_DRAFTS = 64
MAX_NOTES = 64  # 32 requests; each can be followed by an explicit close or withdrawal.
NOTE_LIMIT = 500
REVIEWER = "synthetic-reviewer"
CASE_KEY = "intake-7"

SCHEMA = {
    "answer_drafts": "CREATE TABLE answer_drafts (revision INTEGER PRIMARY KEY, title TEXT NOT NULL,"
    "body TEXT NOT NULL,actor TEXT NOT NULL,recorded_at TEXT NOT NULL,source_count INTEGER NOT NULL,"
    "source_digest TEXT NOT NULL,reply_digest TEXT NOT NULL,digest TEXT NOT NULL) WITHOUT ROWID",
    "answer_draft_head": "CREATE TABLE answer_draft_head (id INTEGER PRIMARY KEY,"
    "base_schema INTEGER NOT NULL,revision INTEGER NOT NULL,digest TEXT NOT NULL,"
    "note_count INTEGER NOT NULL,note_digest TEXT NOT NULL) WITHOUT ROWID",
    "answer_draft_notes": "CREATE TABLE answer_draft_notes (number INTEGER PRIMARY KEY,action TEXT NOT NULL,"
    "text TEXT NOT NULL,revision INTEGER NOT NULL,draft_digest TEXT NOT NULL,actor TEXT NOT NULL,"
    "recorded_at TEXT NOT NULL,digest TEXT NOT NULL) WITHOUT ROWID",
}
for table, key in (("answer_drafts", "revision"), ("answer_draft_notes", "number")):
    name = "no_replace_" + table
    SCHEMA[name] = (
        f"CREATE TRIGGER {name} BEFORE INSERT ON {table} "
        f"WHEN EXISTS (SELECT 1 FROM {table} WHERE {key}=NEW.{key}) "
        "BEGIN SELECT RAISE(ABORT, 'append_only'); END"
    )
    for action in ("UPDATE", "DELETE"):
        name = f"no_{action.lower()}_{table}"
        SCHEMA[name] = (
            f"CREATE TRIGGER {name} BEFORE {action} ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'append_only'); END"
        )


class DraftInputError(ValueError):
    """A training draft could not be saved with the submitted values."""


@dataclass(frozen=True, slots=True)
class AnswerDraft:
    revision: int
    title: str
    body: str
    actor: str
    recorded_at: str
    source_count: int
    source_digest: str
    reply_digest: str
    digest: str


@dataclass(frozen=True, slots=True)
class DraftNote:
    number: int
    action: str
    text: str
    revision: int
    draft_digest: str
    actor: str
    recorded_at: str
    digest: str


def validate_note(action, value):
    if type(action) is not str or action not in {"request", "withdraw", "close"}:
        raise DraftInputError("invalid_draft_note_action")
    if action == "request":
        try:
            text(value, "change request", limit=NOTE_LIMIT)
        except ValidationError as exc:
            raise DraftInputError("invalid_draft_note_text") from exc
    elif type(value) is not str or value:
        raise DraftInputError("unexpected_draft_note_text")


def note_action_allowed(notes, action, revision):
    last = notes[-1] if notes else None
    if last is None or last.action != "request":
        return action == "request"
    if action == "close":
        return revision > last.revision
    return action == "withdraw" and revision == last.revision


def validate_text(title, body):
    try:
        text(title, "title", limit=TITLE_LIMIT)
        text(body, "body", limit=BODY_LIMIT)
    except ValidationError as exc:
        raise DraftInputError("invalid_draft_text") from exc
    # Reserve space for the version pins within the journal's 16 KiB SQLite row limit.
    if len(title.encode()) + len(body.encode()) > 12 * 1024:
        raise DraftInputError("draft_text_too_large")


def _digest(previous, values):
    payload = json.dumps([CASE_KEY, *values], ensure_ascii=False, separators=(",", ":")).encode()
    return sha256(bytes.fromhex(previous) + payload).hexdigest()


def head(con):
    rows = con.execute(
        "SELECT id,base_schema,revision,digest,note_count,note_digest FROM answer_draft_head LIMIT 2"
    ).fetchall()
    if len(rows) != 1:
        raise ValueError("answer_draft_head_missing")
    key, base, revision, digest, note_count, note_tip = rows[0]
    if (
        key != 1
        or base not in (1, 2, 3, 4)
        or type(revision) is not int
        or not 1 <= revision <= MAX_DRAFTS
        or type(note_count) is not int
        or not 0 <= note_count <= MAX_NOTES
    ):
        raise ValueError("answer_draft_head_invalid")
    return base, revision, digest, note_count, note_tip


def read(con, thread, expected_head):
    rows = con.execute(
        "SELECT a.*,s.digest FROM answer_drafts a LEFT JOIN source_events s "
        "ON s.case_key=? AND s.seq=a.source_count ORDER BY a.revision LIMIT ?",
        (CASE_KEY, MAX_DRAFTS + 1),
    ).fetchall()
    if len(rows) != expected_head[1]:
        raise ValueError("answer_draft_history_incomplete")
    replies = {turn.digest: turn for turn in thread if turn.kind == "reply"}
    versions = []
    previous = ""
    last_source_count = last_reply_number = 0
    for number, (*fields, digest, source_at_count) in enumerate(rows, 1):
        draft = AnswerDraft(*fields, digest)
        validate_text(draft.title, draft.body)
        if draft.reply_digest:
            reply = replies.get(draft.reply_digest)
            if reply is None or reply.source_count > draft.source_count:
                raise ValueError("answer_draft_reply_mismatch")
            reply_number = reply.number
        else:
            reply_number = 0
        if (
            draft.revision != number
            or draft.actor != AUTHOR
            or source_at_count != draft.source_digest
            or draft.source_count < last_source_count
            or reply_number < last_reply_number
            or not valid_timestamp(draft.recorded_at)
            or _digest(previous, fields) != digest
        ):
            raise ValueError("answer_draft_history_invalid")
        previous = digest
        last_source_count, last_reply_number = draft.source_count, reply_number
        versions.append(draft)
    if previous != expected_head[2]:
        raise ValueError("answer_draft_tip_mismatch")
    notes = []
    previous = ""
    for number, (*fields, digest) in enumerate(
        con.execute("SELECT * FROM answer_draft_notes ORDER BY number LIMIT ?", (MAX_NOTES + 1,)), 1
    ):
        event = DraftNote(*fields, digest)
        validate_note(event.action, event.text)
        if (
            event.number != number
            or event.actor != REVIEWER
            or not valid_timestamp(event.recorded_at)
            or type(event.revision) is not int
            or not 1 <= event.revision <= len(versions)
            or event.draft_digest != versions[event.revision - 1].digest
            or (notes and event.revision < notes[-1].revision)
            or not note_action_allowed(notes, event.action, event.revision)
            or _digest(previous, ("change-note", *fields)) != event.digest
        ):
            raise ValueError("draft_note_history_invalid")
        notes.append(event)
        previous = digest
    if (len(notes), previous) != expected_head[3:]:
        raise ValueError("draft_note_tip_mismatch")
    return tuple(versions), tuple(notes)


def append(con, versions, title, body, count, source_digest, reply_digest):
    number = len(versions) + 1
    if number > MAX_DRAFTS:
        raise DraftInputError("answer_draft_capacity")
    values = (
        number,
        title,
        body,
        AUTHOR,
        datetime.now(UTC).isoformat(timespec="microseconds"),
        count,
        source_digest,
        reply_digest,
    )
    digest = _digest(versions[-1].digest if versions else "", values)
    if not versions:
        # Remember the exact previously active schema, including whether grants ever existed.
        (base,) = con.execute("PRAGMA user_version").fetchone()
        for sql in SCHEMA.values():
            con.execute(sql)
        con.execute("PRAGMA user_version=5")
        con.execute("INSERT INTO answer_draft_head VALUES (1,?,?,?,0,'')", (base, number, digest))
    else:
        con.execute("UPDATE answer_draft_head SET revision=?,digest=? WHERE id=1", (number, digest))
    con.execute("INSERT INTO answer_drafts VALUES (?,?,?,?,?,?,?,?,?)", (*values, digest))
    return AnswerDraft(*values, digest)


def append_note(con, notes, action, value, revision, draft_digest):
    number = len(notes) + 1
    if number > MAX_NOTES:
        raise DraftInputError("draft_note_capacity")
    fields = (
        number,
        action,
        value,
        revision,
        draft_digest,
        REVIEWER,
        datetime.now(UTC).isoformat(timespec="microseconds"),
    )
    digest = _digest(notes[-1].digest if notes else "", ("change-note", *fields))
    con.execute("INSERT INTO answer_draft_notes VALUES (?,?,?,?,?,?,?,?)", (*fields, digest))
    con.execute(
        "UPDATE answer_draft_head SET note_count=?,note_digest=? WHERE id=1", (number, digest)
    )
    return DraftNote(*fields, digest)
