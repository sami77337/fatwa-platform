"""A complete exact-byte verdict is independent from structural/media validation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

MAX_BYTES = 192000
MAX_FILES = 22  # Existing import envelope: 20 members plus manifest/records.
PURPOSES = frozenset(
    {
        "CASE_ATTACHMENT",
        "SOURCE_ATTACHMENT",
        "ANSWER_FILE",
        "LIBRARY_FILE",
        "IMPORT_FILE",
        "TRANSCRIPT_BUNDLE",
    }
)
STATUSES = (
    "CLEAN",
    "BLOCKED",
    "UNAVAILABLE",
    "FAILED",
    "TIMED_OUT",
    "INCOMPLETE",
    "REVOKED",
    "BUSY",
)


@dataclass(frozen=True, slots=True)
class ScanPolicy:
    key: str
    timeout_seconds: float
    validity_seconds: int
    max_quarantined_files: int


@dataclass(frozen=True, slots=True)
class ScannerSpec:
    key: str
    engine_version: str
    signature_version: str
    signature_digest: str
    configuration_digest: str
    mode: str


@dataclass(frozen=True, slots=True)
class ScanInput:
    raw: bytes
    sha256: str
    size: int
    deadline_monotonic: float


@dataclass(frozen=True, slots=True)
class ScanVerdict:
    status: str
    sha256: str
    size: int
    spec: ScannerSpec
    complete: bool
    scanned_files: int
    loaded_signatures: int


@dataclass(frozen=True, slots=True)
class Admission:
    """Internal audit context captured by an existing authorized domain boundary.

    It is not a persisted permission or a browser token. Every canonical write
    and read must still execute the current original domain authorization.
    """

    case_id: str
    provider_id: str
    subject_id: str
    auth_epoch: str
    purpose: str
    case_revision: int
    evidence_version: int


class ScannerUnavailable(Exception):
    """Fixed internal state; never expose runtime paths or scanner diagnostics."""


class FileScanner(ABC):
    @property
    @abstractmethod
    def spec(self):
        """Return current exact ScannerSpec; no network, process or DB callbacks.

        Every engine/database/configuration change must change this immutable
        projection. Missing or unverifiable configuration raises ScannerUnavailable.
        """
        raise NotImplementedError

    @abstractmethod
    def scan(self, request):
        """Return one ScanVerdict for these exact bytes, without persisting effects.

        The controller bounds waiting and concurrency. A concrete subprocess
        adapter must separately enforce/terminate its own process deadline.
        """
        raise NotImplementedError
