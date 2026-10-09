# pdfpage

Read a PDF in a browser at a chosen page, from any of your devices.

It was written for checking citations.
You have a sentence attributed to page 12 of a scanned report, you want to see that page, and then you want to read the pages around it for context.
`pdfpage` gives you a link that opens the document at that page, with the quoted sentence shown beside it, and lets you step or scroll through the rest.

```
pdfpage report.pdf --page 12
https://your-machine.your-tailnet.ts.net/pdf/report/#p=12
```

```python
import pdfpage

url = pdfpage.publish("report.pdf", find="surface soil / lag geochemical survey")
```

## What the page gives you

- **Page images**: every page rendered to a picture, with Previous and Next buttons, a page-number box, and the left and right arrow keys. This works in every browser, including on a phone.
- **Scrolling PDF**: the browser's own PDF viewer, opened at the same page. Scroll freely through the whole document, and Ctrl+F searches the text.
- **A link that remembers the page.** The address keeps the page number (`#p=12`) as you move, and a button copies it. Save that link next to the citation.
- A heading, a line of context such as the full citation, and the quoted passage in a highlighted box.

Pages are rendered only when a browser first asks for one, and then kept.
A thousand-page document publishes as quickly as a ten-page one.

## Installing

Needs Python 3.10 or later and [poppler-utils](https://poppler.freedesktop.org/) (`pdfinfo`, `pdftoppm`, `pdftotext`):

```
sudo apt install poppler-utils     # Debian, Ubuntu
brew install poppler               # macOS
```

Then, from a clone of this repository:

```
pip install -e .            # into a project's environment, so `import pdfpage` works there
uv tool install --editable .   # or as a command available in every shell
```

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

Useful options for `add`: `--name` (the last part of the address), `--title`, `--subtitle` (a full citation reads well here), `--quote`, `--dpi`.

## From Python

```python
import pdfpage

pdfpage.publish(path, page=1, *, find="", name="", title="", subtitle="", quote="", dpi=150) -> str
pdfpage.url_for(name, page=None) -> str      # link to something already published
pdfpage.page_of(path, phrase) -> int | None  # find a page without publishing
pdfpage.published() -> dict[str, Document]
pdfpage.unpublish(name) -> bool
pdfpage.shutdown(tailnet_too=False) -> bool
```

`publish` raises `FileNotFoundError` for a missing file, `ValueError` for a page outside the document, and `LookupError` when `find` matches nothing.

## How it works, and what it does not do

A small web server listens on the loopback address `127.0.0.1` only.
Nothing is opened to your local network or to the internet, and your machine's firewall is never involved.
`tailscale serve` is what carries requests from your other devices to that server, over your own private network, so only your devices can reach it.

Your PDFs are **not** copied or moved.
The list of published documents and the cached page images live under `~/.local/share/pdfpage` (set `PDFPAGE_HOME` to move them).
Removing a document deletes its cached images and nothing else.

Other settings, all through the environment: `PDFPAGE_PORT` (default 8473), `PDFPAGE_PREFIX` (default `/pdf`), `PDFPAGE_DPI` (default 150).

A scanned document carries text only where it has been through character recognition, so `--find` cannot work on a scan that has not been.
Page numbers are positions in the file, counting the cover as page 1, which is often not the number printed on the page.

## Developing

```
pip install -e ".[dev]"
pytest          # tests build their own small PDF; no fixtures to download
ruff check . && ruff format --check .
mypy
```

MIT licensed.
