"""Append reviewed P1 evidence; never rewrite P0 pins or promote classifications."""

from collections import defaultdict

P1_SHA = "0055a5ab05c6dbe6d41a528666666f9db07f2fee"
P1_RUN = 44208238581
JOBS = (134479648225, 134479647759)


def apply(matrix, groups, *, read, reference, baseline_sha):
    assessment = read("p1_assessments.json")
    assert assessment["head_sha"] == P1_SHA and assessment["base_sha"] == baseline_sha
    run = next(r for r in read("sources/p1_workflows.json")["workflow_runs"] if r["id"] == P1_RUN)
    assert run["status"] == "completed" and run["conclusion"] == "success"
    jobs = read(f"sources/p1_jobs_{P1_RUN}.json")["jobs"]
    assert {j["id"] for j in jobs} == set(JOBS)
    assert all(j["status"] == "completed" and j["conclusion"] == "success" for j in jobs)
    excerpts = []
    for job_id in JOBS:
        excerpt = read(f"sources/p1_job_{job_id}_excerpt.json")
        assert excerpt["head_sha"] == P1_SHA and excerpt["run_id"] == P1_RUN
        text = "\n".join(excerpt["lines"])
        assert "TESTED_SHA=" + P1_SHA in text
        for marker in (
            "Ran 54 tests",
            "Ran 6 tests",
            "AFFECTED EXIT=0",
            "BROWSER-RECOVERY EXIT=0",
            "FATWA_BROWSER_SANDBOX: 1",
        ):
            assert marker in text, (job_id, marker)
        excerpts.append(text)
    p0_ids = {g["id"] for g in groups}
    by_point = defaultdict(list)
    for source in assessment["evidence_groups"]:
        assert source["workflow_run_id"] == P1_RUN
        assert source["supersedes_evidence_ids"] == []  # Append, do not erase P0.
        assert set(source["extends_evidence_ids"]) <= p0_ids
        assert source["assessment_effect"] == "EVIDENCE_ADDED_NO_STATUS_UPGRADE"
        assert all(1 <= n <= 556 for n in source["owner_points"])
        group = dict(source, sha=P1_SHA)
        group["code"] = [reference(v, sha=P1_SHA) for v in source["code"]]
        group["tests"] = [reference(v, sha=P1_SHA) for v in source["tests"]]
        for test in group["tests"]:
            assert test["symbol"]
            assert all(
                test["symbol"] + " (" in text
                and any(
                    test["symbol"] + " (" in line and line.endswith(" ... ok")
                    for line in text.splitlines()
                )
                for text in excerpts
            ), test["symbol"]
        group["launcher"] = reference(source["launcher"], sha=P1_SHA)
        group["run_url"] = f"https://github.com/sami77337/fatwa-platform/actions/runs/{P1_RUN}"
        group["execution_evidence"] = (
            "EXACT_HEAD_JOB_LOG_TEST_PASS_BOTH_MAJORS; source/test assertions inspected; artifact JSON not imported"
        )
        group["job_ids"] = list(JOBS)
        groups.append(group)
        for point in source["owner_points"]:
            by_point[point].append(group["id"])
    assert len(groups) == len({g["id"] for g in groups})
    for row in matrix:
        matched = by_point[int(row["original_id"])]
        row["p1_evidence_ids"] = matched
        row["evidence_shas"] = [baseline_sha] + ([P1_SHA] if matched else [])
        row["p0_engineering_status"] = row["engineering_status"]
        row["assessed_p1"] = bool(matched)
        if matched:
            row["evidence_ids"] = [*row["evidence_ids"], *matched]
            row["rationale"] += (
                " أضيف شاهد P1 محدد عند 0055a5ab؛ تبقى الحالة كما هي لحدود النص والبيئة الاصطناعية."
            )
            row["p1_assessment_effect"] = "EVIDENCE_ADDED_NO_STATUS_UPGRADE"
    return by_point
