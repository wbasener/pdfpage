"""Checking that a quoted passage is on its page, and finding where on the page it sits.

A citation names a PDF, a page (the file's own page number, 1 = the first page of the file) and an exact
quote. `check_quote` says whether the quote is on that page, or on which nearby page it is instead;
`quote_boxes` gives the rectangles the quote covers, one per line of text, which the viewer draws as the
quote's highlight.

Matching compares letters and digits only, in lower case, after Unicode compatibility folding (ligatures such
as "fi" become two letters). Spaces, line breaks, punctuation and hyphens at line ends are therefore ignored,
but every word and number of the quote must appear in the same order with nothing in between. A quote must
hold at least MIN_CHARS letters and digits, so a short phrase cannot match by chance.

Moved from the OrePrior3D Model Atlas (atlas/cite.py: check, page_bbox, quote_boxes); the matching rule is
unchanged. Page texts and word boxes come from poppler's pdftotext and are kept in memory, keyed by the file's
path, size and modification time, so a changed file is read again.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

from . import render

MIN_CHARS = 25  # letters and digits a quote must hold, so a short phrase cannot match by chance
SEARCH_NEAR = 3  # pages either side of the cited one that check_quote also looks at


class QuoteBoxes(TypedDict):
    """Where a quote sits on its page: the page size in PDF points and one box per line, origin top left."""

    page_size: list[float]  # [width, height]
    boxes: list[list[float]]  # [[x0, y0, x1, y1], ...]


@dataclass(frozen=True)
class QuoteCheck:
    """The result of check_quote."""

    ok: bool
    reason: str  # "found", or why not, in a sentence a reader can act on
    found_on: list[int] = field(
        default_factory=list
    )  # nearby pages holding the quote, when the cited one does not


def key(text: str) -> str:
    """Letters and digits only, lower case, after compatibility folding: what matching compares."""
    text = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in text if ch.isalnum())


def _version(pdf: Path) -> tuple[str, int, int]:
    """The file's identity for the caches: a changed file is read again."""
    st = pdf.stat()
    return str(pdf.resolve()), st.st_size, st.st_mtime_ns


@lru_cache(maxsize=4096)
def _page_text(version: tuple[str, int, int], page: int) -> str:
    return render.page_text(Path(version[0]), page)


@lru_cache(maxsize=1024)
def _page_bbox(version: tuple[str, int, int], page: int) -> str:
    return render.page_bbox(Path(version[0]), page)


@lru_cache(maxsize=256)
def _page_count(version: tuple[str, int, int]) -> int:
    return render.page_count(Path(version[0]))


def check_quote(pdf: str | Path, page: int, quote: str, search_near: int = SEARCH_NEAR) -> QuoteCheck:
    """Whether `quote` is on page `page` of `pdf`; if not, why not, and which nearby pages hold it."""
    path = Path(pdf).expanduser()
    if not path.is_file():
        return QuoteCheck(False, "document not found")
    q = key(quote)
    if len(q) < MIN_CHARS:
        return QuoteCheck(False, f"quote too short ({len(q)} letters and digits; at least {MIN_CHARS})")
    version = _version(path)
    n = _page_count(version)
    if not 1 <= page <= n:
        return QuoteCheck(False, f"page {page} outside the document (1 to {n})")
    text = _page_text(version, page)
    if q in key(text):
        return QuoteCheck(True, "found")
    near = [
        k
        for k in range(max(1, page - search_near), min(n, page + search_near) + 1)
        if k != page and q in key(_page_text(version, k))
    ]
    if near:
        return QuoteCheck(False, f"not on page {page}; found on page {', '.join(map(str, near))}", near)
    if len(key(text)) < 50:
        return QuoteCheck(
            False,
            f"page {page} has almost no extractable text (a blank or figure page, or a scanned image "
            "without a text layer); the quote cannot be checked there",
        )
    return QuoteCheck(False, f"not on page {page}")


_WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>')
_PAGE = re.compile(r'<page width="([\d.]+)" height="([\d.]+)">')


def quote_boxes(pdf: str | Path, page: int, quote: str) -> QuoteBoxes | None:
    """Where `quote` sits on page `page`: the page size in points and one box per text line, origin top left.

    Words and their boxes come from pdftotext -bbox; the quote is matched on letters and digits as in
    check_quote.
    None when the quote is not found word by word on that page (or is empty).
    """
    path = Path(pdf).expanduser()
    q = key(quote)
    if not q or not path.is_file():
        return None
    raw = _page_bbox(_version(path), page)
    size = _PAGE.search(raw)
    words = [
        (float(a), float(b), float(c), float(d), html.unescape(w)) for a, b, c, d, w in _WORD.findall(raw)
    ]
    if not size or not words:
        return None
    owner: list[int] = []  # for each letter or digit of the page, the word it belongs to
    text: list[str] = []
    for i, word in enumerate(words):
        k = key(word[4])
        text.append(k)
        owner.extend([i] * len(k))
    at = "".join(text).find(q)
    if at < 0:
        return None
    lines: list[list[float]] = []
    for i in sorted(set(owner[at : at + len(q)])):
        x0, y0, x1, y1, _ = words[i]
        # The same line: the tops agree within most of a word's height, and the word does not go back left.
        if lines and abs(lines[-1][1] - y0) < 0.6 * (y1 - y0) and x0 >= lines[-1][0] - 1:
            ln = lines[-1]
            ln[0], ln[1], ln[2], ln[3] = min(ln[0], x0), min(ln[1], y0), max(ln[2], x1), max(ln[3], y1)
        else:
            lines.append([x0, y0, x1, y1])
    return {
        "page_size": [float(size.group(1)), float(size.group(2))],
        "boxes": [[round(v, 1) for v in box] for box in lines],
    }
