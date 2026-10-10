"""Tests in a real browser (headless Chromium, through Playwright): the viewer in a tab and in the side pane.

They are skipped where Playwright or its Chromium is not installed (`pip install -e ".[dev]"` and then
`python -m playwright install chromium`).
"""

from __future__ import annotations

import functools
import json
import os
import threading
from collections.abc import Iterator
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

import pdfpage
from pdfpage import server, store

sync_api = pytest.importorskip("playwright.sync_api")

LONG_TITLE = ("A citation title long enough to fill several lines of a narrow window " * 6)[:300]
DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"Chromium for Playwright is not installed: {e}")
        yield b
        b.close()


def _serve(handler: Any) -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def tab(sample_pdf: Path, quote: str) -> Iterator[str]:
    """The pdfpage server with the sample published three ways: at its quote, with a 300-character title, and
    in the page-image view (written to the registry directly; publish() would also point Tailscale at it)."""
    docs = {
        "sample": store.Document(
            slug="sample", pdf=str(sample_pdf), pages=3, page=3, title="Sample", quote=quote
        ),
        "long": store.Document(
            slug="long",
            pdf=str(sample_pdf),
            pages=3,
            page=3,
            title=LONG_TITLE,
            subtitle=LONG_TITLE,
            quote=quote,
        ),
        "images": store.Document(
            slug="images", pdf=str(sample_pdf), pages=3, page=3, quote=quote, mode="images"
        ),
    }
    store.save(docs)
    yield from (f"{base}{store.PREFIX}" for base in _serve(server.Handler))


@pytest.fixture
def host(tmp_path: Path, sample_pdf: Path, quote: str) -> Iterator[str]:
    """A host web page that uses the side pane: the viewer's files under pdfpage/, a record file, the PDF."""
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    (site / "pdf").mkdir()
    os.symlink(pdfpage.assets_dir(), site / "pdfpage")
    os.symlink(sample_pdf, site / "pdf" / "sample.pdf")
    records = {
        "c1": pdfpage.citation_record("../pdf/sample.pdf", 3, title="Sample", quote=quote, pdf=sample_pdf),
        "c2": pdfpage.citation_record("../pdf/sample.pdf", 3, title=LONG_TITLE, quote=quote, pdf=sample_pdf),
    }
    (site / "data" / "citations.json").write_text(json.dumps(records), encoding="utf-8")
    url = pdfpage.viewer_url("data/citations.json", assets="pdfpage/", id="c1")
    url2 = pdfpage.viewer_url("data/citations.json", assets="pdfpage/", id="c2")
    (site / "index.html").write_text(
        f"""<!doctype html><html lang="en" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Host</title>
<link rel="stylesheet" href="pdfpage/pane.css"><script src="pdfpage/pane.js" defer></script></head>
<body><main><p>A page that cites a document.</p>
<button type="button" id="cite" data-pdfpage="{url}" data-pdfpage-label="Cited document">Show</button>
<a id="cite2" href="{url2}" data-pdfpage>Long</a>
<div id="slot"></div>
<button type="button" id="inline" data-pdfpage="{url}" data-pdfpage-target="#slot">In the page</button>
</main></body></html>""",
        encoding="utf-8",
    )
    handler = functools.partial(_QuietFiles, directory=str(site))
    yield from _serve(handler)


class _QuietFiles(SimpleHTTPRequestHandler):
    def guess_type(self, path: str | os.PathLike[str]) -> str:
        # The viewer's own media types, as a host application would serve them (a system's may lack .mjs).
        return pdfpage.content_type(os.fspath(path))

    def log_message(self, fmt: str, *args: object) -> None:
        pass


def _open(browser: Any, url: str, viewport: dict[str, int] = DESKTOP, scheme: str = "dark") -> Any:
    page = browser.new_page(viewport=viewport, color_scheme=scheme)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.errors = errors
    page.goto(url)
    page.wait_for_selector("html[data-pp-state=ready]", timeout=20000)
    return page


def _scale(page: Any) -> float:
    return float(page.locator("#pct").inner_text().rstrip("%"))


# ---- the viewer in a tab --------------------------------------------------------------------


def test_viewer_opens_at_the_quote_and_draws_its_box(browser: Any, tab: str) -> None:
    page = _open(browser, f"{tab}/sample/")
    assert page.locator(".page[data-page-number='3'] .pp-mark.pp-q").count() == 2, (
        "one box per line of the quote"
    )
    assert page.locator("#num").input_value() == "3"
    assert page.url.endswith("/sample/#p=3"), "the address keeps the page, and the <base> does not change it"
    box = page.locator(".pp-mark.pp-q").first.bounding_box()
    stage = page.locator("#container").bounding_box()
    assert stage["y"] <= box["y"] <= stage["y"] + stage["height"], "the quote is in view"
    assert not page.errors
    page.close()


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
@pytest.mark.parametrize("scheme", ["dark", "light"])
def test_toolbar_buttons_are_never_cut_off(
    browser: Any, tab: str, viewport: dict[str, int], scheme: str
) -> None:
    page = _open(browser, f"{tab}/long/", viewport, scheme)
    assert page.evaluate("document.documentElement.dataset.theme") == scheme
    stage_top = page.locator("#stage").bounding_box()["y"]
    buttons = page.locator(".pp-bar button:visible, .pp-bar input:visible")
    assert buttons.count() >= 10
    for i in range(buttons.count()):
        b = buttons.nth(i).bounding_box()
        assert b["x"] >= 0 and b["x"] + b["width"] <= viewport["width"], buttons.nth(i).inner_text()
        assert b["y"] + b["height"] <= stage_top, "every button sits above the page, none behind it"
    title = page.locator("#title")
    assert title.get_attribute("title") == LONG_TITLE, "the full title is the tooltip"
    assert title.bounding_box()["height"] < 30, "the title is one line until it is opened"
    page.click("#expand")
    assert title.bounding_box()["height"] > 30
    page.close()


