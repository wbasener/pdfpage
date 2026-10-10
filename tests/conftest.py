"""Shared fixtures. The tests build their own small PDF, so nothing needs downloading."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from pdfpage import store


@pytest.fixture(autouse=True)
def _temporary_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep every test out of the real ~/.local/share/pdfpage."""
    monkeypatch.setattr(store, "HOME", tmp_path / "home")
    yield


# The sample's pages. Page three has two lines, so a quote can run from one line onto the next.
PAGES = [
    ["PAGE ONE"],
    ["PAGE TWO"],
    ["PAGE THREE with a needle in it", "and a second line that carries the quote on"],
]
QUOTE = "a needle in it and a second line"  # runs across the two lines of page three


@pytest.fixture(scope="session")
def quote() -> str:
    """A quote on page three of the sample, running from its first line onto its second."""
    return QUOTE


@pytest.fixture(scope="session")
def sample_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A three-page PDF whose pages say PAGE ONE, PAGE TWO and PAGE THREE (with a second line)."""
    pdf = tmp_path_factory.mktemp("pdf") / "sample.pdf"
    pdf.write_bytes(minimal_pdf(PAGES))
    return pdf


@pytest.fixture(scope="session")
def bottom_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Three pages; on page two the quote (BOTTOM_QUOTE) is the last line, near the foot of the page."""
    pdf = tmp_path_factory.mktemp("pdf") / "bottom.pdf"
    pdf.write_bytes(minimal_pdf([["PAGE ONE"], ["PAGE TWO", BOTTOM_QUOTE], ["PAGE THREE"]], last_line_y=60))
    return pdf


BOTTOM_QUOTE = "the quoted line at the foot of the second page"


@pytest.fixture(scope="session")
def bottom_quote() -> str:
    return BOTTOM_QUOTE


def minimal_pdf(pages: list[list[str]], last_line_y: int | None = None) -> bytes:
    """A valid PDF with the given lines of text on each page, written out directly, from the top down; with
    last_line_y, each page's last line is placed that many points above the foot of the page instead."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    kids, contents = [], []
    for lines in pages:
        shown = " ".join(f"({text}) Tj 0 -30 Td" for text in lines)
        if last_line_y is not None and len(lines) > 1:
            *head, last = lines
            shown = " ".join(f"({text}) Tj 0 -30 Td" for text in head)
            shown += f" ET BT /F1 24 Tf 72 {last_line_y} Td ({last}) Tj"
        stream = f"BT /F1 24 Tf 72 700 Td {shown} ET".encode()
        contents.append(add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)))
    pages_obj = len(objects) + len(pages) + 1
    for content in contents:
        kids.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>" % (pages_obj, font, content)
            )
        )
    kid_refs = b" ".join(b"%d 0 R" % k for k in kids)
    add(b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kid_refs, len(kids)))
    root = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_obj)

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    start = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets[1:])
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, root, start)
    return bytes(out)
