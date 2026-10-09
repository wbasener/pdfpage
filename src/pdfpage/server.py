"""The small web server that shows the published documents.

It listens on the loopback address only (127.0.0.1), so the machine's firewall is never involved
and nothing is exposed to the local network. Tailscale is what makes it reachable from your other
devices; see tailnet.py.
"""

from __future__ import annotations

import html
import os
import signal
import socket
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import unquote

from . import render, store

TEMPLATE = resources.files(__package__).joinpath("viewer.html").read_text(encoding="utf-8")


def viewer_html(doc: store.Document) -> str:
    quote = f'<p class="quote">{html.escape(doc.quote)}</p>' if doc.quote else ""
    return (
        TEMPLATE.replace("__TITLE__", html.escape(doc.title or doc.slug))
        .replace("__SUBTITLE__", html.escape(doc.subtitle))
        .replace("__QUOTE_BLOCK__", quote)
        .replace("__PDF__", "document.pdf")
        .replace("__START__", str(doc.page))
        .replace("__N__", str(doc.pages))
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
        doc = docs.get(slug)
        if doc is None:
            self.send_error(404, "no such document")
            return
        if item in ("", "index.html"):
            self._send(viewer_html(doc).encode(), "text/html; charset=utf-8")
        elif item == "document.pdf":
            self._send_file(Path(doc.pdf), "application/pdf")
        elif item.startswith("page-") and item.endswith(".png"):
            self._send_page(doc, item[5:-4])
        else:
            self.send_error(404)

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

    def _send(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")  # the viewer changes when a document does
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str, cache: bool = False) -> None:
        if not path.exists():
            self.send_error(404)
            return
        size = path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        # Page images never change once rendered, so a browser may keep them.
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.end_headers()
        with path.open("rb") as f:
            while chunk := f.read(1 << 20):
                self.wfile.write(chunk)

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
