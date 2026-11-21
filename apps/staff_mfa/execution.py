"""Bound waiting for a fresh primary verifier, outside any database transaction."""

from queue import Empty, Queue
from threading import BoundedSemaphore, Event, Thread

SLOT = BoundedSemaphore(1)


def primary(provider, credential, challenge):
    if not SLOT.acquire(blocking=False):
        return None
    abandoned, result = Event(), Queue(maxsize=1)

    def work():
        try:
            try:
                value = provider.authenticate_primary(credential, challenge=challenge)
            except BaseException:
                value = None
            if not abandoned.is_set():
                result.put_nowait(value)
        finally:
            SLOT.release()

    try:
        Thread(target=work, name="fatwa-mfa-primary-verifier", daemon=True).start()
    except Exception:
        SLOT.release()
        return None
    try:
        return result.get(timeout=20)
    except Empty:
        abandoned.set()
        return None
