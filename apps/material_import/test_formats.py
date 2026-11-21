import io
import json
import unittest
import zipfile
from hashlib import sha256

from . import formats


def archive(rows, files):
    members = {"records.json": json.dumps(rows, ensure_ascii=False).encode()}
    pins = []
    for path, filename, media_type, raw in files:
        members[path] = raw
        pins.append(
            {
                "path": path,
                "filename": filename,
                "media_type": media_type,
                "sha256": sha256(raw).hexdigest(),
                "size": len(raw),
            }
        )
    members["manifest.json"] = formats.canonical(
        {"schema": formats.SCHEMA, "synthetic": True, "records": "records.json", "files": pins}
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as bundle:
        for path, raw in members.items():
            bundle.writestr(path, raw)
    return output.getvalue()


class InputTests(unittest.TestCase):
    def test_csv_json_jsonl_preserve_actual_unicode_and_crlf_with_named_column_mapping(self):
        original = "  أَثَرٌ ـ ي ى\r\nسطر آخر  "
        row = {
            "_synthetic": True,
            "id": "alpha",
            "type": "BOOK",
            "name": original,
            "source": "عمل اصطناعي",
            "rev": "v1",
        }
        raw = json.dumps([row], ensure_ascii=False).encode()
        for filename, value in (
            ("rows.json", raw),
            ("rows.jsonl", json.dumps(row, ensure_ascii=False).encode()),
        ):
            parsed = formats.parse(value, filename)
            mapping = {key: "" for key in formats.FIELDS}
            mapping.update(
                external_id="id",
                kind="type",
                title="name",
                work_title="source",
                source_version="rev",
            )
            formats.validate_mapping(mapping, parsed)
            result = formats.mapped(
                parsed.rows[0], mapping, provenance="اصطناعي", rights_basis="اصطناعي"
            )
            self.assertEqual(result[3]["title"], original)
            self.assertEqual(result[0], "alpha")
        import csv

        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=list(row), lineterminator="\r\n")
        writer.writeheader()
        writer.writerow({**row, "_synthetic": "true"})
        self.assertEqual(
            formats.parse(output.getvalue().encode(), "source.csv").rows[0]["name"], original
        )

    def test_rejects_duplicate_keys_nontext_numeric_id_secrets_and_nonliteral_synthetic(self):
        specimens = [
            b'[{"_synthetic":true,"id":"a","id":"b"}]',
            b'[{"_synthetic":true,"id":12}]',
            b'[{"_synthetic":true,"password":"x"}]',
            b'[{"_synthetic":1,"id":"a"}]',
            b'[{"_synthetic":false,"id":"a"}]',
            b'[{"_synthetic":true,"approved":"yes"}]',
        ]
        for raw in specimens:
            with self.subTest(raw=raw), self.assertRaises(formats.ImportInputError):
                formats.parse(raw, "records.json")

    def test_zip_hashes_paths_no_hidden_extra_compression_or_symlinks(self):
        rows = [{"_synthetic": True, "id": "alpha"}]
        original = archive(rows, [("files/a.txt", "a.txt", "text/plain", b"synthetic")])
        parsed = formats.parse(original, "bundle.zip")
        self.assertEqual(parsed.files["files/a.txt"].raw, b"synthetic")
        with zipfile.ZipFile(io.BytesIO(original)) as source:
            contents = {name: source.read(name) for name in source.namelist()}
        for mode in ("tampered", "extra", "compressed", "symlink"):
            output = io.BytesIO()
            with zipfile.ZipFile(
                output,
                "w",
                compression=zipfile.ZIP_DEFLATED if mode == "compressed" else zipfile.ZIP_STORED,
            ) as target:
                for name, content in contents.items():
                    if mode == "tampered" and name == "files/a.txt":
                        content = b"different"
                    info = zipfile.ZipInfo(name)
                    info.compress_type = (
                        zipfile.ZIP_DEFLATED if mode == "compressed" else zipfile.ZIP_STORED
                    )
                    if mode == "symlink" and name == "files/a.txt":
                        info.external_attr = 0o120777 << 16
                    target.writestr(info, content)
                if mode == "extra":
                    target.writestr("../hidden.txt", b"hidden")
            with self.subTest(mode=mode), self.assertRaises(formats.ImportInputError):
                formats.parse(output.getvalue(), "bundle.zip")

    def test_mapping_only_declared_targets_and_source_columns_with_required_bindings(self):
        parsed = formats.parse(b'[{"_synthetic":true,"id":"a"}]', "records.json")
        mapping = formats.default_mapping(parsed)
        with self.assertRaises(formats.ImportInputError):
            formats.validate_mapping(mapping, parsed)
        mapping.update(
            external_id="id", kind="id", title="id", work_title="id", source_version="id"
        )
        formats.validate_mapping(mapping, parsed)
        for bad in ({**mapping, "approved": "id"}, {**mapping, "title": "unknown"}):
            with self.assertRaises(formats.ImportInputError):
                formats.validate_mapping(bad, parsed)
