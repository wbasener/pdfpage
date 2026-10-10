"""Read a PDF in a browser at a chosen page, from any of your devices.

    import pdfpage
    url = pdfpage.publish("report.pdf", page=12)          # a link that opens at page 12
    url = pdfpage.publish("report.pdf", find="soil / lag")  # or let it find the page

The address keeps the page number (#p=12), so it can be saved beside a citation.

Another web application can show the same viewer, in a new tab or in a pane beside its own page, without the
pdfpage server: it serves `assets_dir()` and a record from `citation_record` (see host.py). `check_quote` and
`quote_boxes` check a quoted passage against its page and find where on the page it sits (see quote.py).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import render, server, store, tailnet
from .host import assets_dir, citation_record, content_type, file_sha256, viewer_url
from .quote import QuoteBoxes, QuoteCheck, check_quote, quote_boxes
from .store import Document

__all__ = [
    "Document",
    "QuoteBoxes",
    "QuoteCheck",
    "assets_dir",
    "check_quote",
    "citation_record",
    "content_type",
    "file_sha256",
    "page_of",
    "publish",
    "published",
    "quote_boxes",
    "shutdown",
    "unpublish",
    "url_for",
    "viewer_url",
]
__version__ = "0.2.0"


def publish(
    pdf: str | Path,
    page: int = 1,
    *,
    find: str = "",
    name: str = "",
    title: str = "",
    subtitle: str = "",
    quote: str = "",
    dpi: int = store.DPI,
    mode: str = store.MODE,
    zoom: int = store.ZOOM,
) -> str:
    """Publish a PDF and return the address that opens it at `page`.

    pdf      the file, which stays where it is; only page images are cached elsewhere
    page     the page to open at (1 is the first page of the file, not of its numbering)
    find     a phrase to look for instead: the first page containing it becomes `page`,
             and the phrase is shown as the quote unless `quote` says otherwise
    name     the last part of the address; by default it is made from the file name
    title    the heading; by default the file name
    subtitle a line of context under the heading, such as the full citation
    quote    a passage to show in a highlighted box, such as the sentence being checked
    dpi      page-image resolution; raise it for small print, lower it for large documents
    mode     which view to open in: "pdf" (the scrolling PDF, with its text, zoom and highlights) or "images"
             (pictures of the pages, for a browser that cannot run the PDF viewer)
    zoom     the percentage the scrolling PDF opens at, for example 125
    """
    if mode not in ("pdf", "images"):
        raise ValueError(f'mode must be "pdf" or "images", not {mode!r}')
    if not 10 <= zoom <= 1000:
        raise ValueError(f"zoom must be a percentage between 10 and 1000, not {zoom}")
    path = Path(pdf).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    pages = render.page_count(path)
    if find:
        found = render.find_page(path, find, pages)
        if found is None:
            raise LookupError(
                f"{path.name} has no page whose text contains {find!r}; "
                "a scanned document carries text only where it has been through character recognition"
            )
        page, quote = found, quote or find
    if not 1 <= page <= pages:
        raise ValueError(f"page {page} is outside {path.name}, which has {pages} pages")

    doc = store.Document(
        slug=store.slugify(name or path.stem),
        pdf=str(path),
        pages=pages,
        page=page,
        title=title or path.stem,
        subtitle=subtitle,
        quote=quote,
        dpi=dpi,
        mode=mode,
        zoom=zoom,
    )
    docs = store.load()
    if (old := docs.get(doc.slug)) and (old.pdf != doc.pdf or old.dpi != doc.dpi):
        shutil.rmtree(old.cache, ignore_errors=True)  # a different file or size: drop stale images
    docs[doc.slug] = doc
    store.save(docs)
    server.start_background()
    return f"{tailnet.base_url()}/{doc.slug}/#p={doc.page}"


def url_for(name: str, page: int | None = None) -> str:
    """The address of an already published document, at `page` if given."""
    docs = store.load()
    doc = docs.get(store.slugify(name))
    if doc is None:
        raise KeyError(f"{name} is not published; published(): {sorted(docs)}")
    return f"{tailnet.base_url()}/{doc.slug}/#p={page or doc.page}"


def published() -> dict[str, Document]:
    """Every published document, by name."""
    return store.load()


def page_of(pdf: str | Path, phrase: str) -> int | None:
    """The first page of `pdf` whose text contains `phrase`, or None. Nothing is published."""
    return render.find_page(Path(pdf).expanduser().resolve(), phrase)


def unpublish(name: str, *, keep_images: bool = False) -> bool:
    """Remove a document from the list. The PDF itself is never touched."""
    docs = store.load()
    doc = docs.pop(store.slugify(name), None)
    if doc is None:
        return False
    if not keep_images:
        shutil.rmtree(doc.cache, ignore_errors=True)
    store.save(docs)
    return True


def shutdown(*, tailnet_too: bool = False) -> bool:
    """Stop the local server. With tailnet_too, also remove the tailnet path."""
    stopped = server.stop()
    if tailnet_too:
        tailnet.unpublish_path()
    return stopped
