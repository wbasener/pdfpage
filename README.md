# pdfpage

Read a PDF in a browser at a chosen page, from any of your devices, or beside the pages of your own web application.

It was written for checking citations.
You have a sentence attributed to page 12 of a scanned report, you want to see that page, and then you want to read the pages around it for context.
`pdfpage` gives you a link that opens the document at that page, with the quoted sentence highlighted on the page, and lets you zoom, mark passages of your own, and step or scroll through the rest.

```
pdfpage report.pdf --page 12 --quote "a surface soil / lag geochemical survey"
https://your-machine.your-tailnet.ts.net/pdf/report/#p=12
```

```python
import pdfpage

url = pdfpage.publish("report.pdf", find="surface soil / lag geochemical survey")
```

The same viewer works in two ways:

- **in a tab of its own**, from the small server that `pdfpage` runs (the command and `publish`);
- **in a pane beside another web page**, for a web application that cites documents: a button opens the viewer on the right of the page, and the pane has a link that opens the same view in a new tab ("The side pane" below).

## What the viewer gives you

- **The page, with the quote marked.** The document opens at the chosen page with the quoted passage outlined in orange, scrolled so the passage is in view; "Back to the quote" returns to it.
  The quote is found word by word in the PDF's text (`quote_boxes`), so it is marked only where the PDF has text; a scan carries text only where it has been through character recognition.
- **Scrolling through the whole document**, drawn by [PDF.js](https://mozilla.github.io/pdf.js/), which comes with the package.
  Previous and Next, a page-number box, and the left and right arrow keys move a page at a time.
- **Zoom**: "Zoom out", "Zoom in" (steps of 1.2 times, from 30 % to 400 %), "Fit width", and the current size between them.
  The + and - keys do the same, and so do Ctrl and the mouse wheel, or a pinch on a touchpad, around the pointer.
- **Two tools**, shown as a switch:
  - **Highlight**, the tool in use when the pointer is over the page: select words with the mouse and they are highlighted in yellow; click a highlight and then "Remove highlight" to take it away (or press Delete); Ctrl+Z takes away the last one.
    On a touch screen, select the words and tap "Highlight".
  - **Hand**: the pointer becomes a hand that grabs the page; drag to move around it, up, down and across.
    Holding the space bar gives the hand for as long as it is held.
- **Your highlights are kept in your own browser only**, in its local storage, named by the document's SHA-256 (a fingerprint of the file's contents), so the same file shows the same highlights from any address.
  Nothing is sent anywhere, and another person, browser or device does not see them.
  "Clear my highlights" (under "More") removes all of yours from the document; the quote's own mark stays, and cannot be removed.
- **A link that remembers the page.** The address keeps the page number (`#p=12`) as you move, and "Copy link to this page" copies it.
- **A heading that never hides the tools.** The title, a line of context such as the full citation, and the quote each take one line, cut short with "..." when they are long; "Show in full" opens them, and the title's full text is also its tooltip.
  The buttons sit in rows of their own above the page at every window width, from a phone to a wide screen.
- **Light and dark**, following the system, the host page (in the side pane), or the reader's choice under "More".
- **Page images**, for a browser that cannot run PDF.js: each page rendered to a picture by the server, with the quote marked the same way.
  `pdfpage` switches to them by itself in that case, and "Show page images" (under "More") switches by hand.
  Where there are no page images (in a host application), the browser's own PDF viewer is used instead.

Pages are rendered as they come into view, and the server sends only the parts of the file the viewer asks for, so a thousand-page document opens as quickly as a ten-page one.

## Installing

