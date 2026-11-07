"""Read-only verifier for the pinned October 10 owner-scope reconciliation."""
import argparse
from collections import Counter
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile


OWNER = "542.docx"
REGISTRY = "requirements.jsonl"
SPEC = "PRODUCT_SPEC.txt"
MANIFEST = "INDEPENDENT_RECONCILIATION_DELIVERY_MANIFEST.json"
FORWARD = "ORIGINAL_556_TO_479_SEMANTIC_VERIFIED.json"
REVERSE = "CURRENT_479_TO_556_REVERSE_SEMANTIC_VERIFIED.json"
PINS = {
    OWNER: "436751386501bf53c6a7f39bb21ee1eec85e6d34f3326fe528cf38e6bc6c80ff",
    REGISTRY: "48024cb9c1693d64c6e2c22928748f123c819ba37428016ca7cd8a26e2d175fb",
    SPEC: "5b810ace8c846fb1437165c36a2884f3b0134b3b3c51149290e125f95d28b8c7",
    MANIFEST: "3d75c10be8e5b312e0b669779d6b55977e8e7ed6fee32adb922071dd320d3a52",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pinned_read(root, name, expected):
    path = (root / name).resolve(strict=True)
    require(path.is_relative_to(root) and path.is_file(), "Invalid input path")
    # All six reviewed files are smaller than four MiB.
    with path.open("rb") as stream:
        data = stream.read(4 * 1024 * 1024 + 1)
    require(len(data) <= 4 * 1024 * 1024 and digest(data) == expected, "Source pin mismatch: " + name)
    return data


def owner_paragraphs(data):
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with ZipFile(BytesIO(data)) as archive:
        body = ET.fromstring(archive.read("word/document.xml")).find(ns + "body")
    return {i: "".join(t.text or "" for t in p.iter(ns + "t")).strip()
            for i, p in enumerate(body.findall(ns + "p"), 1)}


def audit_records(paragraphs, spec_lines, clauses, forward, reverse):
    registry = {row["id"]: row for row in clauses}
    require(len(clauses) == len(registry) == len(reverse) == 479, "Expected 479 unique registry clauses")
    require({row["spec_id"] for row in reverse} == set(registry), "Missing or duplicate reverse clause")

    numbered = {i for i, text in paragraphs.items() if re.fullmatch(r"\d+[.)]\s*.+", text)}
    traced = {row["docx_paragraph_1based"] for row in forward}
    require(len(forward) == len(traced) == 556 and traced == numbered, "Missing or duplicate owner paragraph")
    points = {}
    dispositions = Counter()
    examples = set()
    links = set()
    for number, row in enumerate(forward, 1):
        index, text = row["docx_paragraph_1based"], row["exact_text"]
        require(row["point_no"] == number and row["source_group"] ==
                ("ORIGINAL_542" if number <= 542 else "D062_APPENDIX_14"), "Owner numbering or group mismatch")
        match = re.fullmatch(r"(\d+)[.)]\s*(.+)", paragraphs[index])
        require(row["review_performed"] is True and row["raw_numbered_paragraph"] == paragraphs[index] and
                match is not None and match.groups() == (str(number), text) and
                digest(text.encode()) == row["source_text_sha256"], "Owner text or paragraph mismatch")
        for example in row["continuation_examples"]:
            pos = example["paragraph_1based"]
            require(pos not in examples and pos not in numbered and paragraphs.get(pos) == example["exact_text"],
                    "Invalid continuation paragraph")
            examples.add(pos)
        points[number] = row
        dispositions[row["reviewer_disposition"]] += 1
        for evidence in row["spec_associations"]:
            key = evidence["spec_id"]
            require(key in registry and evidence["exact_quote"] == registry[key]["verbatim"], "Invalid forward clause")
            links.add((number, key, "SELECTED_FORWARD_EVIDENCE"))
        for key in row["additional_reverse_refinement_refs"]:
            links.add((number, key, "SEMANTIC_ANTECEDENT_OR_ALTERNATIVE_SUPPORT"))

    reverse_links = set()
    for row in reverse:
        key = row["spec_id"]
        original = registry[key]
        first, last = original["start_line"], original["end_line"]
        quote = "\n".join(spec_lines[first - 1:last])
        evidence = row["source_evidence"]
        require(1 <= first <= last <= len(spec_lines) and row["review_performed"] is True and
                (first, last) == (evidence["source_line_start"], evidence["source_line_end"]) and
                quote == original["verbatim"] == evidence["exact_quote"] and
                digest(quote.encode()) == original["text_sha256"] == evidence["quote_sha256_utf8"],
                "Registry source span or text mismatch")
        for origin in row["original_point_origins"]:
            number = origin["point_no"]
            require(number in points and origin["docx_paragraph_1based"] == points[number]["docx_paragraph_1based"]
                    and origin["exact_quote"] == points[number]["exact_text"], "Reverse origin mismatch")
            reverse_links.add((number, key, origin["relation"]))
    require(links == reverse_links, "Forward/reverse relationship mismatch")
    return {"classification": "DOCUMENTARY_SCOPE_ONLY", "numbered_owner_paragraphs": len(traced),
            "source_groups": dict(Counter(r["source_group"] for r in forward)), "additional_examples": len(examples),
            "secondary_registry_clauses": len(registry), "documentary_dispositions": dict(dispositions),
            "unique_links_by_relation": dict(Counter(edge[2] for edge in links)),
            "implementation": "NOT_EVALUATED", "product_tests": "NOT_RUN", "owner_or_gate_decision": "NOT_EVALUATED"}


def verify(root):
    root = root.resolve(strict=True)
    data = {name: pinned_read(root, name, pin) for name, pin in PINS.items()}
    published = {item["filename"]: item for item in json.loads(data[MANIFEST])["artifacts"]}
    reports = []
    for name in (FORWARD, REVERSE):
        item = published[name]
        raw = pinned_read(root, name, item["sha256"])
        require(len(raw) == item["byte_size"], "Report size mismatch")
        reports.append(json.loads(raw)["records"])
    clauses = [json.loads(line) for line in data[REGISTRY].splitlines()]
    return audit_records(owner_paragraphs(data[OWNER]), data[SPEC].decode("utf-8-sig").splitlines(), clauses, *reports)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path, help="Directory containing all six original files")
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.source_root), indent=2, sort_keys=True))
    except OSError:
        parser.exit(1, "Owner scope not verified: a required original could not be read.\n")
    except ValueError as exc:
        parser.exit(1, f"Owner scope not verified: {exc}\n")
