# zotidy

Read-only diagnostics for a local Zotero library. It opens `~/Zotero/zotero.sqlite`
in immutable mode, so it is safe to run while Zotero is open and it can never
modify the library.

Successor of [ZoteroTidy](https://github.com/chraibi/ZoteroTidy): same checks,
but no Streamlit, no Web API round trips, and the whole library is scanned in
seconds instead of minutes.

## Use

```
uv run zotidy libraries
uv run zotidy report --library 20
uv run zotidy report --library 20 --check duplicate_pdf --check duplicate_doi
uv run zotidy report --library 20 --out report.md     # full report, Markdown
uv run zotidy report --library 20 --out report.json   # full report, JSON
```

## Checks

| Check | Meaning |
|---|---|
| duplicate_pdf | one item with several PDF attachments of the same file name |
| duplicate_doi | several items with the same DOI |
| duplicate_isbn | several items with the same ISBN |
| duplicate_title | same item type and normalised title, not already caught above |
| missing_pdf | article or book without a PDF |
| missing_id | article without DOI, book without ISBN |
| suspicious | metadata produced by Zotero's PDF recognizer (`libraryCatalog = Zotero`) |

## Fixing

Fixes are deliberately not part of this tool yet. Deleting attachments or merging
items must go through the Zotero Web API or the Zotero UI. The JSON report carries
item and attachment keys so a fix step can be added later.

Metadata normalisation (author names, journal names, DOIs, APA style) is a
different job and is already solved by the
[Zometaker](https://github.com/ShiyangZheng/zometaker) plugin inside Zotero.
Use that; do not reimplement it here.

## Development

```
uv sync --extra dev
uv run pytest
uv run ruff check .
```