def test_zoom_buttons_and_keys(browser: Any, tab: str) -> None:
    page = _open(browser, f"{tab}/sample/")
    start = _scale(page)
    page.click("#zoomIn")
    page.wait_for_function(f"parseFloat(document.getElementById('pct').textContent) > {start}")
    assert _scale(page) == pytest.approx(start * 1.2, abs=1.5)
    page.click("#zoomOut")
    page.wait_for_function(f"Math.abs(parseFloat(document.getElementById('pct').textContent) - {start}) < 2")
    for _ in range(12):
        page.keyboard.press("+")
    page.wait_for_function("document.getElementById('pct').textContent === '400%'")
    assert page.locator("#zoomIn").is_disabled(), "400 % is the largest size"
    page.click("#fit")
    page.wait_for_function("document.getElementById('fit').getAttribute('aria-pressed') === 'true'")
    page.close()


def test_hand_tool_pans_in_both_directions(browser: Any, tab: str) -> None:
    page = _open(browser, f"{tab}/sample/")
    for _ in range(4):
        page.click("#zoomIn")
    page.wait_for_timeout(400)
    page.click("#toolHand")
    container = page.locator("#container")
    assert container.evaluate("e => getComputedStyle(e).cursor") == "grab"
    before = container.evaluate("e => [e.scrollLeft, e.scrollTop]")
    c = container.bounding_box()
    page.mouse.move(c["x"] + 600, c["y"] + 500)
    page.mouse.down()
    page.mouse.move(c["x"] + 450, c["y"] + 350, steps=8)
    page.mouse.up()
    after = container.evaluate("e => [e.scrollLeft, e.scrollTop]")
    assert after[0] - before[0] == pytest.approx(150, abs=2)
    assert after[1] - before[1] == pytest.approx(150, abs=2)
    page.close()


def test_space_bar_holds_the_hand(browser: Any, tab: str) -> None:
    page = _open(browser, f"{tab}/sample/")
    container = page.locator("#container")
    container.focus()
    page.keyboard.down(" ")
    assert container.evaluate("e => e.classList.contains('pp-tool-hand')")
    page.keyboard.up(" ")
    assert container.evaluate("e => e.classList.contains('pp-tool-highlight')")
    page.close()


def _select_first_line(page: Any) -> None:
    span = page.locator(".page[data-page-number='3'] .textLayer span").first
    b = span.bounding_box()
    page.mouse.move(b["x"] + 1, b["y"] + b["height"] / 2)
    page.mouse.down()
    page.mouse.move(b["x"] + b["width"] - 1, b["y"] + b["height"] / 2, steps=6)
    page.mouse.up()


def test_highlight_is_kept_in_the_browser_and_can_be_removed(browser: Any, tab: str) -> None:
    page = _open(browser, f"{tab}/sample/")
    page.wait_for_selector(".page[data-page-number='3'] .textLayer span")
    _select_first_line(page)
    marks = page.locator(".pp-mark.pp-h")
    assert marks.count() == 1
    stored = page.evaluate(
        "Object.entries(localStorage).filter(([k]) => k.startsWith('pdfpage-highlights:'))"
    )
    assert len(stored) == 1
    key, value = stored[0]
    assert key.endswith(pdfpage.file_sha256(store.load()["sample"].pdf)), "keyed by the document's SHA-256"
    item = json.loads(value)["items"][0]
    assert item["page"] == 3 and "PAGE THREE" in item["text"]
    quote_box = page.locator(".pp-mark.pp-q").first.bounding_box()
    mark = marks.first.bounding_box()
    assert abs(mark["y"] - quote_box["y"]) < 8, "the highlight sits on the line, where the quote's box is"

    page.reload()
    page.wait_for_selector("html[data-pp-state=ready]")
    page.wait_for_selector(".pp-mark.pp-h")
    assert page.locator(".pp-mark.pp-h").count() == 1, "restored from the browser's storage"
    assert "(1)" in page.locator("#clearHl").inner_text()

    m = page.locator(".pp-mark.pp-h").first.bounding_box()
    page.mouse.click(m["x"] + 4, m["y"] + m["height"] / 2)
    page.click(".pp-pop button")
    assert page.locator(".pp-mark.pp-h").count() == 0
    assert (
        page.evaluate("Object.keys(localStorage).filter(k => k.startsWith('pdfpage-highlights:')).length")
        == 0
    )
    assert page.locator(".pp-mark.pp-q").count() == 2, "the quote's own box stays"
    page.close()


