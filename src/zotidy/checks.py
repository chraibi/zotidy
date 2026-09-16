"""Diagnostics over a list of items. Every check returns Findings.

A Finding groups the items that share one problem, so the report can
show them together and a later fix step can act on the group.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .db import Item, group_by

# Item types expected to carry a DOI or an ISBN.
WANTS_DOI = {"journalArticle", "conferencePaper", "preprint"}
WANTS_ISBN = {"book", "bookSection"}

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
SHORT_DOI_RE = re.compile(r"^10/[a-z0-9]+$")
ARXIV_DOI_PREFIX = "10.48550/"

# Publisher landing pages that the DOI resolves to anyway.
PUBLISHER_HOSTS = {
    "doi.org", "dx.doi.org", "linkinghub.elsevier.com", "sciencedirect.com", "link.springer.com",
    "iopscience.iop.org", "link.aps.org", "journals.aps.org", "ieeexplore.ieee.org",
    "onlinelibrary.wiley.com", "nature.com", "journals.sagepub.com", "tandfonline.com", "mdpi.com",
    "royalsocietypublishing.org", "dl.acm.org", "portal.acm.org", "journals.plos.org", "dx.plos.org",
    "worldscientific.com", "pnas.org", "pubsonline.informs.org", "science.org", "hindawi.com",
    "ascelibrary.org", "aip.scitation.org", "pubs.aip.org", "jstor.org", "epubs.siam.org",
    "doi.apa.org", "cambridge.org", "academic.oup.com", "frontiersin.org", "degruyter.com",
}


@dataclass
class Finding:
    check: str
    reason: str
    items: list[Item]
    hints: dict[str, str] = field(default_factory=dict)  # item key -> extra info


def _title_key(item: Item) -> str:
    """Type, first creator, year and normalised title.

    Same title by a different author or in a different year is another edition,
    not a duplicate. A missing year matches any year.
    """
    t = re.sub(r"[^a-z0-9]+", " ", item.title.lower()).strip()
    who = item.creators[0].lower() if item.creators else ""
    year = item.fields.get("date", "")[:4]
    return f"{item.item_type}|{who}|{year}|{t}" if len(t) > 15 else ""


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
    for key, group in _title_groups(items).items():
        if len(group) > 1 and frozenset(i.item_id for i in group) not in seen:
            out.append(Finding("duplicate_title", key.rsplit("|", 1)[1], group))
    return out


def _title_groups(items: list[Item]) -> dict[str, list[Item]]:
    """Group by _title_key, folding items without a year into every dated group."""
    groups = group_by(items, _title_key)
    undated = {k: g for k, g in groups.items() if k and k.split("|", 3)[2] == ""}
    for key, group in undated.items():
        typ, who, _, title = key.split("|", 3)
        dated = [k for k in groups if k.startswith(f"{typ}|{who}|") and k.endswith(f"|{title}") and k != key]
        for k in dated:
            groups[k].extend(group)
    return groups


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


def empty_stubs(items: list[Item]) -> list[Finding]:
    """Items missing at least two of: creators, year, a title of three or more words."""
    def gaps(i: Item) -> int:
        return sum([not i.creators, not i.fields.get("date", "")[:4], len(i.title.split()) < 3])

    bad = [i for i in items if i.item_type not in {"note", "attachment"} and gaps(i) >= 2]
    return [Finding("stub", "missing two of creators, year, title", bad)] if bad else []


def short_dois(items: list[Item]) -> list[Finding]:
    """shortDOI aliases (10/xxxxx). Valid, but Zotero and Crossref match only the full DOI."""
    bad = [i for i in items if SHORT_DOI_RE.match(i.doi)]
    return [Finding("short_doi", "shortDOI, resolve to full DOI", bad)] if bad else []


def malformed_dois(items: list[Item]) -> list[Finding]:
    """DOIs that are neither 10.NNNN/suffix nor a shortDOI, e.g. URLs or typos."""
    bad = [i for i in items if i.doi and not DOI_RE.match(i.doi) and not SHORT_DOI_RE.match(i.doi)]
    return [Finding("malformed_doi", "DOI not 10.NNNN/suffix", bad)] if bad else []


def _is_preprint(item: Item) -> bool:
    return item.item_type == "preprint" or item.doi.startswith(ARXIV_DOI_PREFIX)


def preprint_pairs(items: list[Item]) -> list[Finding]:
    """A preprint next to a published version: same first creator and title."""
    def key(i: Item) -> str:
        t = _title_key(i).rsplit("|", 1)[-1]
        who = i.creators[0].lower() if i.creators else ""
        return f"{who}|{t}" if t else ""

    out = []
    for k, group in group_by(items, key).items():
        pre = [i for i in group if _is_preprint(i)]
        pub = [i for i in group if not _is_preprint(i)]
        if pre and pub:
            out.append(Finding("preprint_pair", k.split("|", 1)[1], pre + pub))
    return out


def _redundant_url(item: Item) -> bool:
    url = item.fields.get("url", "")
    if not item.doi or not url or url.lower().endswith(".pdf"):
        return False
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return host in PUBLISHER_HOSTS or item.doi in url.lower()


def redundant_urls(items: list[Item]) -> list[Finding]:
    """Item has a DOI and a URL that is just the publisher landing page for that DOI."""
    bad = [i for i in items if _redundant_url(i)]
    return [Finding("redundant_url", "URL is the DOI's publisher page", bad)] if bad else []


# One line per check, shown in `zotidy report --help`.
CHECK_HELP = {
    "duplicate_pdf": "several PDF attachments with the same file name on one item",
    "duplicate_doi": "several items with the same DOI",
    "duplicate_isbn": "several items with the same ISBN",
    "duplicate_title": "same type, first creator, year and title (not caught above)",
    "missing_pdf": "article or book without a PDF",
    "missing_id": "article without DOI, book without ISBN",
    "suspicious": "metadata from Zotero's PDF recognizer; --identify looks up the PDF",
    "stub": "missing two of: creators, year, a title of three or more words",
    "short_doi": "shortDOI alias like 10/f5gckw; see fixes below",
    "malformed_doi": "DOI neither 10.NNNN/suffix nor a shortDOI",
    "preprint_pair": "preprint next to its published version",
    "redundant_url": "URL is only the DOI's publisher page; see fixes below",
}

ALL_CHECKS = {
    "duplicate_pdf": duplicate_pdfs,
    "duplicate_doi": duplicates_by_doi,
    "duplicate_isbn": duplicates_by_isbn,
    "duplicate_title": duplicates_by_title,
    "missing_pdf": missing_pdf,
    "missing_id": missing_identifier,
    "suspicious": suspicious_metadata,
    "stub": empty_stubs,
    "short_doi": short_dois,
    "malformed_doi": malformed_dois,
    "preprint_pair": preprint_pairs,
    "redundant_url": redundant_urls,
}


def run(items: list[Item], names: list[str] | None = None) -> list[Finding]:
    names = names or list(ALL_CHECKS)
    findings: list[Finding] = []
    for n in names:
        findings.extend(ALL_CHECKS[n](items))
    return findings
