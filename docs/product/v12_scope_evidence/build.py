"""Deterministic source-to-evidence rendering. No network, DB or product mutation."""

import ast
import csv
import hashlib
import io
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SHA = "5aff9ba3cce35241b3ded27ed3428e0d4ecad768"
REPO = "https://github.com/sami77337/fatwa-platform"
STATES = {
    "COMPLETE": "مكتمل",
    "PARTIAL": "جزئي",
    "DECISION": "قرار",
    "NOT_IMPLEMENTED": "غير منفذ بالدليل المتاح",
    "OUT_OF_SCOPE": "خارج نطاق V1 الحالي",
}


def read(name):
    return json.loads((HERE / name).read_text())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pinned(path):
    return subprocess.check_output(["git", "show", f"{SHA}:{path}"], cwd=ROOT)


def reference(value):
    path, _, symbol = value.partition("#")
    raw = pinned(path)
    line, end = 1, len(raw.splitlines())
    if symbol:
        nodes = [
            n
            for n in ast.walk(ast.parse(raw))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and n.name == symbol
        ]
        if len(nodes) != 1:
            raise ValueError(f"non-unique or missing anchor: {value}")
        line, end = nodes[0].lineno, nodes[0].end_lineno
    return dict(
        path=path,
        symbol=symbol or None,
        line=line,
        end_line=end,
        sha=SHA,
        file_sha256=digest(raw),
        url=f"{REPO}/blob/{SHA}/{path}#L{line}-L{end}",
    )


def sources():
    pages = [read(f"sources/scope_read_{i}.json")["results"][0] for i in (1, 2)]
    assert [(p["start_line"], p["end_line"], p["has_more"]) for p in pages] == [
        (1, 1000, True),
        (1001, 1817, False),
    ]
    assert all(
        p["total_lines"] == 1817 and p["file_id"] == "file_000000005a9081f5806656498dcf4c40"
        for p in pages
    )
    a, b = [p["content"] for p in pages]
    owner = list(csv.reader(io.StringIO(a[3])))[4:]
    specs = list(csv.reader(io.StringIO(a[5] + "\n" + b[0])))[4:]
    assert len(owner) == 556 and all(len(row) == 13 for row in owner)
    assert [int(r[1]) for r in owner] == list(range(1, 557))
    assert len(specs) == len({r[1] for r in specs}) == 479
    return owner, specs


def decisions():
    src = read("sources/decision_log.json")
    text = src["content"]
    headers = list(
        re.finditer(r"^(?:\d{4}-\d{2}-\d{2}[^\r\n]*D-\d{3}|D-\d{3} —)[^\r\n]*", text, re.M)
    )
    counts = Counter()
    result = []
    for i, match in enumerate(headers):
        ident = re.search(r"D-\d{3}", match[0])[0]
        counts[ident] += 1
        body = text[match.start() : headers[i + 1].start() if i + 1 < len(headers) else len(text)]
        result.append(
            dict(
                original_id=ident,
                occurrence=counts[ident],
                source_header=match[0],
                text=body,
                text_sha256=digest(body.encode()),
                source_url=src["url"],
                source_modified=src["modified_time"],
            )
        )
    assert {d["original_id"] for d in result} == {f"D-{i:03}" for i in range(1, 73)}
    return result


