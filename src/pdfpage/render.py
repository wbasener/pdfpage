"""Reading page counts and turning single pages into images, with poppler's command-line tools.

Pages are rendered one at a time, when a browser first asks for them, and kept in a cache folder.
A long document therefore publishes at once instead of after rendering every page.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


class PopplerMissingError(RuntimeError):
    """poppler-utils is not installed (Debian and Ubuntu: apt install poppler-utils)."""


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError as e:  # pragma: no cover - depends on the machine
        raise PopplerMissingError(f"{cmd[0]} not found; install poppler-utils") from e


def page_count(pdf: Path) -> int:
    out = _run(["pdfinfo", str(pdf)]).stdout
    found = re.search(r"^Pages:\s+(\d+)", out, re.MULTILINE)
    if not found:
        raise ValueError(f"pdfinfo reported no page count for {pdf}")
    return int(found.group(1))


def page_text(pdf: Path, page: int) -> str:
    """The text of one page, for finding which page a quoted passage is on."""
    return _run(["pdftotext", "-f", str(page), "-l", str(page), str(pdf), "-"]).stdout


def find_page(pdf: Path, phrase: str, pages: int | None = None) -> int | None:
    """The first page whose text contains `phrase`, ignoring how the lines are broken, or None.

    Scanned pages carry text only where the document has been through character recognition.
    """
    want = " ".join(phrase.lower().split())
    for n in range(1, (pages or page_count(pdf)) + 1):
        if want in " ".join(page_text(pdf, n).lower().split()):
            return n
    return None


def render_page(pdf: Path, page: int, out_dir: Path, dpi: int) -> Path:
    """Render one page to out_dir/page-N.png if it is not already there, and return the path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"page-{page}.png"
    if target.exists():
        return target
    stem = out_dir / f".tmp-{page}"
    _run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(dpi), "-png", "-singlefile",
          str(pdf), str(stem)])  # fmt: skip
    produced = stem.with_suffix(".png")
    produced.replace(target)  # one step, so a browser never fetches a half-written image
    return target
