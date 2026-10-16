"""Actual loopback HTTP against an ephemeral WSGI server, without DB or mocks."""

from http.client import HTTPConnection
from threading import Thread
from wsgiref.simple_server import WSGIRequestHandler, make_server

from django.core.wsgi import get_wsgi_application
from django.test import SimpleTestCase


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass


class B5LoopbackHTTPTests(SimpleTestCase):
    databases = set()

    def test_actual_http_read_only_headers_and_denials(self):
        server = make_server("127.0.0.1", 0, get_wsgi_application(), handler_class=QuietHandler)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            probes = [("GET", "/healthz", 200), ("HEAD", "/healthz", 200),
                      ("GET", "/api/v1/fiqh/books?limit=0", 400),
                      ("GET", "/api/v1/private/cases", 404)]
            probes += [(method, route, 405)
                       for method in ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"]
                       for route in ["/healthz", "/api/v1/fiqh/books", "/missing"]]
            for method, route, expected in probes:
                with self.subTest(method=method, route=route):
                    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                    try:
                        connection.request(method, route, headers={"Origin": "https://foreign.invalid"})
                        response = connection.getresponse()
                        body = response.read()
                        self.assertEqual(response.status, expected)
                        csp = response.getheader("Content-Security-Policy")
                        for directive in ["default-src 'none'", "script-src 'self'",
                                          "frame-ancestors 'none'", "form-action 'self'"]:
                            self.assertIn(directive, csp)
                        self.assertNotIn("unsafe-inline", csp)
                        self.assertNotIn("unsafe-eval", csp)
                        self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
                        self.assertEqual(response.getheader("Cache-Control"), "no-store")
                        self.assertIsNone(response.getheader("Access-Control-Allow-Origin"))
                        self.assertIsNone(response.getheader("Set-Cookie"))
                        self.assertNotIn(b"Traceback", body)
                        if method == "HEAD":
                            self.assertEqual(body, b"")
                        if expected == 405:
                            self.assertEqual(response.getheader("Allow"), "GET, HEAD")
                    finally:
                        connection.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