def build():
    owner, specs = sources()
    spec_ids = {r[1] for r in specs}
    decs = decisions()
    dec_ids = {d["original_id"] for d in decs}
    assessment = read("assessments.json")
    runs = read("sources/p0_workflows.json")["workflow_runs"]
    run_ids = {r["id"] for r in runs}
    groups, links = [], defaultdict(list)
    for src in assessment["evidence_groups"]:
        group = dict(src)
        group["sha"] = SHA
        group["code"] = [reference(x) for x in src["code"]]
        group["tests"] = [reference(x) for x in src["tests"]]
        if src["workflow_run_id"]:
            assert src["workflow_run_id"] in run_ids
            group["launcher"] = reference(src["launcher"])
            group["run_url"] = f"{REPO}/actions/runs/{src['workflow_run_id']}"
            jobs = read(f"sources/jobs_{src['workflow_run_id']}.json")["jobs"]
            assert jobs and all(j["conclusion"] == "success" for j in jobs)
            group["execution_evidence"] = (
                "REMOTE_WORKFLOW_AND_JOB_SUCCESS; test-selector linkage inspected; no per-assertion log imported"
            )
        else:
            group["execution_evidence"] = "STATIC_ONLY; exact test execution not established here"
        groups.append(group)
        for point in group["owner_points"]:
            assert 1 <= point <= 556
            links[point].append(group["id"])
    assert len(groups) == len({g["id"] for g in groups})
    matrix = []
    for row in owner:
        (
            index,
            ident,
            original,
            title,
            documentary,
            scope,
            direct,
            decision,
            examples,
            paragraph,
            reverse,
            units,
            receipt,
        ) = row
        number = int(ident)
        direct_ids = re.findall(r"SPEC-U\d{2}-\d{3}", direct)
        reverse_ids = re.findall(r"SPEC-U\d{2}-\d{3}", reverse)
        decision_ids = re.findall(r"D-\d{3}", decision)
        assert set(direct_ids + reverse_ids) <= spec_ids
        assert set(decision_ids) <= dec_ids
        status = "PARTIAL" if links[number] else "NOT_IMPLEMENTED"
        reason = (
            "دليل محدود مرتبط أدناه؛ لا يغطي النص كله أو التشغيل الحقيقي."
            if links[number]
            else assessment["unimplemented_default"]
        )
        if scope in ("خاص بمكتبة الحديث المؤجلة", "التصميم البصري النهائي مؤجل"):
            status = "OUT_OF_SCOPE"
            reason = (
                "تأجيل موثق في D-072 أو D-070؛ الأصل محفوظ، وليس إنجازًا ولا حذفًا دائمًا من الرؤية."
            )
        elif scope in (
            "الوظيفة مرصودة، وعقد U03 التفصيلي معلق",
            "مبدأ دور أو قيد، والتفعيل بحسب السياسة",
            "تفصيل سجله المالك مفتوحًا؛ يتطلب دليل حسم",
            "قرار أصلي عولج لاحقًا",
            "قاعدة نطاق أصلية مع استثناءات لاحقة",
        ):
            status = "DECISION"
            reason = (
                "قرار نطاق/سياسة مطلوب أو حُسم جزئيًا لاحقًا؛ الشواهد التقنية لا تفعّل U03 ولا تمنح قبولًا. "
                "ارجع إلى معاملة النطاق والقرارات الأصلية أدناه."
            )
        if number in (67, 68):
            status = "DECISION"
            reason = "التعيين التخصصي الآلي غير معتمد وفق D-041؛ يبقى مغلقًا."
        if str(number) in assessment["explicit_gaps"]:
            reason += " " + assessment["explicit_gaps"][str(number)]
        matrix.append(
            dict(
                original_id=ident,
                original_text=original,
                original_heading=title,
                source_locator={"sheet": "نقاط المالك", "parsed_index": int(index)},
                source_word_paragraph_unverified=paragraph,
                source_examples=examples,
                source_documentary_match=documentary,
                source_scope_treatment=scope,
                source_acceptance_receipt=receipt,
                direct_spec_ids=direct_ids,
                additional_reverse_spec_ids=reverse_ids,
                decision_ids=decision_ids,
                unit_refs=units,
                engineering_status=status,
                status_ar=STATES[status],
                rationale=reason,
                evidence_ids=links[number],
                evidence_sha=SHA,
                acceptance="HOLD",
                assessed_p1=False,
            )
        )
    for d in decs:
        d["owner_points"] = [
            r["original_id"] for r in matrix if d["original_id"] in r["decision_ids"]
        ]
        d["evidence_ids"] = sorted(
            {g for r in matrix if r["original_id"] in d["owner_points"] for g in r["evidence_ids"]}
        )
        d["evidence_relation"] = "INDIRECT_VIA_WORKBOOK_POINTS; not decision-wide completion"
        d["status"] = "DECISION"
        d["acceptance"] = "HOLD"
    clauses = [
        dict(
            original_id=r[1],
            unit=r[2],
            title=r[3],
            original_text=r[4],
            source_scope_treatment=r[5],
            owner_points_source=r[6],
            source_spec_lines_unverified=r[7],
            parsed_index=int(r[0]),
            acceptance="HOLD",
        )
        for r in specs
    ]
    output = {
        "matrix.json": matrix,
        "specifications.json": clauses,
        "decisions.json": decs,
        "evidence.json": groups,
    }
    products = {
        name: json.dumps(v, ensure_ascii=False, indent=2) + "\n" for name, v in output.items()
    }
    csvout = io.StringIO(newline="")
    writer = csv.writer(csvout, lineterminator="\n")
    writer.writerow(
        [
            "original_id",
            "original_text",
            "status",
            "rationale",
            "source_scope_treatment",
            "direct_spec_ids",
            "additional_reverse_spec_ids",
            "decision_ids",
            "evidence_ids",
            "evidence_sha",
            "acceptance",
        ]
    )
    for r in matrix:
        writer.writerow(
            [
                r["original_id"],
                r["original_text"],
                r["status_ar"],
                r["rationale"],
                r["source_scope_treatment"],
                ";".join(r["direct_spec_ids"]),
                ";".join(r["additional_reverse_spec_ids"]),
                ";".join(r["decision_ids"]),
                ";".join(r["evidence_ids"]),
                SHA,
                "HOLD",
            ]
        )
    products["matrix.csv"] = csvout.getvalue()
    md = [
        "# مصفوفة أدلة V12 P2",
        "",
        f"الرأس: `{SHA}`. جميع الصفوف ACCEPTANCE_HOLD؛ لا نسبة إنجاز مشتقة.",
        "",
        "التصنيفات تصف الأدلة الهندسية عند P0 فقط. غير منفذ بالدليل المتاح لا يجزم بغياب كل كود متعلق.",
        "المطابقة الوثائقية في Excel محفوظة مستقلة؛ لا تتحول تلقائيًا إلى مكتمل. [المنهج والحدود](README.md).",
        "",
    ]

    def esc(t):
        return str(t).replace("|", "\\|").replace("\n", "<br>")

    heading = None
    for r in matrix:
        if heading != r["original_heading"]:
            heading = r["original_heading"]
            md += [
                "",
                f"## {heading}",
                "",
                "| الرقم الأصلي والنص | الحالة | بنود/قرارات المصدر | الدليل | المتبقي |",
                "|---|---|---|---|---|",
            ]
        refs = ", ".join(
            r["direct_spec_ids"] + r["additional_reverse_spec_ids"] + r["decision_ids"]
        )
        ev = (
            ", ".join(f"[{g}](EVIDENCE.md#{g})" for g in r["evidence_ids"])
            or "لا شاهد تنفيذ مطابق مثبت"
        )
        md.append(
            "| "
            + " | ".join(
                [
                    esc(r["original_id"] + " — " + r["original_text"]),
                    r["status_ar"],
                    refs,
                    ev,
                    esc(r["rationale"]),
                ]
            )
            + " |"
        )
    products["MATRIX.md"] = "\n".join(md) + "\n"
    emd = [
        "# شواهد محددة عند P0",
        "",
        "كل مجموعة تثبت الجزء المكتوب فقط؛ اشتراك نقاط في شاهد لا يجعلها متكافئة.",
    ]
    for g in groups:
        emd += [
            "",
            f"## {g['id']}",
            "",
            g["bounded_claim"],
            "",
            "**الحد:** " + g["remaining"],
            "",
            "نقاط: " + ", ".join(map(str, g["owner_points"])),
            "",
        ]
        for kind in ("code", "tests"):
            emd += [
                f"- {kind}: [{e['path']} — {e['symbol'] or 'file'}]({e['url']})" for e in g[kind]
            ]
        emd += ["", g["execution_evidence"]]
        if g.get("run_url"):
            emd += [f"[تشغيل SHA المثبت]({g['run_url']}) · [محدد التشغيل]({g['launcher']['url']})"]
    products["EVIDENCE.md"] = "\n".join(emd) + "\n"
    products["summary.json"] = (
        json.dumps(
            dict(
                evidence_sha=SHA,
                owner_points=len(matrix),
                specification_clauses=len(clauses),
                unique_decision_ids=len(dec_ids),
                decision_occurrences=len(decs),
                status_counts={
                    state: Counter(r["engineering_status"] for r in matrix)[state]
                    for state in STATES
                },
                acceptance="HOLD",
                p1_evidence_included=False,
                percentage=None,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    return products


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    products = build()
    if args.check:
        for name, text in products.items():
            assert (HERE / name).read_bytes() == text.encode(), f"generated output drift: {name}"
        print(
            "PASS: deterministic source fidelity, 556 points, 479 clauses, decision occurrences, pinned code/test references and output drift"
        )
    else:
        for name, text in products.items():
            (HERE / name).write_bytes(text.encode())
        print("Wrote", len(products), "derived artifacts")
