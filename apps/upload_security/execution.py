"""One bounded waiting slot; a timed-out adapter keeps it until its worker exits."""

from queue import Empty, Queue
from threading import BoundedSemaphore, Event, Thread

SLOT = BoundedSemaphore(1)


def invoke(scanner, request, timeout):
    if not SLOT.acquire(blocking=False):
        return "BUSY", None
    abandoned = Event()
    result = Queue(maxsize=1)

    def work():
        try:
            try:
                answer = ("RETURNED", scanner.scan(request))
            except BaseException:
                answer = ("FAILED", None)
            if not abandoned.is_set():
                result.put_nowait(answer)
        finally:
            SLOT.release()

    worker = Thread(target=work, name="fatwa-upload-scanner", daemon=True)
    try:
        worker.start()
    except Exception:
        SLOT.release()
        return "FAILED", None
    try:
        return result.get(timeout=timeout)
    except Empty:
        abandoned.set()
        return "TIMED_OUT", None
