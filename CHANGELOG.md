# Changelog

## 0.2.0 - 2026-10-10

A viewer of its own, which also works beside the pages of another web application.

- The document is drawn by PDF.js 6.3.289, which comes with the package (no Python dependency).
  It opens at the page with the quoted passage outlined on the page, and "Back to the quote" returns to it.
- Zoom: "Zoom out", "Zoom in", "Fit width" and the current size; the + and - keys; Ctrl and the wheel.
- Two tools: "Highlight" (the default: select words to highlight them, click a highlight to remove it) and
  "Hand" (drag to move around the page; the space bar held does the same).
- A reader's highlights are kept in their own browser only, named by the document's SHA-256.
- The heading keeps every button in view at any window width: long titles are cut to one line, with
  "Show in full" and a tooltip.
- Light and dark pages.
- The side pane: `pane.js` and `pane.css` open the viewer in a pane on the right of any web page from a
  `data-pdfpage` element, with "Open in a new tab"; the whole window on a phone.
- Python: `check_quote` and `quote_boxes` (moved from the OrePrior3D Model Atlas), and `assets_dir`,
  `citation_record`, `viewer_url`, `file_sha256` and `content_type` for a host application.
- The server answers range requests for the PDF, so a long document opens without being downloaded whole.
- The page images stay, for browsers that cannot run PDF.js; the browser's own PDF viewer is the last resort.

## 0.1.0 - 2026-10-09

First release.

- `publish` a PDF and get a link that opens it at a chosen page, `#p=12`.
- `--find` opens at the first page whose text contains a phrase.
- Two views: the browser's own scrolling PDF viewer (the default, at 125%) and
  pre-rendered page images for browsers that cannot show a PDF inside a page.
- Page images are rendered when first asked for and then kept, so publishing a long
  document is as quick as a short one.
- Served on the loopback address only; Tailscale carries it to your other devices.
- A command line and a Python API; no Python dependencies.
