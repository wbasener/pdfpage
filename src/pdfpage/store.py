"""Where published documents are recorded and where their page images are cached."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

# ---- modify here ---------------------------------------------------------------------------
# Everything pdfpage writes lives under this folder; set PDFPAGE_HOME to move it.
HOME = Path(os.environ.get("PDFPAGE_HOME", Path.home() / ".local/share/pdfpage"))
PORT = int(os.environ.get("PDFPAGE_PORT", "8473"))  # loopback port; a firewall never sees it
PREFIX = os.environ.get("PDFPAGE_PREFIX", "/pdf")  # the path documents appear under
DPI = int(os.environ.get("PDFPAGE_DPI", "150"))  # page-image resolution, readable for scans


@dataclass(frozen=True)
class Document:
    """One published PDF."""

    slug: str
    pdf: str  # absolute path to the PDF, which stays where it is
    pages: int
    page: int = 1  # the page the viewer opens at
    title: str = ""
    subtitle: str = ""
    quote: str = ""
    dpi: int = DPI

    @property
    def cache(self) -> Path:
        return HOME / "pages" / self.slug


def registry_path() -> Path:
    return HOME / "registry.json"


def load() -> dict[str, Document]:
    """Every published document, by slug. Entries whose PDF has gone are dropped."""
    path = registry_path()
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {s: Document(**d) for s, d in raw.items() if Path(d["pdf"]).exists()}


def save(docs: dict[str, Document]) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = registry_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps({s: asdict(d) for s, d in docs.items()}, indent=1), encoding="utf-8")
    tmp.replace(registry_path())  # replace in one step, so a reader never sees a half-written file


def slugify(text: str) -> str:
    """A short name safe to put in a web address."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "document"
