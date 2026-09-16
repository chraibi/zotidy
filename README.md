# zotidy

Read-only diagnostics for a local Zotero library. It opens `~/Zotero/zotero.sqlite`
in immutable mode, so it is safe to run while Zotero is open and it can never
modify the library.

Successor of [ZoteroTidy](https://github.com/chraibi/ZoteroTidy): same checks,
but no Streamlit, no Web API round trips, and the whole library is scanned in
seconds instead of minutes.

## Use

The command comes first, then its options, as in `git commit -m`:
`zotidy COMMAND --library N [...]`. `zotidy --help` lists the commands,
`zotidy COMMAND --help` the options, and `zotidy report --help` also the checks.

```
uv run zotidy libraries
uv run zotidy report --library 20
uv run zotidy report --library 20 --check duplicate_pdf --check duplicate_doi
uv run zotidy report --library 20 --out report.md     # full report, Markdown
uv run zotidy report --library 20 --out report.json   # full report, JSON
uv run zotidy report --library 20 --check suspicious --identify   # look up PDFs online
uv run zotidy resolve --library 20 --out short_dois.csv  # shortDOI -> full DOI map
```

All of these are read-only. `resolve` only queries doi.org and writes a CSV.

### Write commands

> [!CAUTION]
> Every command in this section **modifies your library**. They write through
> the Zotero Web API, so the change lands on the server and syncs to every
> member of a group. Zotero has no undo for this. Each command asks for
> confirmation before writing; run it with `--dry-run` first and review the list.

```
uv run zotidy apply-dois --library 20 --csv short_dois.csv --dry-run   # show only
ZOTERO_API_KEY=... uv run zotidy apply-dois --library 20 --csv short_dois.csv
uv run zotidy clear-urls --library 20 --dry-run
ZOTERO_API_KEY=... uv run zotidy clear-urls --library 20
```

`apply-dois` replaces the shortDOI in each item's DOI field with the full DOI
from the `resolve` CSV. Before writing it prints a warning and waits for you to
type `continue`; `--yes` skips the prompt for scripted use. It needs an API key
with write access from <https://www.zotero.org/settings/keys>, and
`ZOTERO_USER_ID` when targeting the user library. Sync Zotero afterwards.

`clear-urls` blanks the URL and Accessed fields of every `redundant_url` item, in
batches of 50, after the same confirmation prompt. The DOI stays and resolves to
the same page, so nothing is lost for citations.

## Checks

| Check | Meaning |
|---|---|
| duplicate_pdf | one item with several PDF attachments of the same file name |
| duplicate_doi | several items with the same DOI |
| duplicate_isbn | several items with the same ISBN |
| duplicate_title | same item type and normalised title, not already caught above |
| missing_pdf | article or book without a PDF |
| missing_id | article without DOI, book without ISBN |
| suspicious | metadata produced by Zotero's PDF recognizer (`libraryCatalog = Zotero`); with `--identify` the PDF's first pages are read and the item is looked up on Crossref (needs `pdftotext`) |
| stub | item missing two of creators, year, and a title of three or more words |
| short_doi | shortDOI alias like `10/f5gckw`; valid, but Zotero and Crossref only match the full DOI |
| malformed_doi | DOI neither `10.NNNN/suffix` nor a shortDOI, e.g. a URL or a typo |
| redundant_url | item has a DOI and a URL that is only the publisher landing page for it; BibTeX needs just the DOI |
| preprint_pair | preprint (arXiv DOI or preprint type) next to a published version with the same first author and title |

## Fixing

`apply-dois` and `clear-urls` (see Write commands above) are the only fixes so far. Deleting
attachments or merging items still goes through the Zotero UI. The JSON report
carries item and attachment keys so more fix steps can be added later.

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
