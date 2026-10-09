# Changelog

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
