"""Tests of the Python side: reading the PDF, publishing, quotes, records for a host, and the server."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import pdfpage
from pdfpage import render, server, store

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


def test_viewer_html_carries_the_record_and_escapes_it(sample_pdf: Path, quote: str) -> None:
    doc = store.Document(
        slug="s", pdf=str(sample_pdf), pages=3, page=3, title="A & B </script><script>", quote=quote
    )
    page = server.viewer_html(doc)
    head, _, _ = page.partition("</head>")
    assert '<base href="../_viewer/' in head, "the viewer's own files come from one shared address"
    assert "<title>A &amp; B &lt;/script&gt;&lt;script&gt;</title>" in head
    data = head.split('id="pdfpage-record">')[1].split("</script>")[0]
    assert "<" not in data, "nothing in the record can end the script element"
    rec = json.loads(data)
    assert (rec["doc"], rec["page"], rec["pages"], rec["zoom"], rec["view"]) == (
        "document.pdf",
        3,
        3,
        125,
        "pdf",
    )
    assert rec["title"] == "A & B </script><script>"
    assert rec["images"] == "page-{page}.png"
    assert rec["highlight"] is not None and len(rec["highlight"]["boxes"]) == 2, (
        "the quote is found on two lines"
    )
    assert rec["sha256"] == hashlib.sha256(sample_pdf.read_bytes()).hexdigest()


def test_viewer_opens_in_the_chosen_view_and_zoom(sample_pdf: Path) -> None:
    doc = store.Document(slug="s", pdf=str(sample_pdf), pages=3, page=2, mode="images", zoom=200)
    rec = server.record(doc)
    assert (rec["view"], rec["zoom"], rec["highlight"]) == ("images", 200, None)


def test_publish_rejects_a_bad_view_or_zoom(sample_pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "start_background", lambda: None)
    with pytest.raises(ValueError, match="mode"):
        pdfpage.publish(sample_pdf, mode="sideways")
    with pytest.raises(ValueError, match="zoom"):
        pdfpage.publish(sample_pdf, zoom=0)


def test_index_lists_documents(sample_pdf: Path) -> None:
    docs = {"a": store.Document(slug="a", pdf=str(sample_pdf), pages=3, page=2, title="Alpha")}
    assert 'href="a/#p=2"' in server.index_html(docs)
    assert "none yet" in server.index_html({})


# ---- quotes ---------------------------------------------------------------------------------


def test_check_quote(sample_pdf: Path, quote: str) -> None:
    assert pdfpage.check_quote(sample_pdf, 3, quote) == pdfpage.QuoteCheck(True, "found")
    near = pdfpage.check_quote(sample_pdf, 2, quote)
    assert (near.ok, near.found_on) == (False, [3])
    assert "found on page 3" in near.reason
    assert "too short" in pdfpage.check_quote(sample_pdf, 3, "a needle").reason
    assert "outside" in pdfpage.check_quote(sample_pdf, 9, quote).reason
    assert pdfpage.check_quote(sample_pdf.with_name("missing.pdf"), 1, quote).reason == "document not found"


def test_quote_matching_ignores_case_spaces_and_punctuation(sample_pdf: Path) -> None:
    assert pdfpage.check_quote(sample_pdf, 3, "A NEEDLE, in it - and a second   line!").ok


def test_quote_boxes_one_box_per_line(sample_pdf: Path, quote: str) -> None:
    found = pdfpage.quote_boxes(sample_pdf, 3, quote)
    assert found is not None
    assert found["page_size"] == [612.0, 792.0]
    first, second = found["boxes"]
    assert first[1] < second[1], "the first line is above the second, measured from the top"
    assert all(0 <= v <= 612 for box in found["boxes"] for v in box)
    assert pdfpage.quote_boxes(sample_pdf, 2, quote) is None, "not on that page"
    assert pdfpage.quote_boxes(sample_pdf, 3, "") is None


# ---- a host application's records -----------------------------------------------------------


ASSETS = [
    "viewer.html",
    "viewer.js",
    "viewer.css",
    "pane.js",
    "pane.css",
    "fonts/OFL-NotoSans.txt",
    "pdfjs/LICENSE",
    "pdfjs/VERSION",
    "pdfjs/build/pdf.min.mjs",
    "pdfjs/build/pdf.worker.min.mjs",
    "pdfjs/web/pdf_viewer.mjs",
    "pdfjs/web/pdf_viewer.css",
    "pdfjs/legacy/build/pdf.min.mjs",
    "pdfjs/legacy/web/pdf_viewer.mjs",
    "pdfjs/standard_fonts/LiberationSans-Regular.ttf",
]
OWN_TEXT = ["viewer.html", "viewer.js", "viewer.css", "pane.js", "pane.css", "pdfjs/VERSION"]
EM_DASH = chr(0x2014)  # never in this package's own writing


def test_assets_are_in_the_package() -> None:
    root = pdfpage.assets_dir()
    for name in ASSETS:
        assert (root / name).is_file(), name
    assert "Apache License" in (root / "pdfjs/LICENSE").read_text(encoding="utf-8")
    assert pdfpage.content_type("x/pdf.min.mjs").startswith("text/javascript")
    assert pdfpage.content_type("a.wasm") == "application/wasm"


def test_no_asset_is_left_out_of_git() -> None:
    """A file of the viewer that git ignores would be missing from a clone and from GitHub's checks."""
    repo = Path(__file__).resolve().parents[1]
    if not (repo / ".git").exists() or not shutil.which("git"):
        pytest.skip("not a git clone")
    files = [str(f.relative_to(repo)) for f in pdfpage.assets_dir().rglob("*") if f.is_file()]
    ignored = subprocess.run(
        ["git", "check-ignore", "--no-index", *files], cwd=repo, capture_output=True, text=True
    ).stdout.split()
    assert ignored == []


