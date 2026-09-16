"""Command line entry point.

    zotidy libraries
    zotidy report --library 20 [--check duplicate_pdf --check duplicate_doi] [--json] [--limit N]
    zotidy report --library 20 --out report.md      # full report as Markdown (or .json)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
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


def resolve_short_doi(short: str) -> str:
    """Return the full DOI behind a shortDOI via the doi.org handle API, or "" if unknown."""
    url = f"https://doi.org/api/handles/{urllib.parse.quote(short)}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.load(resp)
    for v in data.get("values", []):
        if v.get("type") == "HS_ALIAS":
            return v["data"]["value"].lower()
    return ""


def cmd_resolve(args: argparse.Namespace) -> int:
    """Map every shortDOI in a library to its full DOI; writes CSV, never touches the database."""
    items = db.load_items(db.connect(args.db), args.library)
    short = [i for f in checks.short_dois(items) for i in f.items]
    rows = []
    for n, i in enumerate(short, 1):
        try:
            full = resolve_short_doi(i.doi)
        except (urllib.error.URLError, OSError) as e:
            full = ""
            print(f"{i.key}: {e}", file=sys.stderr)
        rows.append((i.key, i.doi, full, i.label()))
        print(f"\r{n}/{len(short)}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    with args.out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["key", "short_doi", "doi", "item"])
        w.writerows(rows)
    print(f"wrote {args.out} ({sum(1 for r in rows if r[2])}/{len(rows)} resolved)")
    return 0


API = "https://api.zotero.org"


def api_prefix(conn, library_id: int) -> str:
    gid = db.group_id(conn, library_id)
    if gid is not None:
        return f"{API}/groups/{gid}"
    uid = os.environ.get("ZOTERO_USER_ID")
    if not uid:
        sys.exit("set ZOTERO_USER_ID for the user library (see zotero.org/settings/keys)")
    return f"{API}/users/{uid}"


def api_request(method: str, url: str, key: str, body: dict | None = None, version: int | None = None):
    headers = {"Zotero-API-Key": key, "Zotero-API-Version": "3"}
    if version is not None:
        headers["If-Unmodified-Since-Version"] = str(version)
    data = json.dumps(body).encode() if body is not None else None
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def cmd_apply_dois(args: argparse.Namespace) -> int:
    """Write the full DOI from a `resolve` CSV into each item via the Zotero Web API."""
    key = os.environ.get("ZOTERO_API_KEY")
    if not key and not args.dry_run:
        sys.exit("set ZOTERO_API_KEY (write access to the library) or use --dry-run")
    with args.csv.open(newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r["doi"]]
    prefix = api_prefix(db.connect(args.db), args.library)
    print(f"{len(rows)} items -> {prefix}" + (" (dry run)" if args.dry_run else ""))
    if not args.dry_run and not args.yes and not confirm(len(rows), prefix):
        print("cancelled, nothing written")
        return 1
    done = 0
    for r in rows:
        print(f"  {r['key']}  {r['short_doi']} -> {r['doi']}")
        if args.dry_run:
            continue
        done += _patch_doi(prefix, key, r["key"], r["doi"])
    if not args.dry_run:
        print(f"updated {done}/{len(rows)}; sync Zotero to see the changes locally")
    return 0


def confirm(n: int, prefix: str) -> bool:
    print(f"\nWARNING: this writes the DOI field of {n} items in {prefix} through the Zotero Web API.")
    print("The change is applied on the server and synced to every member of the library.")
    answer = input("Type 'continue' to proceed or anything else to cancel: ")
    return answer.strip().lower() == "continue"


def _patch_doi(prefix: str, key: str, item_key: str, doi: str) -> int:
    url = f"{prefix}/items/{item_key}"
    try:
        current = api_request("GET", url, key)
        if current["data"].get("DOI") == doi:
            return 1
        api_request("PATCH", url, key, {"DOI": doi}, version=current["version"])
        return 1
    except urllib.error.HTTPError as e:
        print(f"    failed: HTTP {e.code} {e.read().decode(errors='replace')[:120]}", file=sys.stderr)
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

    v = sub.add_parser("resolve", help="map shortDOIs to full DOIs via doi.org, write CSV")
    v.add_argument("--library", type=int, required=True, help="libraryID from `zotidy libraries`")
    v.add_argument("--out", type=Path, default=Path("short_dois.csv"), help="CSV to write")
    v.set_defaults(func=cmd_resolve)

    a = sub.add_parser("apply-dois", help="write full DOIs from a resolve CSV via the Zotero Web API")
    a.add_argument("--library", type=int, required=True, help="libraryID from `zotidy libraries`")
    a.add_argument("--csv", type=Path, default=Path("short_dois.csv"), help="CSV from `zotidy resolve`")
    a.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    a.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    a.set_defaults(func=cmd_apply_dois)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
