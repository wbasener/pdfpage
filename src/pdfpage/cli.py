"""The pdfpage command."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pdfpage

from . import render, server, store, tailnet


def _add(a: argparse.Namespace) -> int:
    try:
        url = pdfpage.publish(
            a.pdf, page=a.page, find=a.find, name=a.name, title=a.title,
            subtitle=a.subtitle, quote=a.quote, dpi=a.dpi,
            mode="images" if a.images else "pdf", zoom=a.zoom,
        )  # fmt: skip
    except (FileNotFoundError, LookupError, ValueError, render.PopplerMissingError) as e:
        print(f"pdfpage: {e}", file=sys.stderr)
        return 1
    print(url)
    if url.startswith("http://127.0.0.1"):
        print("Tailscale is not available, so this address works on this machine only.",
              file=sys.stderr)  # fmt: skip
    return 0


def _list(_: argparse.Namespace) -> int:
    docs = pdfpage.published()
    if not docs:
        print("nothing published")
        return 0
    base = tailnet.base_url()
    width = max(len(s) for s in docs)
    for slug, doc in sorted(docs.items()):
        print(f"{slug:<{width}}  {doc.pages:>4} pages  {base}/{slug}/#p={doc.page}  {doc.pdf}")
    return 0


def _remove(a: argparse.Namespace) -> int:
    if not pdfpage.unpublish(a.name):
        print(f"pdfpage: {a.name} is not published", file=sys.stderr)
        return 1
    print(f"removed {a.name}")
    return 0


def _find(a: argparse.Namespace) -> int:
    page = pdfpage.page_of(a.pdf, a.phrase)
    if page is None:
        print("not found", file=sys.stderr)
        return 1
    print(page)
    return 0


def _stop(a: argparse.Namespace) -> int:
    stopped = pdfpage.shutdown(tailnet_too=a.tailnet)
    print("server stopped" if stopped else "no server was running")
    return 0


def _where(_: argparse.Namespace) -> int:
    print(f"documents   {store.registry_path()}")
    print(f"page images {store.HOME / 'pages'}")
    print(f"server      127.0.0.1:{store.PORT} ({'running' if server.is_running() else 'stopped'})")
    print(f"address     {tailnet.base_url()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pdfpage", description=__doc__)
    subs = p.add_subparsers(dest="command")

    add = subs.add_parser("add", help="publish a PDF (the default command)")
    add.add_argument("pdf", type=Path)
    add.add_argument("--page", type=int, default=1, help="the page to open at")
    add.add_argument("--find", default="", help="open at the first page containing this phrase")
    add.add_argument("--name", default="", help="the last part of the address")
    add.add_argument("--title", default="", help="heading; default: the file name")
    add.add_argument("--subtitle", default="", help="a line of context, such as the full citation")
    add.add_argument("--quote", default="", help="a passage to mark on the page and show under the heading")
    add.add_argument(
        "--dpi", type=int, default=store.DPI, help=f"page-image resolution (default {store.DPI})"
    )
    add.add_argument(
        "--zoom", type=int, default=store.ZOOM,
        help=f"percentage the document opens at (default {store.ZOOM})",
    )  # fmt: skip
    add.add_argument("--images", action="store_true", help="open in the page images, not the scrolling PDF")
    add.set_defaults(func=_add)

    subs.add_parser("list", help="show what is published").set_defaults(func=_list)

    rm = subs.add_parser("remove", help="remove a document from the list")
    rm.add_argument("name")
    rm.set_defaults(func=_remove)

    fd = subs.add_parser("find", help="print the first page containing a phrase")
    fd.add_argument("pdf", type=Path)
    fd.add_argument("phrase")
    fd.set_defaults(func=_find)

    st = subs.add_parser("stop", help="stop the local server")
    st.add_argument("--tailnet", action="store_true", help="also remove the tailnet path")
    st.set_defaults(func=_stop)

    subs.add_parser("where", help="show the folders, the port and the address").set_defaults(func=_where)

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in {*subs.choices, "-h", "--help"}:
        argv.insert(0, "add")  # `pdfpage report.pdf --page 12` means `pdfpage add ...`
    a = p.parse_args(argv)
    if not getattr(a, "func", None):
        p.print_help()
        return 1
    result: int = a.func(a)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