def test_page_images_view(browser: Any, tab: str) -> None:
    page = _open(browser, f"{tab}/images/")
    img = page.locator("#img")
    assert img.get_attribute("src").endswith("/images/page-3.png")
    assert img.evaluate("e => e.naturalWidth") > 0
    assert page.locator("#imgPage .pp-mark.pp-q").count() == 2
    page.click("#prev")
    page.wait_for_function("document.getElementById('img').src.endsWith('page-2.png')")
    page.close()


def test_legacy_build_opens_the_document(browser: Any, host: str) -> None:
    url = pdfpage.viewer_url("data/citations.json", assets="pdfpage/", id="c1")
    page = _open(browser, f"{host}/{url}&build=legacy")
    assert page.locator(".pp-mark.pp-q").count() == 2
    assert not page.errors
    page.close()


# ---- the side pane --------------------------------------------------------------------------


def _frame_ready(page: Any) -> Any:
    frame = page.frame_locator("iframe.pdfpage-pane-frame").first
    frame.locator("html[data-pp-state=ready]").wait_for(state="attached", timeout=20000)
    return frame


def test_pane_opens_beside_the_page_and_closes(browser: Any, host: str) -> None:
    page = browser.new_page(viewport=DESKTOP)
    page.goto(f"{host}/index.html")
    margin = page.evaluate("getComputedStyle(document.body).marginRight")
    page.click("#cite")
    pane = page.locator("aside.pdfpage-pane")
    assert pane.is_visible()
    frame = _frame_ready(page)
    assert frame.locator(".pp-mark.pp-q").count() == 2
    assert frame.locator("html").get_attribute("data-theme") == "dark", "the viewer follows the host's theme"
    box = pane.bounding_box()
    assert box["x"] + box["width"] == DESKTOP["width"] and box["x"] > DESKTOP["width"] / 3, (
        "a pane on the right"
    )
    assert page.evaluate("getComputedStyle(document.body).marginRight") == f"{box['width']}px", (
        "the page moves aside"
    )
    assert page.locator("#cite").get_attribute("aria-expanded") == "true"
    assert "viewer.html?record=" in page.locator(".pdfpage-pane-tab").get_attribute("href")
    assert pane.locator(".pdfpage-pane-label").inner_text() == "Cited document"

    page.evaluate("document.documentElement.dataset.theme = 'light'")
    page.wait_for_function(
        "document.querySelector('iframe.pdfpage-pane-frame')"
        ".contentDocument.documentElement.dataset.theme === 'light'"
    )
    assert pane.get_attribute("data-theme") == "light"

    page.click(".pdfpage-pane-close")
    assert not pane.is_visible()
    assert page.locator("#cite").get_attribute("aria-expanded") == "false"
    assert page.evaluate("getComputedStyle(document.body).marginRight") == margin
    page.close()


def test_pane_width_is_dragged_and_remembered(browser: Any, host: str) -> None:
    page = browser.new_page(viewport=DESKTOP)
    page.goto(f"{host}/index.html")
    page.click("#cite")
    grip = page.locator(".pdfpage-pane-grip").bounding_box()
    page.mouse.move(grip["x"] + 5, 400)
    page.mouse.down()
    page.mouse.move(DESKTOP["width"] - 900, 400, steps=5)
    page.mouse.up()
    assert page.locator("aside.pdfpage-pane").bounding_box()["width"] == pytest.approx(900, abs=2)
    page.keyboard.press("Escape")
    page.reload()
    page.click("#cite")
    assert page.locator("aside.pdfpage-pane").bounding_box()["width"] == pytest.approx(900, abs=2)
    page.close()


def test_pane_covers_a_phone_screen(browser: Any, host: str) -> None:
    page = browser.new_page(viewport=PHONE)
    page.goto(f"{host}/index.html")
    page.click("#cite2")
    frame = _frame_ready(page)
    box = page.locator("aside.pdfpage-pane").bounding_box()
    assert (box["x"], box["y"], box["width"], box["height"]) == (0, 0, PHONE["width"], PHONE["height"])
    bar = page.locator(".pdfpage-pane-bar")
    for part in (".pdfpage-pane-tab", ".pdfpage-pane-close"):
        b = bar.locator(part).bounding_box()
        assert b["x"] + b["width"] <= PHONE["width"], part
    assert frame.locator("#title").get_attribute("title") == LONG_TITLE
    page.locator(".pdfpage-pane-close").click()
    assert not page.locator("aside.pdfpage-pane").is_visible()
    page.close()


def test_pane_inside_a_host_element(browser: Any, host: str) -> None:
    page = browser.new_page(viewport=DESKTOP)
    page.goto(f"{host}/index.html")
    page.click("#inline")
    assert page.locator("#slot > .pdfpage-pane-inline").is_visible()
    assert page.locator("aside.pdfpage-pane").count() == 0, "no floating pane"
    _frame_ready(page)
    page.close()
