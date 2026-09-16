from zotidy.checks import (
    duplicate_pdfs,
    duplicates_by_doi,
    duplicates_by_title,
    empty_stubs,
    malformed_dois,
    missing_identifier,
    preprint_pairs,
    redundant_urls,
    short_dois,
)
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


def test_title_duplicates_require_same_first_creator():
    a = item(1, title="Traffic engineering handbook")
    b = item(2, title="Traffic engineering handbook.")
    a.creators, b.creators = ["Evans"], ["Baerwald"]
    assert duplicates_by_title([a, b]) == []


def test_title_duplicates_require_same_year_unless_missing():
    a = item(1, title="Emergency movement chapter", date="1995")
    b = item(2, title="Emergency movement chapter", date="2002")
    c = item(3, title="Emergency movement chapter")
    assert duplicates_by_title([a, b]) == []
    found = duplicates_by_title([a, c])
    assert len(found) == 1 and {i.item_id for i in found[0].items} == {1, 3}


def test_missing_identifier_by_type():
    found = missing_identifier([item(1), item(2, typ="book"), item(3, DOI="10.1/x")])
    assert {f.check: [i.item_id for i in f.items] for f in found} == {
        "missing_doi": [1], "missing_isbn": [2]}


def test_stub_needs_two_gaps():
    ok = item(1, date="2020")
    ok.creators = ["A"]
    short = item(2, title="Notes", date="2020")
    short.creators = ["A"]
    bare = item(3)
    assert [i.item_id for f in empty_stubs([ok, short, bare]) for i in f.items] == [3]


def test_short_and_malformed_doi_are_distinct():
    good = item(1, DOI="https://doi.org/10.1007/s10035-013-0443-7")
    short = item(2, DOI="10/f5gckw")
    broken = item(3, DOI="10.1007 s10035")
    assert [i.item_id for f in short_dois([good, short, broken]) for i in f.items] == [2]
    assert [i.item_id for f in malformed_dois([good, short, broken]) for i in f.items] == [3]


def test_preprint_pair_same_author_and_title():
    a = item(1, DOI="10.48550/arxiv.2207.10435", typ="preprint")
    b = item(2, DOI="10.1007/978-3-031-19830-4_22")
    c = item(3, DOI="10.48550/arxiv.1.2", title="Some other long enough title")
    for i in (a, b, c):
        i.creators = ["Yue"]
    found = preprint_pairs([a, b, c])
    assert len(found) == 1 and {i.item_id for i in found[0].items} == {1, 2}


def test_redundant_url_needs_doi_and_publisher_page():
    pub = item(1, DOI="10.1016/x", url="https://www.sciencedirect.com/science/article/pii/1")
    doi_in_url = item(2, DOI="10.1234/abc", url="https://example.org/10.1234/ABC")
    arxiv = item(3, DOI="10.1016/y", url="https://arxiv.org/abs/1.2")
    no_doi = item(4, url="https://www.sciencedirect.com/science/article/pii/2")
    found = redundant_urls([pub, doi_in_url, arxiv, no_doi])
    assert [i.item_id for f in found for i in f.items] == [1, 2]
