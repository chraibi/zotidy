"""Command line entry point.

    zotidy libraries
    zotidy report --library 20 [--check duplicate_pdf --check duplicate_doi] [--json] [--limit N]
    zotidy report --library 20 --out report.md      # full report as Markdown (or .json)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import checks, db


def cmd_libraries(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    for lib_id, kind, name in db.libraries(conn):
        n = conn.execute("SELECT count(*) FROM items WHERE libraryID = ?", (lib_id,)).fetchone()[0]
        print(f"{lib_id:>4}  {kind:<5}  {n:>6}  {name}")
    return 0


def findings_json(findings: list[checks.Finding]) -> list[dict]:
    return [
        {
            "check": f.check,
            "reason": f.reason,
            "items": [
                {"key": i.key, "type": i.item_type, "title": i.title,
                 "pdfs": [a.key for a in i.pdfs]}
                for i in f.items
            ],
        }
        for f in findings
    ]


def findings_markdown(library: int, n_items: int, findings: list[checks.Finding]) -> str:
    by_check: dict[str, list[checks.Finding]] = {}
    for f in findings:
        by_check.setdefault(f.check, []).append(f)
    lines = [f"# zotidy report, library {library}", "", f"{n_items} items scanned.", "",
             "| check | findings | items |", "|---|---|---|"]
    for name, group in by_check.items():
        lines.append(f"| {name} | {len(group)} | {sum(len(f.items) for f in group)} |")
    for name, group in by_check.items():
        lines += ["", f"## {name}", ""]
        for f in group:
            lines.append(f"- **{f.reason}**")
            for it in f.items:
                lines.append(f"  - `{it.key}` {it.label()}")
    return "\n".join(lines) + "\n"


def print_findings(library: int, n_items: int, findings: list[checks.Finding], limit: int) -> None:
    print(f"library {library}: {n_items} items")
    by_check: dict[str, list[checks.Finding]] = {}
    for f in findings:
        by_check.setdefault(f.check, []).append(f)
    for name, group in by_check.items():
        total = sum(len(f.items) for f in group)
        print(f"\n== {name}: {len(group)} findings, {total} items")
        for f in group[:limit]:
            print(f"  [{f.reason}]")
            for it in f.items:
                print(f"     {it.key}  {it.label()}")
        if len(group) > limit:
            print(f"  ... {len(group) - limit} more (raise --limit or use --out)")


def cmd_report(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    items = db.load_items(conn, args.library)
    findings = checks.run(items, args.check or None)

    if args.out:
        if args.out.suffix == ".json":
            args.out.write_text(json.dumps(findings_json(findings), indent=1, ensure_ascii=False))
        else:
            args.out.write_text(findings_markdown(args.library, len(items), findings))
        print(f"wrote {args.out} ({len(findings)} findings)")
        return 0
    if args.json:
        json.dump(findings_json(findings), sys.stdout, indent=1, ensure_ascii=False)
        return 0
    print_findings(args.library, len(items), findings, args.limit)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="zotidy", description=__doc__)
    p.add_argument("--db", type=Path, default=db.DEFAULT_DB, help="path to zotero.sqlite")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("libraries", help="list libraries with item counts").set_defaults(func=cmd_libraries)

    r = sub.add_parser("report", help="run checks on one library")
    r.add_argument("--library", type=int, required=True, help="libraryID from `zotidy libraries`")
    r.add_argument("--check", action="append", choices=list(checks.ALL_CHECKS),
                   help="run only this check (repeatable)")
    r.add_argument("--json", action="store_true", help="machine readable output")
    r.add_argument("--limit", type=int, default=20, help="findings shown per check")
    r.add_argument("--out", type=Path, help="write the full report to this file (.md or .json)")
    r.set_defaults(func=cmd_report)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
