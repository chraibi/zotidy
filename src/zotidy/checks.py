"""Diagnostics over a list of items. Every check returns Findings.

A Finding groups the items that share one problem, so the report can
show them together and a later fix step can act on the group.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .db import Item, group_by

# Item types expected to carry a DOI or an ISBN.
WANTS_DOI = {"journalArticle", "conferencePaper", "preprint"}
WANTS_ISBN = {"book", "bookSection"}


@dataclass
class Finding:
    check: str
    reason: str
    items: list[Item]


def _title_key(item: Item) -> str:
    t = re.sub(r"[^a-z0-9]+", " ", item.title.lower()).strip()
    return f"{item.item_type}|{t}" if len(t) > 15 else ""


def duplicate_pdfs(items: list[Item]) -> list[Finding]:
    """Items with two or more PDF attachments of the same file name."""
    out = []
    for it in items:
        names = [a.filename for a in it.pdfs if a.filename]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            out.append(Finding("duplicate_pdf", ", ".join(dupes), [it]))
    return out


def duplicates_by_doi(items: list[Item]) -> list[Finding]:
    return [
        Finding("duplicate_doi", doi, group)
        for doi, group in group_by(items, lambda i: i.doi).items()
        if len(group) > 1
    ]


def duplicates_by_isbn(items: list[Item]) -> list[Finding]:
    return [
        Finding("duplicate_isbn", isbn, group)
        for isbn, group in group_by(items, lambda i: i.isbn).items()
        if len(group) > 1
    ]


def duplicates_by_title(items: list[Item]) -> list[Finding]:
    """Same type and same normalised title, but not already caught by DOI/ISBN."""
    seen = set()
    for f in duplicates_by_doi(items) + duplicates_by_isbn(items):
        seen.add(frozenset(i.item_id for i in f.items))
    out = []
    for key, group in group_by(items, _title_key).items():
        if len(group) > 1 and frozenset(i.item_id for i in group) not in seen:
            out.append(Finding("duplicate_title", key.split("|", 1)[1], group))
    return out


def missing_pdf(items: list[Item]) -> list[Finding]:
    bad = [i for i in items if i.item_type in WANTS_DOI | WANTS_ISBN and not i.pdfs]
    return [Finding("missing_pdf", "no PDF attachment", bad)] if bad else []


def missing_identifier(items: list[Item]) -> list[Finding]:
    no_doi = [i for i in items if i.item_type in WANTS_DOI and not i.doi]
    no_isbn = [i for i in items if i.item_type in WANTS_ISBN and not i.isbn]
    out = []
    if no_doi:
        out.append(Finding("missing_doi", "article without DOI", no_doi))
    if no_isbn:
        out.append(Finding("missing_isbn", "book without ISBN", no_isbn))
    return out


def suspicious_metadata(items: list[Item]) -> list[Finding]:
    """Items whose metadata came from Zotero's own PDF recognizer.

    These were imported from a PDF and may carry wrong or thin metadata.
    """
    bad = [i for i in items if i.fields.get("libraryCatalog") == "Zotero"]
    return [Finding("suspicious", "libraryCatalog is Zotero", bad)] if bad else []


ALL_CHECKS = {
    "duplicate_pdf": duplicate_pdfs,
    "duplicate_doi": duplicates_by_doi,
    "duplicate_isbn": duplicates_by_isbn,
    "duplicate_title": duplicates_by_title,
    "missing_pdf": missing_pdf,
    "missing_id": missing_identifier,
    "suspicious": suspicious_metadata,
}


def run(items: list[Item], names: list[str] | None = None) -> list[Finding]:
    names = names or list(ALL_CHECKS)
    findings: list[Finding] = []
    for n in names:
        findings.extend(ALL_CHECKS[n](items))
    return findings
