"""Showing the viewer from another web application, in a new tab or in a pane beside the host's own page.

A host application serves two things and needs no copy of the viewer:

1. the folder `assets_dir()` as static files, under any address, for example /pdfpage/;
2. a JSON record for each place in a document it wants to show, made by `citation_record`. One file may
   hold a single record, or many keyed by an id ({"c1": {...}, "c2": {...}}).

The viewer is then `<assets>/viewer.html?record=<record address>&id=<id>`, which `viewer_url` writes.
The record's address is resolved against the viewer page's address, and the document's address inside the
record against the record's own address, as a browser resolves a link inside the file it was read from.

For the pane beside a page, the host page also loads `<assets>/pane.css` and `<assets>/pane.js`; any element
with `data-pdfpage="<viewer address>"` then opens the viewer in a right-hand pane (README: "The side pane").
"""

from __future__ import annotations

import hashlib
import posixpath
from functools import lru_cache
from importlib import resources
from pathlib import Path
from urllib.parse import quote as urlquote

from .quote import QuoteBoxes, quote_boxes

RECORD_FORMAT = 1  # the "pdfpage" field of a record; raised when a field changes meaning

# The media types of the viewer's files. Browsers refuse a JavaScript module served under another type, and
# some systems' own tables lack .mjs or the PDF.js font and character-map files.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".gif": "image/gif",
    ".wasm": "application/wasm",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".pfb": "application/octet-stream",
    ".bcmap": "application/octet-stream",
    ".icc": "application/vnd.iccprofile",
    ".txt": "text/plain; charset=utf-8",
    ".pdf": "application/pdf",
}
ZOOM_WORDS = ("page-width", "page-fit", "auto")  # sizes the viewer works out from the pane's width or height


def assets_dir() -> Path:
    """The folder holding the viewer (viewer.html, viewer.js, viewer.css), the pane (pane.js, pane.css),
    PDF.js and the fonts. Serve it as static files under any address."""
    return Path(str(resources.files(__package__).joinpath("viewer")))


def content_type(path: str | Path) -> str:
    """The media type to serve one of the viewer's files with."""
    return CONTENT_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


@lru_cache(maxsize=1024)
def _sha256(path: str, size: int, mtime_ns: int) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(1 << 20):
            h.update(block)
    return h.hexdigest()


def file_sha256(pdf: str | Path) -> str:
    """The file's SHA-256, which names the document in the browser's store of a reader's highlights, so the
    same file read from two addresses shows the same highlights. Kept in memory while the file is the same."""
    path = Path(pdf).expanduser().resolve()
    st = path.stat()
    return _sha256(str(path), st.st_size, st.st_mtime_ns)


def citation_record(
    doc_url: str,
    page: int = 1,
    *,
    title: str = "",
    subtitle: str = "",
    quote: str = "",
    boxes: QuoteBoxes | None = None,
    printed: str = "",
    note: str = "",
    sha256: str = "",
    pages: int | None = None,
    zoom: int | str = "page-width",
    images: str = "",
    view: str = "pdf",
    pdf: str | Path | None = None,
) -> dict[str, object]:
    """The JSON record the viewer reads: which document, which page, and what to show with it.

    doc_url   the PDF's address, relative to the record's own address (or absolute)
    page      the page to open at and whose quote is highlighted (1 is the first page of the file)
    title     the heading; subtitle a line of context under it, such as the full citation
    quote     the quoted passage, shown under the heading; boxes says where it sits on the page (quote_boxes)
    printed   the page number printed on the page, when it differs from the file's own count
    note      one more line under the quote, for example why the quote is not highlighted
    sha256    the file's SHA-256, which keys the reader's highlights; without it the viewer uses PDF.js's own
              fingerprint of the file
    pages     the number of pages, shown before the document has loaded and used by the page-image view
    zoom      the size it opens at: a percentage (10 to 1000) or "page-width", "page-fit" or "auto"
    images    the address of one page's image with {page} in place of the number, for the page-image view;
              empty where there are no page images
    view      "pdf" (the PDF.js viewer) or "images" (the page images, which needs `images`)
    pdf       the file on this machine, when there is one: boxes (for a quote) and sha256 are then worked
              out from it unless they are given
    """
    if not isinstance(page, int) or page < 1:
        raise ValueError(f"page must be a whole number from 1, not {page!r}")
    if pages is not None and not 1 <= page <= pages:
        raise ValueError(f"page {page} is outside a document of {pages} pages")
    if isinstance(zoom, str):
        if zoom not in ZOOM_WORDS:
            raise ValueError(f"zoom must be a percentage or one of {ZOOM_WORDS}, not {zoom!r}")
    elif not 10 <= zoom <= 1000:
        raise ValueError(f"zoom must be a percentage between 10 and 1000, not {zoom}")
    if view not in ("pdf", "images"):
        raise ValueError(f'view must be "pdf" or "images", not {view!r}')
    if images and "{page}" not in images:
        raise ValueError(f"images must hold {{page}} where the page number goes, not {images!r}")
    if view == "images" and not images:
        raise ValueError('view "images" needs the address of the page images (images=...)')
    if pdf is not None:
        if boxes is None and quote:
            boxes = quote_boxes(pdf, page, quote)
        sha256 = sha256 or file_sha256(pdf)
    if boxes is not None:
        _check_boxes(boxes)
    return {
        "pdfpage": RECORD_FORMAT,
        "doc": doc_url,
        "page": page,
        "title": title,
        "subtitle": subtitle,
        "quote": quote,
        "highlight": boxes,
        "printed": printed if printed != str(page) else "",
        "note": note,
        "sha256": sha256,
        "pages": pages,
        "zoom": zoom,
        "images": images,
        "view": view,
    }


def _check_boxes(boxes: QuoteBoxes) -> None:
    size = boxes.get("page_size")
    if not (
        isinstance(size, list) and len(size) == 2 and all(isinstance(v, (int, float)) and v > 0 for v in size)
    ):
        raise ValueError(f"boxes page_size must be [width, height] in points, not {size!r}")
    for box in boxes.get("boxes", []):
        if not (isinstance(box, list) and len(box) == 4 and box[0] <= box[2] and box[1] <= box[3]):
            raise ValueError(f"each box must be [x0, y0, x1, y1] with x0 <= x1 and y0 <= y1, not {box!r}")


def _absolute(url: str) -> bool:
    return url.startswith("/") or "://" in url.split("?")[0]


def viewer_url(record_url: str, *, assets: str = "", id: str = "", page: int | None = None) -> str:
    """The viewer's address for a record, as a link on the host page.

    record_url  the record file's address, as seen from the host page
    assets      the address `assets_dir()` is served under, as seen from the host page ("pdfpage/")
    id          the record's id, when the file holds many records keyed by id
    page        a page to open at instead of the record's own

    Both addresses may be relative to the host page or both absolute; a relative record with an absolute
    `assets` cannot be resolved here, because the host page's own address is not known.
    """
    base = assets.rstrip("/")
    if _absolute(record_url):
        record = record_url
    elif _absolute(assets):
        raise ValueError(
            "record_url is relative to the host page but assets is absolute; "
            "give both relative or both absolute"
        )
    else:
        record = posixpath.relpath(record_url, base or ".")
    url = f"{base + '/' if base else ''}viewer.html?record={urlquote(record, safe='/:.-_~')}"
    if id:
        url += f"&id={urlquote(id, safe='')}"
    if page is not None:
        url += f"#p={page}"
    return url
