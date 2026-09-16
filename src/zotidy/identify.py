"""Guess correct metadata for a PDF whose Zotero record came from the recognizer.

Reads the first pages with pdftotext, looks for a DOI or arXiv ID, and asks
Crossref (by DOI, else by the page text) for the best match. Read-only.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from .db import Attachment, Item

DOI_IN_TEXT = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)
ARXIV_IN_TEXT = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE)
CROSSREF = "https://api.crossref.org/works"


def pdf_path(attachment: Attachment, db_path: Path) -> Path | None:
    if not attachment.path or not attachment.path.startswith("storage:"):
        return None
    return db_path.parent / "storage" / attachment.key / attachment.path.split(":", 1)[1]


def first_pages_text(path: Path, pages: int = 2) -> str:
    if not shutil.which("pdftotext"):
        return ""
    run = subprocess.run(["pdftotext", "-l", str(pages), str(path), "-"],
                         capture_output=True, text=True, errors="replace", check=False)
    return run.stdout if run.returncode == 0 else ""


def find_ids(text: str) -> tuple[str, str]:
    """(doi, arxiv_id) found in the text, each "" when absent."""
    doi = DOI_IN_TEXT.search(text)
    arxiv = ARXIV_IN_TEXT.search(text)
    return (doi.group(1).rstrip(".,;)") if doi else "", arxiv.group(1) if arxiv else "")


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "zotidy (mailto:m.chraibi@gmail.com)"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def _describe(work: dict) -> str:
    authors = [a.get("family", "") for a in work.get("author", [])[:3] if a.get("family")]
    year = (work.get("issued", {}).get("date-parts") or [[""]])[0][0] or "n.d."
    title = (work.get("title") or [""])[0]
    where = (work.get("container-title") or [""])[0]
    return f"{', '.join(authors)} {year}: {title[:80]} | {where} | doi:{work.get('DOI', '')}"


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def title_similarity(a: str, b: str) -> float:
    """Jaccard overlap of the word sets of two titles, 0..1."""
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def crossref_by_doi(doi: str) -> dict | None:
    try:
        return _get(f"{CROSSREF}/{urllib.parse.quote(doi)}")["message"]
    except (OSError, KeyError, ValueError):
        return None


def crossref_by_text(text: str) -> dict | None:
    query = " ".join(text.split()[:60])
    if not query:
        return None
    url = f"{CROSSREF}?rows=1&query.bibliographic={urllib.parse.quote(query)}"
    try:
        hits = _get(url)["message"]["items"]
    except (OSError, KeyError, ValueError):
        return None
    return hits[0] if hits else None


def best_match(item: Item, text: str, doi: str) -> str:
    """Crossref record for the DOI, else the best title search; weak matches are marked."""
    work = crossref_by_doi(doi) if doi else None
    if work:
        return _describe(work)
    for query in (item.title, text):
        work = crossref_by_text(query)
        if not work:
            continue
        sim = title_similarity(item.title, (work.get("title") or [""])[0])
        if sim >= 0.6:
            return _describe(work)
    return "no confident Crossref match"


def identify(item: Item, db_path: Path) -> str:
    """One-line hint for the item: found identifiers plus the best Crossref match."""
    paths = [p for a in item.pdfs if (p := pdf_path(a, db_path)) and p.exists()]
    if not paths:
        return "no PDF file on disk"
    text = first_pages_text(paths[0])
    if not text:
        return "no text in PDF (scan without OCR, or pdftotext missing)"
    doi, arxiv = find_ids(text)
    hint = best_match(item, text, doi)
    if arxiv:
        hint = f"arXiv:{arxiv} | {hint}"
    return hint
