from zotidy.checks import duplicate_pdfs, duplicates_by_doi, duplicates_by_title, missing_identifier
from zotidy.db import Attachment, Item


def item(i, title="A long enough title for matching", typ="journalArticle", **fields):
    return Item(i, f"K{i}", 1, typ, fields={"title": title, **fields})


def test_duplicate_pdf_same_name_only():
    a = item(1)
    a.attachments = [
        Attachment(10, "A", "application/pdf", "storage:x.pdf"),
        Attachment(11, "B", "application/pdf", "storage:x.pdf"),
        Attachment(12, "C", "application/pdf", "storage:supplement.pdf"),
    ]
    b = item(2)
    b.attachments = [Attachment(13, "D", "application/pdf", "storage:y.pdf")]
    found = duplicate_pdfs([a, b])
    assert [f.items[0].item_id for f in found] == [1]
    assert found[0].reason == "x.pdf"


def test_doi_duplicates_ignore_prefix_and_case():
    a = item(1, DOI="10.1000/ABC")
    b = item(2, DOI="https://doi.org/10.1000/abc")
    c = item(3, DOI="10.1000/other")
    found = duplicates_by_doi([a, b, c])
    assert len(found) == 1 and {i.item_id for i in found[0].items} == {1, 2}


def test_title_duplicates_skip_groups_already_found_by_doi():
    a = item(1, DOI="10.1/x")
    b = item(2, DOI="10.1/x")
    c = item(3, title="Another sufficiently long title")
    d = item(4, title="another SUFFICIENTLY long title!")
    found = duplicates_by_title([a, b, c, d])
    assert len(found) == 1 and {i.item_id for i in found[0].items} == {3, 4}


def test_missing_identifier_by_type():
    found = missing_identifier([item(1), item(2, typ="book"), item(3, DOI="10.1/x")])
    assert {f.check: [i.item_id for i in f.items] for f in found} == {
        "missing_doi": [1], "missing_isbn": [2]}
