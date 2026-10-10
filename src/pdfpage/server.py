"""The small web server that shows the published documents.

It listens on the loopback address only (127.0.0.1), so the machine's firewall is never involved
and nothing is exposed to the local network. Tailscale is what makes it reachable from your other
devices; see tailnet.py.
"""

from __future__ import annotations

import html
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from . import host, render, store

ASSETS = (
    "_viewer"  # the path under PREFIX that serves the viewer's files; no document's name can start with _
)


def record(doc: store.Document) -> dict[str, object]:
    """The record the viewer reads for a published document (host.citation_record)."""
    return host.citation_record(
        "document.pdf",
        doc.page,
        title=doc.title or doc.slug,
        subtitle=doc.subtitle,
        quote=doc.quote,
        pages=doc.pages,
        zoom=doc.zoom,
        images="page-{page}.png",
        view="images" if doc.mode == "images" else "pdf",
        pdf=doc.pdf,
    )


def viewer_html(doc: store.Document) -> str:
    """The viewer page of one document: the package's viewer.html with the document's record written into it.

    The page's own files are fetched from PREFIX/_viewer/<version>/ (the <base> element), so a browser keeps
    them between documents and fetches them again only after an upgrade.
    """
    from . import __version__  # here, not at the top: the package imports this module before it sets it

    data = json.dumps(record(doc), ensure_ascii=False)
    # Inside <script>, "</script>" would end the element; escaped, the JSON reads the same.
    data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    page = (host.assets_dir() / "viewer.html").read_text(encoding="utf-8")
    head = f'<head>\n<base href="../{ASSETS}/{__version__}/">'
    script = f'<script type="application/json" id="pdfpage-record">{data}</script>\n</head>'
    return (
        page.replace("<head>", head, 1)
        .replace("</head>", script, 1)
        .replace("<title>pdfpage</title>", f"<title>{html.escape(doc.title or doc.slug)}</title>", 1)
    )


def index_html(docs: dict[str, store.Document]) -> str:
    rows = "\n".join(
        f'<li><a href="{html.escape(s)}/#p={d.page}">{html.escape(d.title or s)}</a>'
        f' <span class="sub">{d.pages} pages</span></li>'
        for s, d in sorted(docs.items(), key=lambda kv: (kv[1].title or kv[0]).lower())
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>pdfpage</title>'
        "<style>:root{color-scheme:dark}body{margin:0;padding:18px;background:#1f2329;color:#e8eaed;"
        'font:15px/1.7 "Noto Sans","Segoe UI",Arial,sans-serif}a{color:#9cc3ff}'
        ".sub{color:#b0b5bf;font-size:13px}ul{padding-left:20px}</style></head><body>"
        f"<h1>Published documents</h1><ul>{rows or '<li>none yet</li>'}</ul></body></html>"
    )


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # The name do_GET is fixed by BaseHTTPRequestHandler.
    def do_GET(self) -> None:
        path = unquote(self.path.split("?")[0].split("#")[0])
        if not path.startswith(store.PREFIX):
            self.send_error(404)
            return
        rest = path[len(store.PREFIX) :].strip("/")
        docs = store.load()
        if not rest:
            self._send(index_html(docs).encode(), "text/html; charset=utf-8")
            return
        slug, _, item = rest.partition("/")
        if slug == ASSETS:
            self._send_asset(
                item.partition("/")[2]
            )  # the first part is the version, which only defeats caches
            return
        doc = docs.get(slug)
        if doc is None:
            self.send_error(404, "no such document")
            return
        if item == "" and not path.endswith("/"):
            self._redirect(f"{slug}/")  # the viewer's addresses are relative to the folder, /pdf/<name>/
        elif item in ("", "index.html"):
            self._send(viewer_html(doc).encode(), "text/html; charset=utf-8")
        elif item == "document.pdf":
            self._send_file(Path(doc.pdf), "application/pdf", ranges=True)
        elif item.startswith("page-") and item.endswith(".png"):
            self._send_page(doc, item[5:-4])
        else:
            self.send_error(404)

    def _send_asset(self, item: str) -> None:
        root = host.assets_dir().resolve()
        path = (root / item).resolve()
        if not item or not path.is_relative_to(root) or not path.is_file():
            self.send_error(404)
            return
        self._send_file(path, host.content_type(path), cache=True)

    def _send_page(self, doc: store.Document, number: str) -> None:
        if not number.isdigit() or not 1 <= int(number) <= doc.pages:
            self.send_error(404, "no such page")
            return
        try:
            image = render.render_page(Path(doc.pdf), int(number), doc.cache, doc.dpi)
        except (render.PopplerMissingError, subprocess.CalledProcessError) as e:
            self.send_error(500, f"could not render the page: {e}")
            return
        self._send_file(image, "image/png", cache=True)

    def _redirect(self, location: str) -> None:
        self.send_response(301)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")  # the viewer changes when a document does
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str, cache: bool = False, ranges: bool = False) -> None:
        """Send a file. With ranges, a request for part of it (the Range header, which PDF.js sends to read a
        long document a piece at a time) gets only that part."""
        if not path.exists():
            self.send_error(404)
            return
        size = path.stat().st_size
        start, end = 0, size - 1
        wanted = self.headers.get("Range", "") if ranges else ""
        part = re.fullmatch(r"bytes=(\d*)-(\d*)", wanted.strip())
        if part and (part.group(1) or part.group(2)):
            if part.group(1):
                start = int(part.group(1))
                end = min(int(part.group(2)), size - 1) if part.group(2) else size - 1
            else:  # bytes=-N: the last N bytes
                start = max(size - int(part.group(2)), 0)
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(end - start + 1))
        if ranges:
            self.send_header("Accept-Ranges", "bytes")
        # Page images and the viewer's files never change at the same address, so a browser may keep them.
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.end_headers()
        with path.open("rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0 and (chunk := f.read(min(1 << 20, left))):
                self.wfile.write(chunk)
                left -= len(chunk)

    def log_message(self, fmt: str, *args: object) -> None:
        pass  # one line per request would bury whatever started the server


def pid_file() -> Path:
    return store.HOME / "server.pid"


def is_running() -> bool:
    """True if something is listening on the loopback port."""
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", store.PORT)) == 0


def start_background() -> None:
    """Start the server as a detached process, unless it is already listening."""
    if is_running():
        return
    store.HOME.mkdir(parents=True, exist_ok=True)
    log = (store.HOME / "server.log").open("ab")
    proc = subprocess.Popen(
        [sys.executable, "-m", "pdfpage.server"],
        stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True,
    )  # fmt: skip
    pid_file().write_text(str(proc.pid))
    for _ in range(50):  # up to 5 seconds
        if is_running():
            return
        time.sleep(0.1)
    raise RuntimeError(f"the server did not start; see {store.HOME / 'server.log'}")


def stop() -> bool:
    """Stop a server started by start_background. True if one was stopped."""
    path = pid_file()
    if not path.exists():
        return False
    try:
        os.kill(int(path.read_text()), signal.SIGTERM)
    except (ProcessLookupError, ValueError):
        return False
    finally:
        path.unlink(missing_ok=True)
    return True


def serve_forever() -> None:
    ThreadingHTTPServer(("127.0.0.1", store.PORT), Handler).serve_forever()


if __name__ == "__main__":
    serve_forever()