def test_no_em_dash_in_our_own_writing() -> None:
    repo = Path(__file__).resolve().parents[1]
    files = [pdfpage.assets_dir() / n for n in OWN_TEXT]
    files += [*repo.glob("*.md"), *repo.glob("src/pdfpage/*.py"), *repo.glob("tests/*.py")]
    for f in files:
        assert EM_DASH not in f.read_text(encoding="utf-8"), f


def test_citation_record(sample_pdf: Path, quote: str) -> None:
    rec = pdfpage.citation_record(
        "../pdf/sample.pdf", 3, title="Sample", quote=quote, printed="3", pdf=sample_pdf
    )
    assert rec["doc"] == "../pdf/sample.pdf"
    assert rec["printed"] == "", "a printed page equal to the file's own is not repeated"
    assert (
        rec["sha256"]
        == pdfpage.file_sha256(sample_pdf)
        == hashlib.sha256(sample_pdf.read_bytes()).hexdigest()
    )
    assert rec["highlight"] == pdfpage.quote_boxes(sample_pdf, 3, quote)
    assert rec["zoom"] == "page-width"
    json.dumps(rec)  # the record is plain JSON


def test_citation_record_rejects_what_the_viewer_cannot_use() -> None:
    for bad in ({"page": 0}, {"zoom": 5}, {"zoom": "huge"}, {"view": "sideways"}, {"images": "page.png"},
                {"view": "images"}, {"page": 4, "pages": 3},
                {"boxes": {"page_size": [612, 792], "boxes": [[10, 10, 5, 20]]}}):  # fmt: skip
        with pytest.raises(ValueError):
            pdfpage.citation_record("a.pdf", **bad)


def test_viewer_url() -> None:
    assert pdfpage.viewer_url("data/citations.json", assets="pdfpage/", id="c 1") == (
        "pdfpage/viewer.html?record=../data/citations.json&id=c%201"
    )
    assert (
        pdfpage.viewer_url("/data/c.json", assets="/pdfpage", page=4)
        == "/pdfpage/viewer.html?record=/data/c.json#p=4"
    )
    assert pdfpage.viewer_url("c.json") == "viewer.html?record=c.json"
    with pytest.raises(ValueError, match="both relative"):
        pdfpage.viewer_url("data/c.json", assets="/pdfpage/")


# ---- the server -----------------------------------------------------------------------------


@pytest.fixture
def running(sample_pdf: Path, quote: str) -> Iterator[str]:
    """The pdfpage server on a free loopback port, with the sample published as "sample" (written to the
    registry directly: publish() would also point Tailscale at it)."""
    store.save({"sample": store.Document(slug="sample", pdf=str(sample_pdf), pages=3, page=3, quote=quote)})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}{store.PREFIX}"
    httpd.shutdown()
    httpd.server_close()


def _get(url: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, dict(res.headers), res.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_server_sends_the_viewer_and_its_files(running: str) -> None:
    status, _, body = _get(f"{running}/sample/")
    assert status == 200 and b'id="pdfpage-record"' in body
    status, headers, _ = _get(f"{running}/_viewer/0/pdfjs/build/pdf.min.mjs")
    assert status == 200 and headers["Content-Type"].startswith("text/javascript")
    assert _get(f"{running}/_viewer/0/../../store.py")[0] == 404, "nothing outside the viewer's folder"
    assert _get(f"{running}/_viewer/0/%2e%2e/store.py")[0] == 404
    assert _get(f"{running}/nothing/")[0] == 404


def test_server_redirects_to_the_folder(running: str) -> None:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: object, **kwargs: object) -> None:
            return None

    opener = urllib.request.build_opener(NoRedirect)
    with pytest.raises(urllib.error.HTTPError) as e:
        opener.open(f"{running}/sample")
    assert e.value.code == 301 and e.value.headers["Location"] == "sample/"


def test_server_sends_part_of_the_pdf(running: str, sample_pdf: Path) -> None:
    whole = sample_pdf.read_bytes()
    status, headers, body = _get(f"{running}/sample/document.pdf", {"Range": "bytes=10-19"})
    assert (status, body) == (206, whole[10:20])
    assert headers["Content-Range"] == f"bytes 10-19/{len(whole)}"
    status, _, body = _get(f"{running}/sample/document.pdf", {"Range": "bytes=-5"})
    assert (status, body) == (206, whole[-5:])
    status, headers, body = _get(f"{running}/sample/document.pdf")
    assert (status, body, headers["Accept-Ranges"]) == (200, whole, "bytes")
    assert _get(f"{running}/sample/document.pdf", {"Range": f"bytes={len(whole)}-"})[0] == 416