Needs Python 3.10 or later and [poppler-utils](https://poppler.freedesktop.org/) (`pdfinfo`, `pdftoppm`, `pdftotext`):

```
sudo apt install poppler-utils     # Debian, Ubuntu
brew install poppler               # macOS
```

Then:

```
pip install pdfpage                                    # from PyPI
pip install git+https://github.com/wbasener/pdfpage    # or the latest from this repository
uv tool install pdfpage                                # or as a command in every shell
```

It has no Python dependencies.
To work on it, from a clone: `pip install -e ".[dev]"`.

[Tailscale](https://tailscale.com/) is optional.
With it, the address works on all your devices; without it, you get a `http://127.0.0.1` address that works on the machine running `pdfpage`.

## The command

```
pdfpage report.pdf --page 12                        publish, and print the link
pdfpage report.pdf --find "a sentence to look for"  publish at the page containing a phrase
pdfpage find report.pdf "a sentence"                just print the page number
pdfpage list                                        what is published, and where
pdfpage remove report                               take one off the list
pdfpage where                                       folders, port, server state, address
pdfpage stop [--tailnet]                            stop the local server
```

Useful options for `add`:

| option | what it does |
| --- | --- |
| `--name` | the last part of the address; by default made from the file name |
| `--title` | the heading; by default the file name |
| `--subtitle` | a line of context under the heading, where a full citation reads well |
| `--quote` | a passage to mark on the page and show under the heading |
| `--zoom` | the percentage the document opens at (default 125); a window narrower than that opens at its width |
| `--images` | open in the page images instead of the scrolling PDF |
| `--dpi` | page-image resolution (default 150); raise it for small print |

After an upgrade, `pdfpage stop` and then any `pdfpage` publish starts the server again with the new viewer.

## From Python

```python
import pdfpage

pdfpage.publish(path, page=1, *, find="", name="", title="", subtitle="", quote="",
                dpi=150, mode="pdf", zoom=125) -> str
pdfpage.url_for(name, page=None) -> str      # link to something already published
pdfpage.page_of(path, phrase) -> int | None  # find a page without publishing
pdfpage.published() -> dict[str, Document]
pdfpage.unpublish(name) -> bool
pdfpage.shutdown(tailnet_too=False) -> bool

# Checking a quote against its page
pdfpage.check_quote(path, page, quote) -> QuoteCheck            # .ok, .reason, .found_on (nearby pages)
pdfpage.quote_boxes(path, page, quote) -> QuoteBoxes | None     # where the quote sits, one box per line

# Showing the viewer from another web application
pdfpage.assets_dir() -> Path                                     # the viewer, the pane and PDF.js, to serve
pdfpage.citation_record(doc_url, page, *, title="", subtitle="", quote="", boxes=None, printed="",
                        note="", sha256="", pages=None, zoom="page-width", images="", view="pdf",
                        pdf=None) -> dict                        # what the viewer reads
pdfpage.viewer_url(record_url, *, assets="", id="", page=None) -> str
pdfpage.file_sha256(path) -> str
pdfpage.content_type(path) -> str                                # the media type for one of the assets
```

`publish` raises `FileNotFoundError` for a missing file, `ValueError` for a page outside the document or a `mode` or `zoom` that makes no sense, and `LookupError` when `find` matches nothing.

`check_quote` and `quote_boxes` match letters and digits only, in lower case: spaces, line breaks, punctuation and hyphens at the ends of lines are ignored, but every word and number of the quote must be there, in order.
`check_quote` asks for at least 25 letters and digits, so that a short phrase cannot match by chance, and when the quote is not on the cited page it names the nearby pages (three either side) that hold it.
Page numbers are positions in the file, counting the cover as page 1, which is often not the number printed on the page; `citation_record(printed=...)` shows the printed one beside it.

## The viewer in another web application

A host application serves two things, and needs no copy of the viewer:

1. the folder `pdfpage.assets_dir()` as static files, under an address of its choice, for example `/pdfpage/`;
2. a JSON file of records made by `citation_record`: one record, or many keyed by an id.

```python
import json
from pathlib import Path

import pdfpage

records = {
    "c1": pdfpage.citation_record(
        "../pdf/wmc-1999.pdf",  # the PDF's address, relative to this JSON file
        12,
        title="WMC Resources, Combined Annual Report C333/1997",
        subtitle="WAMEX report A60645",
        quote="The major exploration activity conducted during the year was a surface soil",
        printed="7",
        pdf="/data/reports/a60645.pdf",  # the file on this machine: finds the quote's boxes and SHA-256
    ),
}
Path("site/data/citations.json").write_text(json.dumps(records))
url = pdfpage.viewer_url("data/citations.json", assets="pdfpage/", id="c1")
# "pdfpage/viewer.html?record=../data/citations.json&id=c1"
```

With FastAPI or Starlette, for example: `app.mount("/pdfpage", StaticFiles(directory=pdfpage.assets_dir()))`.
Any static file server works, as long as `.mjs` files go out as `text/javascript` (`pdfpage.content_type` gives the type for each file).
The record's address is resolved against the viewer's address, and the document's address inside the record against the record's own address.
A PDF served with HTTP range requests (most servers do) opens a page without the whole file being downloaded first.

The viewer's address also takes `?file=<address of a PDF>` in place of a record, `#p=<page>`, `?theme=light` or `dark`, and `?build=legacy` (PDF.js's build for older browsers, which it otherwise tries by itself when the newer one cannot run).

### The side pane

```html
<link rel="stylesheet" href="pdfpage/pane.css">
<script src="pdfpage/pane.js" defer></script>

<button type="button" data-pdfpage="pdfpage/viewer.html?record=../data/citations.json&id=c1"
        data-pdfpage-label="Cited document">Show the page in the document</button>
<a href="pdfpage/viewer.html?record=../data/citations.json&id=c2" data-pdfpage>Page 4 of the report</a>
```

A click on an element with `data-pdfpage` opens the viewer in a pane on the right of the window, with "Open in a new tab" (at the page the reader has reached) and "Close" above it.
The reader can drag the pane's left edge to make it wider or narrower, and the width is remembered in their browser.
At a window width of 900 pixels or less, as on a phone, the pane covers the whole window.
A link (`<a href=... data-pdfpage>`) still opens in a new tab when clicked with Ctrl, Shift or the middle button, or where JavaScript does not run.

- `data-pdfpage-label` sets the words in the pane's bar (default "Document").
- `data-pdfpage-target="#selector"` opens the viewer inside that element of the page instead of the floating pane.
- From a script: `pdfpage.open(url, {label, target, trigger})`, `pdfpage.close()`, `pdfpage.isOpen()`.
- Events on `document`: `pdfpage:open` (with `detail.url` and `detail.trigger`) and `pdfpage:close`.
  While its document is open, the clicked element has the class `pdfpage-active` and `aria-expanded="true"`.
- The pane follows the host page's theme: `<html data-pdfpage-theme="light">` or `"dark"` if set, else `<html data-theme="...">`, else the page's `color-scheme`, else the system's; when it changes, the viewer changes with it.
- While the pane is open, the page's `body` gets a right margin of the pane's width, so nothing is hidden behind it; the width is also the CSS variable `--pdfpage-pane-width`.
  `<html data-pdfpage-push="off">` turns the margin off, for a page that makes room another way, for example `html.pdfpage-pane-open main { margin-right: var(--pdfpage-pane-width); }` under a full-width header.
- CSS variables for the host: `--pdfpage-pane-top` (how far below the top of the window the pane starts, for a fixed header), `--pdfpage-pane-z` (stacking order, default 60) and `--pdfpage-inline-height` (a pane inside an element, default 75vh).

## How it works, and what it does not do

The `pdfpage` server listens on the loopback address `127.0.0.1` only.
Nothing is opened to your local network or to the internet, and your machine's firewall is never involved.
`tailscale serve` is what carries requests from your other devices to that server, over your own private network, so only your devices can reach it.

Your PDFs are **not** copied or moved.
The list of published documents and the cached page images live under `~/.local/share/pdfpage` (set `PDFPAGE_HOME` to move them).
Removing a document deletes its cached images and nothing else.

Other settings, all through the environment: `PDFPAGE_PORT` (default 8473), `PDFPAGE_PREFIX` (default `/pdf`), `PDFPAGE_DPI` (default 150), `PDFPAGE_MODE` (`pdf` or `images`), `PDFPAGE_ZOOM` (default 125).

The viewer is PDF.js 6.3.289 from Mozilla (Apache License 2.0), copied unchanged into `src/pdfpage/viewer/pdfjs/` with its licence; `pdfjs/VERSION` says where it came from.
Its text is set in Noto Sans (SIL Open Font License 1.1), which also comes with the package.
A browser that cannot run either PDF.js build gets the page images, or else its own PDF viewer, opened at the page (`#page=12&zoom=125`, a convention from Adobe's "PDF open parameters" that Chrome, Edge and Firefox honour).

## Developing

```
pip install -e ".[dev]"
python -m playwright install chromium   # the browser for tests/test_browser.py, which skip without it
pytest          # tests build their own small PDF; no fixtures to download
ruff check . && ruff format --check .
mypy
```

pdfpage is MIT licensed.
The PDF.js it carries is under the Apache License 2.0, with parts under BSD and MIT licences and substitute fonts under their own licences; Noto Sans is under the SIL Open Font License 1.1.
Each licence file is beside the files it covers, and all are listed in `pyproject.toml`.
