"""Required PR51 integration hooks; run explicitly once E2 is assembled."""
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

from .live_server import SyntheticLiveServerTestCase
from .support import require_disposable_database

require_disposable_database()


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a" and "href" in attributes:
            self.hrefs.append(attributes["href"])


class ReviewBatchIntegrationTests(SyntheticLiveServerTestCase):
    base = "/dev/editorial-preview/pipeline"

    def get(self, suffix):
        with urlopen(self.live_server_url + self.base + suffix, timeout=5) as response:
            self.assertEqual(response.status, 200)
            return response.read().decode("utf-8")

    def test_same_external_id_is_isolated_by_allowlisted_batch(self):
        default = self.get("/SYN-P01?batch=default")
        mixed = self.get("/SYN-P01?batch=mixed")
        self.assertIn("دفعة الاستلام الأساسية", default)
        self.assertIn("دفعة متنوعة", mixed)
        self.assertIn("  سؤال اصطناعي في الطهارة للمراجعة فقط  ", default)
        self.assertIn("  سؤالٌ اصطناعيٌّ آخر\tللمراجعة\nفقط  ", mixed)
        self.assertNotIn("سؤال اصطناعي في الطهارة للمراجعة فقط", mixed)

    def test_batch_filter_page_detail_and_return_state_use_real_links(self):
        params = {"batch": ["mixed"], "status": ["blocked-invalid"], "issue": ["invalid_input"],
                  "page_size": ["1"], "page": ["2"], "q": ["اصطناعي"]}
        # urlopen needs ASCII request targets. Use the actual encoded browser URL.
        from urllib.parse import urlencode
        query = "?" + urlencode({key: value[0] for key, value in params.items()})
        html = self.get(query)
        self.assertIn('id="batch"', html)
        self.assertIn("SYN-M03", html)
        links = Links()
        links.feed(html)
        detail = next(link for link in links.hrefs if urlsplit(link).path == self.base + "/SYN-M03")
        self.assertEqual(parse_qs(urlsplit(detail).query), params)
        detail_html = self.get(detail.removeprefix(self.base))
        returned = Links()
        returned.feed(detail_html)
        back = next(link for link in returned.hrefs if urlsplit(link).path == self.base
                    and parse_qs(urlsplit(link).query) == params)
        self.assertIn("SYN-M03", self.get(back.removeprefix(self.base)))

    def test_unallowlisted_batch_and_write_are_rejected(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.live_server_url + self.base + "?batch=not-allowlisted", timeout=5)
        self.assertEqual(caught.exception.code, 400)
        from urllib.request import Request
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(self.live_server_url + self.base + "?batch=mixed", data=b""), timeout=5)
        self.assertEqual(caught.exception.code, 405)
