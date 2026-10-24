"""Real Django middleware/templates/services, with database access forbidden."""

import os
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

from django.core.handlers.wsgi import WSGIHandler
from django.test import SimpleTestCase


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass


def run_browser(origin, scope):
    return subprocess.run(
        ["node", str(Path(__file__).with_name("browser.mjs")), origin, scope],
        env=os.environ.copy(),
        check=False,
        timeout=240,
    ).returncode


@contextmanager
def editorial_server():
    with make_server("127.0.0.1", 0, WSGIHandler(), handler_class=QuietHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join(timeout=5)


class EditorialBrowserTests(SimpleTestCase):
    def test_connected_synthetic_editorial_browser(self):
        # SimpleTestCase also forbids opening a DB connection in the WSGI thread.
        with editorial_server() as origin:
            result = run_browser(origin, "editorial")
            self.assertEqual(result, 0, "Read fastbuild editorial report: FAIL or NOT_RUN")
