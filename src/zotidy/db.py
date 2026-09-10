"""Read the Zotero sqlite database without touching it.

The database is opened with SQLite's immutable flag, so this works while
Zotero is running and can never write or lock the file.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DB = Path.home() / "Zotero" / "zotero.sqlite"

# Item types that are containers, not bibliographic records.
NON_BIBLIOGRAPHIC = {"attachment", "note", "annotation"}


@dataclass
class Attachment:
    item_id: int
    key: str
    content_type: str | None
    path: str | None

    @property
    def filename(self) -> str | None:
        if not self.path:
            return None
        return self.path.split(":", 1)[-1].rsplit("/", 1)[-1]

    @property
    def is_pdf(self) -> bool:
        return self.content_type == "application/pdf"


@dataclass
class Item:
    item_id: int
    key: str
    library_id: int
    item_type: str
    fields: dict[str, str] = field(default_factory=dict)
    creators: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)

    @property
    def title(self) -> str:
        return self.fields.get("title", "")

    @property
    def doi(self) -> str:
        return normalize_doi(self.fields.get("DOI", ""))

    @property
    def isbn(self) -> str:
        return "".join(ch for ch in self.fields.get("ISBN", "") if ch.isalnum()).upper()

    @property
    def pdfs(self) -> list[Attachment]:
        return [a for a in self.attachments if a.is_pdf]

    def label(self) -> str:
        who = self.creators[0] if self.creators else "?"
        year = self.fields.get("date", "")[:4] or "n.d."
        return f"{who} {year}: {self.title[:70]}"


def normalize_doi(value: str) -> str:
    v = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        v = v.removeprefix(prefix)
    return v


def connect(path: Path = DEFAULT_DB) -> sqlite3.Connection:
    uri = f"file:{path}?immutable=1"
    return sqlite3.connect(uri, uri=True)


def libraries(conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
    """Return (libraryID, type, name) for user and group libraries."""
    rows = conn.execute(
        """
        SELECT l.libraryID, l.type, COALESCE(g.name, 'My Library')
        FROM libraries l LEFT JOIN groups g ON g.libraryID = l.libraryID
        WHERE l.type IN ('user', 'group') ORDER BY l.libraryID
        """
    ).fetchall()
    return [(int(a), b, c) for a, b, c in rows]


def load_items(conn: sqlite3.Connection, library_id: int) -> list[Item]:
    """Load every non-deleted bibliographic item of a library with its data."""
    deleted = {r[0] for r in conn.execute("SELECT itemID FROM deletedItems")}

    items: dict[int, Item] = {}
    for item_id, key, type_name in conn.execute(
        """
        SELECT i.itemID, i.key, t.typeName FROM items i
        JOIN itemTypes t ON t.itemTypeID = i.itemTypeID
        WHERE i.libraryID = ?
        """,
        (library_id,),
    ):
        if item_id in deleted or type_name in NON_BIBLIOGRAPHIC:
            continue
        items[item_id] = Item(item_id, key, library_id, type_name)

    for item_id, name, value in conn.execute(
        """
        SELECT d.itemID, f.fieldName, v.value FROM itemData d
        JOIN fields f ON f.fieldID = d.fieldID
        JOIN itemDataValues v ON v.valueID = d.valueID
        JOIN items i ON i.itemID = d.itemID WHERE i.libraryID = ?
        """,
        (library_id,),
    ):
        if item_id in items:
            items[item_id].fields[name] = str(value)

    for item_id, last, first in conn.execute(
        """
        SELECT ic.itemID, c.lastName, c.firstName FROM itemCreators ic
        JOIN creators c ON c.creatorID = ic.creatorID
        JOIN items i ON i.itemID = ic.itemID WHERE i.libraryID = ?
        ORDER BY ic.itemID, ic.orderIndex
        """,
        (library_id,),
    ):
        if item_id in items:
            items[item_id].creators.append(last or first or "")

    for att_id, key, parent, ctype, path in conn.execute(
        """
        SELECT a.itemID, i.key, a.parentItemID, a.contentType, a.path
        FROM itemAttachments a JOIN items i ON i.itemID = a.itemID
        WHERE i.libraryID = ?
        """,
        (library_id,),
    ):
        if att_id in deleted or parent not in items:
            continue
        items[parent].attachments.append(Attachment(att_id, key, ctype, path))

    return list(items.values())


def group_by(items: list[Item], keyfn) -> dict[str, list[Item]]:
    groups: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        k = keyfn(it)
        if k:
            groups[k].append(it)
    return groups
