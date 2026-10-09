"""Tests. They build a small PDF with poppler's own tools, so nothing else is needed."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

import pdfpage
from pdfpage import render, server, store


@pytest.fixture(autouse=True)
def _temporary_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep every test out of the real ~/.local/share/pdfpage."""
    monkeypatch.setattr(store, "HOME", tmp_path / "home")
    yield


@pytest.fixture(scope="session")
def sample_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A three-page PDF whose pages say PAGE ONE, PAGE TWO and PAGE THREE."""
    out = tmp_path_factory.mktemp("pdf")
    text = out / "sample.txt"
    text.write_text("PAGE ONE\n\f PAGE TWO\n\f PAGE THREE with a needle in it\n")
    pdf = out / "sample.pdf"
    try:
        subprocess.run(["pstopdf", str(text)], check=True, capture_output=True)
    except FileNotFoundError:
        # ps2pdf and pstopdf are not always present; build the PDF by hand instead.
        pdf.write_bytes(_minimal_pdf(["PAGE ONE", "PAGE TWO", "PAGE THREE with a needle in it"]))
    return pdf


def _minimal_pdf(pages: list[str]) -> bytes:
    """A valid PDF with one line of text on each page, written out directly."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    kids, contents = [], []
    for text in pages:
        stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode()
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


# ---- reading the PDF ------------------------------------------------------------------------


def test_page_count(sample_pdf: Path) -> None:
    assert render.page_count(sample_pdf) == 3


def test_find_page_ignores_line_breaks(sample_pdf: Path) -> None:
    assert render.find_page(sample_pdf, "needle") == 3
    assert render.find_page(sample_pdf, "PAGE   three WITH a needle") == 3
    assert render.find_page(sample_pdf, "haystack") is None


def test_render_page_caches(sample_pdf: Path, tmp_path: Path) -> None:
    out = tmp_path / "pages"
    first = render.render_page(sample_pdf, 2, out, dpi=50)
    assert first.exists() and first.name == "page-2.png"
    stamp = first.stat().st_mtime_ns
    assert render.render_page(sample_pdf, 2, out, dpi=50).stat().st_mtime_ns == stamp
    assert not list(out.glob(".tmp-*")), "no half-written files are left behind"


# ---- publishing -----------------------------------------------------------------------------


def test_publish_records_the_document(sample_pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "start_background", lambda: None)
    monkeypatch.setattr(pdfpage.tailnet, "base_url", lambda: "https://example.ts.net/pdf")
    url = pdfpage.publish(sample_pdf, page=2, title="Sample")
    assert url == "https://example.ts.net/pdf/sample/#p=2"
    doc = pdfpage.published()["sample"]
    assert (doc.pages, doc.page, doc.title) == (3, 2, "Sample")
    assert doc.pdf == str(sample_pdf), "the PDF stays where it is"


def test_publish_by_phrase(sample_pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "start_background", lambda: None)
    monkeypatch.setattr(pdfpage.tailnet, "base_url", lambda: "https://example.ts.net/pdf")
    assert pdfpage.publish(sample_pdf, find="needle").endswith("#p=3")
    assert pdfpage.published()["sample"].quote == "needle", "the phrase becomes the quote"


def test_publish_rejects_bad_input(sample_pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "start_background", lambda: None)
    with pytest.raises(FileNotFoundError):
        pdfpage.publish(sample_pdf.with_name("missing.pdf"))
    with pytest.raises(ValueError, match="outside"):
        pdfpage.publish(sample_pdf, page=99)
    with pytest.raises(LookupError, match="character recognition"):
        pdfpage.publish(sample_pdf, find="not in this document")


def test_unpublish_keeps_the_pdf(sample_pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "start_background", lambda: None)
    monkeypatch.setattr(pdfpage.tailnet, "base_url", lambda: "https://example.ts.net/pdf")
    pdfpage.publish(sample_pdf)
    assert pdfpage.unpublish("sample") is True
    assert pdfpage.published() == {}
    assert sample_pdf.exists()
    assert pdfpage.unpublish("sample") is False


def test_slugify() -> None:
    assert store.slugify("WMC Report (1999) A60645") == "wmc-report-1999-a60645"
    assert store.slugify("!!!") == "document"


# ---- the pages the server sends --------------------------------------------------------------


def test_viewer_html_shows_the_page_and_escapes_the_title(sample_pdf: Path) -> None:
    doc = store.Document(slug="s", pdf=str(sample_pdf), pages=3, page=2, title="A & B <script>")
    page = server.viewer_html(doc)
    assert 'const N = 3, PDF = "document.pdf", START = 2;' in page
    assert "<script>" not in page.split("</header>")[0], "the title is escaped, not run"
    assert "A &amp; B" in page


def test_index_lists_documents(sample_pdf: Path) -> None:
    docs = {"a": store.Document(slug="a", pdf=str(sample_pdf), pages=3, page=2, title="Alpha")}
    assert 'href="a/#p=2"' in server.index_html(docs)
    assert "none yet" in server.index_html({})
