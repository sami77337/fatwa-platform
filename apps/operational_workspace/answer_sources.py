"""Retain canonical citation/media vetoes through the last operational callback."""

from contextlib import contextmanager

from apps.casework import services as cases


class SourceAdapter:
    def __init__(self, bundle):
        self.bundle = bundle

    def callbacks(self):
        self.bundle.callbacks()

    def external_reads(self):
        self.bundle.verify_bytes()

    def final_pins(self):
        self.bundle.final_pins()


@contextmanager
def retain(guard):
    with cases._answer_use_boundary() as bundle:
        guard.adapters.append(SourceAdapter(bundle))
        yield
