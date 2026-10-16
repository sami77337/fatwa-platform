"""Synthetic stdout-only demo: python -m apps.reference_links.demo."""

import json
from dataclasses import asdict

from .bridge import BridgeConfig, EditionMap, HeadingMap, SourceIdentity, resolve_prepared_pointers
from .resolution import Heading, SnapshotCatalog


def fixtures():
    identity = SourceIdentity("synthetic-only", "622", "human-edition-A", "a" * 64, "b" * 64)
    config = BridgeConfig(EditionMap(identity, 41), (HeadingMap("source-X", "heading-Y", "row-Z", 73),))
    heading = Heading(41, 73, "كشاف القناع — مثال اصطناعي", "باب الطهارة", "الأول", 12,
                      ("كتاب الطهارة", "باب الطهارة"), "synthetic-only", "622", "b" * 64)
    return config, heading


def main():
    config, heading = fixtures()
    raw = json.dumps({"schema": "fatwa.prepared-intake.v1", "items": [
        {"external_id": "synthetic-1", "reference_links": [
            {"source_id": "source-X", "heading_id": "heading-Y"}]},
        {"external_id": "synthetic-2", "reference_links": [
            {"source_id": "41", "heading_id": "73"}]},
    ]}).encode()
    print(json.dumps([asdict(row) for row in resolve_prepared_pointers(
        raw, config, SnapshotCatalog((heading,)))], ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
