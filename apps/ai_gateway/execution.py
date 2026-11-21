"""Bound request waiting and concurrency without pretending to kill Python code."""

from queue import Empty, Queue
from threading import BoundedSemaphore, Event, Thread

# One slot for the process, not one per provider or request. A hung adapter keeps
# it until it exits, so timeout/retry/config changes cannot accumulate workers.
SLOT = BoundedSemaphore(1)


def invoke(provider, request, *, timeout):
    if not SLOT.acquire(blocking=False):
        return False, None
    abandoned = Event()
    result = Queue(maxsize=1)

    def work():
        try:
            try:
                value = (True, provider.generate(request))
            except BaseException:
                # Do not log raw adapter errors or let a thread exception hook
                # print context. The controller records only a fixed status.
                value = (False, None)
            if not abandoned.is_set():
                result.put_nowait(value)
        finally:
            SLOT.release()

    worker = Thread(target=work, name="fatwa-citation-provider", daemon=True)
    try:
        worker.start()
    except Exception:
        SLOT.release()
        return False, None
    try:
        return result.get(timeout=timeout)
    except Empty:
        # The worker has no completion callback, model/service handle or DB
        # persistence path. A late return is discarded, never handed to a retry.
        abandoned.set()
        return False, None
