"""Actual current library sources; no external dataset or provider is impersonated."""

from apps.research_library.test_support import FEATURES as LIBRARY_FEATURES
from apps.research_library.test_support import LibraryFixture, payload

FEATURES = {**LIBRARY_FEATURES, "FATWA_MATERIAL_API_ENABLED": True,
            "MIDDLEWARE": ["apps.material_api.middleware.MaterialAPIResponses", *LIBRARY_FEATURES["MIDDLEWARE"]]}
BASE = "/library-preview/api/v1/materials/"
TEXT = "نص أصلي اصطناعي محفوظ\r\n  بايتاته تبقى كما هي  \n".encode()


class APIFixture(LibraryFixture):
    def source(self, **changes):
        return self.release(self.write(payload=payload(title="قراءة اصطناعية للمطور", recorded_text="نص متاح للقراءة وفق الإذن"),
            file_bytes=TEXT, filename="private-source-name.txt", media_type="text/plain"), **changes)

    def url(self, row):
        return BASE + row["public_id"] + "/versions/" + str(row["number"]) + "/"
