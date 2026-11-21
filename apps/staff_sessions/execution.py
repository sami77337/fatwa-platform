"""Bound waiting and concurrency; a timed-out verifier is never reused or killed."""

from queue import Empty, Queue
from threading import BoundedSemaphore, Event, Thread

SLOT = BoundedSemaphore(1)


def invoke(provider, credential, *, challenge, timeout):
    if not SLOT.acquire(blocking=False):
        return False, None
    abandoned, result = Event(), Queue(maxsize=1)

    def work():
        try:
            try:
                value = (True, provider.authenticate_fresh(credential, challenge=challenge))
            except BaseException:
                value = (False, None)
            if not abandoned.is_set():
                result.put_nowait(value)
        finally:
            # No persistence callback is installed. Trusted adapters that use a
            # directory connection must finish their own connection lifecycle.
            SLOT.release()

    worker = Thread(target=work, name="fatwa-session-fresh-verifier", daemon=True)
    try:
        worker.start()
    except Exception:
        SLOT.release()
        return False, None
    try:
        return result.get(timeout=timeout)
    except Empty:
        abandoned.set()
        return False, None
