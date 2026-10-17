"""Synthetic E3 lookup measurement; run with the desired checkout on PYTHONPATH.

Not a latency assertion or a real-source benchmark. No database or network.
"""

import cProfile
import hashlib
import json
from pathlib import Path
from statistics import median
from time import perf_counter
from dataclasses import replace

import apps.reference_links.bridge as bridge
from apps.reference_links.demo import fixtures
from apps.reference_links.resolution import SnapshotCatalog


config, heading = fixtures()
config = replace(config, headings=tuple(
    bridge.HeadingMap("s", f"h{i}", f"c{i}", i + 1) for i in range(20_000)
))
catalog = SnapshotCatalog(tuple(replace(heading, source_row_id=i + 1) for i in range(100)))
raw = json.dumps({"schema": "fatwa.prepared-intake.v1", "items": [
    {"external_id": f"r{r}", "reference_links": [
        {"source_id": "s", "heading_id": f"h{i}"} for i in range(100)
    ]} for r in range(10)
]}).encode()
durations = []
for _ in range(10):
    start = perf_counter()
    results = bridge.resolve_prepared_pointers(raw, config, catalog)
    durations.append((perf_counter() - start) * 1000)
    assert all(p.status.value == "verified" for r in results for p in r.reference_links)
profile = cProfile.Profile()
profile.runcall(bridge.resolve_prepared_pointers, raw, config, catalog)
scans = sum(s.callcount for s in profile.getstats()
            if isinstance(s.code, str) and "'count' of 'list'" in s.code)
print(json.dumps({
    "bridge_sha256": hashlib.sha256(Path(bridge.__file__).read_bytes()).hexdigest(),
    "input_bytes": len(raw), "mappings": len(config.headings), "rows": 10,
    "references_per_row": 100, "median_ms_10_runs": round(median(durations), 3),
    "per_reference_full_list_count_calls": scans,
}, sort_keys=True))
