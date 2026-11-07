"""One time-limited capability for a single open clarification in the training journal."""

import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from .clarifications import valid_timestamp

SCHEMA = {
    "requester_reply_access": "CREATE TABLE requester_reply_access (id INTEGER PRIMARY KEY, "
    "revision INTEGER NOT NULL,request_digest TEXT,source_digest TEXT,draft_digest TEXT,"
    "code_hash TEXT,expires_at TEXT) WITHOUT ROWID",
}
TTL = timedelta(minutes=30)
_CODE = re.compile(r"[A-Za-z0-9_-]{32}")
_HEX = re.compile(r"[a-f0-9]{64}")


class ReplyCodeUnavailable(ValueError):
    """The training reply capability does not open a current request."""


@dataclass(frozen=True, slots=True)
class IssuedCode:
    code: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ReplyPrompt:
    prompt: str
    question: str | None
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class Grant:
    revision: int = 0
    request_digest: str | None = None
    source_digest: str | None = None
    draft_digest: str | None = None
    code_hash: str | None = field(default=None, repr=False)
    expires_at: datetime | None = None

    def active_deadline(self):
        if self.expires_at and timedelta(0) < self.expires_at - datetime.now(UTC) <= TTL:
            return self.expires_at
        return None

    def accepts(self, supplied_hash):
        return (
            self.code_hash
            and hmac.compare_digest(self.code_hash, supplied_hash)
            and self.active_deadline()
        )


def code_hash(code):
    if type(code) is not str or _CODE.fullmatch(code) is None:
        raise ReplyCodeUnavailable("reply_code_unavailable")
    return sha256(code.encode("ascii")).hexdigest()


def read_grant(con, thread, head):
    rows = con.execute("SELECT * FROM requester_reply_access LIMIT 2").fetchall()
    if len(rows) != 1:
        raise ValueError("invalid_reply_grant")
    key, revision, request, source, draft, stored_hash, expiry = rows[0]
    if key != 1 or type(revision) is not int or revision < 1:
        raise ValueError("invalid_reply_grant")
    if stored_hash is None and (request, source, draft, expiry) == (None, None, None, None):
        return Grant(revision)
    if (
        not thread
        or thread[-1].kind != "request"
        or thread[-1].digest != request
        or not head
        or head[1] != source
        or not valid_timestamp(expiry)
        or not all(type(d) is str and _HEX.fullmatch(d) for d in (draft, stored_hash))
    ):
        raise ValueError("invalid_reply_grant")
    return Grant(revision, request, source, draft, stored_hash, datetime.fromisoformat(expiry))


def issue(con, revision, request, source, draft):
    code = secrets.token_urlsafe(24)
    expiry = datetime.now(UTC) + TTL
    if revision == 0:
        con.execute(SCHEMA["requester_reply_access"])
    con.execute(
        "INSERT OR REPLACE INTO requester_reply_access VALUES (1,?,?,?,?,?,?)",
        (
            revision + 1,
            request,
            source,
            draft,
            code_hash(code),
            expiry.isoformat(timespec="microseconds"),
        ),
    )
    return IssuedCode(code, expiry)


def clear(con, grant):
    if grant.code_hash is not None:
        con.execute(
            "UPDATE requester_reply_access SET revision=revision+1,request_digest=NULL,"
            "source_digest=NULL,draft_digest=NULL,code_hash=NULL,expires_at=NULL WHERE id=1"
        )
