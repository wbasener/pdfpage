// The pdfpage viewer: one PDF, opened at a page, with the cited quote highlighted; zoom; a highlight tool (the
// default) and a hand tool; and the reader's own highlights, kept in this browser only (localStorage).
//
// What to show is a record (citation_record in the Python package). It comes from, in this order:
//   a <script type="application/json" id="pdfpage-record"> in the page (the pdfpage server writes one);
//   ?record=<address>[&id=<id>]: a JSON file of one record, or of many keyed by id (a host application's);
//   ?file=<address of a PDF>: a document alone, opened at its first page.
// The record's address is resolved against this page's address, and the document's address against the record's.
// #p=<page> opens at that page instead of the record's, and follows the reader. ?theme=light or dark is the host
// page's theme (the side pane passes it); ?build=legacy uses PDF.js's build for older browsers from the start.
//
// The page is drawn by PDF.js (pdfjs/, see pdfjs/VERSION). Where PDF.js cannot run, the page images are shown when
// the record names them, else the browser's own PDF viewer, else a link to the file.

const PDFJS = new URL('pdfjs/', import.meta.url);
const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const MIN_SCALE = 0.3;
const MAX_SCALE = 4;
const STEP = 1.2;
const STORE = 'pdfpage-highlights:';   // + the document's key: {"v": 1, "items": [{id, page, rects, text, at}]}
const ZOOM_WORDS = ['page-width', 'page-fit', 'auto'];

const S = {
  rec: null, docUrl: '', pages: 0, page: 1, view: 'pdf', tool: 'highlight', spaceHand: false,
  lib: null, viewer: null, key: '', marks: [], canStore: true, selected: null, undo: [], addedAt: 0,
  fitWord: null, imgScale: 1, pointer: 'mouse',
};
const container = $('container');

// ------------------------------------------------------------------ small helpers
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
const round5 = (v) => Math.round(clamp(v, 0, 1) * 1e5) / 1e5;
const posInt = (v) => (Number.isInteger(Number(v)) && Number(v) >= 1 ? Number(v) : 0);
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}
function here() { return location.href.split('#')[0]; }   // this page without its #, for links that must not use <base>
let toastTimer = 0;
function toast(text, ms = 2600) {
  const t = $('toast');
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, ms);
}
function message(text, link) {
  const m = $('msg');
  m.textContent = text;
  if (link) {
    m.append(' ');
    const a = el('a', '', link.text);
    a.href = link.href;
    a.target = '_blank';
    a.rel = 'noopener';
    m.append(a);
  }
  m.hidden = false;
}
function setState(s) { document.documentElement.dataset.ppState = s; }   // ready or failed, for tests and hosts
function toParent(data) {
  if (window.parent !== window) window.parent.postMessage({ pdfpage: data.type, ...data }, '*');
}

// ------------------------------------------------------------------ the record
async function loadRecord() {
  const inline = $('pdfpage-record');
  if (inline) return { rec: JSON.parse(inline.textContent), base: here() };
  const address = params.get('record');
  if (address) {
    const url = new URL(address, here());
    const res = await fetch(url, { credentials: 'same-origin' });
    if (!res.ok) throw new Error(`the record ${url.pathname} could not be read (HTTP ${res.status})`);
    let data = await res.json();
    const id = params.get('id');
    if (id !== null) {
      if (!data || typeof data !== 'object' || !Object.prototype.hasOwnProperty.call(data, id)) {
        throw new Error(`the record file has no entry "${id}"`);
      }
      data = data[id];
    }
    return { rec: data, base: url.href };
  }
  const file = params.get('file');
  if (file) return { rec: { doc: file }, base: here() };
  throw new Error('no document was named: the address needs ?record=... or ?file=...');
}

function normalise(r, base) {
  if (!r || typeof r !== 'object' || !r.doc) throw new Error('the record names no document');
  const h = r.highlight;
  const okBoxes = h && Array.isArray(h.page_size) && h.page_size.length === 2 && Array.isArray(h.boxes)
    && h.boxes.length > 0 && h.boxes.every((b) => Array.isArray(b) && b.length === 4);
  const zoom = ZOOM_WORDS.includes(r.zoom) ? r.zoom
    : (Number(r.zoom) >= 10 && Number(r.zoom) <= 1000 ? Number(r.zoom) : 'page-width');
  return {
    doc: new URL(String(r.doc), base).href,
    page: posInt(r.page) || 1,
    title: String(r.title || ''),
    subtitle: String(r.subtitle || ''),
    quote: String(r.quote || ''),
    highlight: okBoxes ? h : null,
    printed: String(r.printed || ''),
    note: String(r.note || ''),
    sha256: String(r.sha256 || ''),
    pages: posInt(r.pages),
    zoom,
    images: r.images && String(r.images).includes('{page}') ? String(r.images) : '',   // resolved per page:
    imagesBase: base,                                                                   // a URL escapes the braces
    view: r.view === 'images' ? 'images' : 'pdf',
  };
}

function startPage(rec) {
  const hash = new URLSearchParams(location.hash.slice(1));
  return posInt(hash.get('p') || hash.get('page')) || rec.page;
}

// ------------------------------------------------------------------ the header
function fileName(url) {
  try { return decodeURIComponent(new URL(url).pathname.split('/').pop()) || 'Document'; } catch (e) { return 'Document'; }
}

function fillHeader(rec) {
  const title = rec.title || fileName(rec.doc);
  $('title').textContent = title;
  $('title').title = title;
  document.title = title;
  if (rec.subtitle) {
    $('sub').textContent = rec.subtitle;
    $('sub').title = rec.subtitle;
    $('sub').hidden = false;
  }
  if (rec.quote) {
    $('quoteWhere').textContent = `Page ${rec.page}${rec.printed ? ` (printed ${rec.printed})` : ''}:`;
    $('quoteText').textContent = `“${rec.quote}”`;
    $('quote').title = rec.quote;
    $('quote').hidden = false;
  }
  const notes = [];
  if (rec.quote && !rec.highlight) notes.push('The quote could not be placed word by word on this page, so it is not highlighted.');
  if (rec.note) notes.push(rec.note);
  if (notes.length) {
    $('note').textContent = notes.join(' ');
    $('note').title = $('note').textContent;
    $('note').hidden = false;
  }
  $('toQuote').hidden = !rec.highlight;
  $('toQuote').textContent = 'Back to the quote';
  if (S.pages) $('count').textContent = `of ${S.pages}`;
  $('expand').addEventListener('click', () => {
    const open = $('info').classList.toggle('pp-open');
    $('expand').setAttribute('aria-expanded', String(open));
    $('expand').textContent = open ? 'Show less' : 'Show in full';
  });
  new ResizeObserver(checkCut).observe($('info'));
  checkCut();
}

// "Show in full" appears only when a line of the header is cut short.
function checkCut() {
  if ($('info').classList.contains('pp-open')) return;
  const cut = ['title', 'sub', 'quote', 'note'].some((id) => !$(id).hidden
    && (getComputedStyle($(id)).display === 'none' || $(id).scrollWidth > $(id).clientWidth + 1));
  $('expand').hidden = !cut;
}

// ------------------------------------------------------------------ the theme
const forcedTheme = ['light', 'dark'].includes(params.get('theme'));
function theme() { return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark'; }
function setTheme(t, remember) {
  document.documentElement.setAttribute('data-theme', t);
  if (remember) { try { localStorage.setItem('pdfpage-theme', t); } catch (e) { /* a private window */ } }
  $('themeBtn').textContent = t === 'light' ? 'Dark page' : 'Light page';
}

// ------------------------------------------------------------------ pages, position and links
function setPage(n) {
  S.page = n;
  if (document.activeElement !== $('num')) $('num').value = String(n);
  $('prev').disabled = n <= 1;
  $('next').disabled = !S.pages || n >= S.pages;
  history.replaceState(history.state, '', `${here()}#p=${n}`);
  $('openFile').href = `${S.docUrl}#page=${n}`;
  toParent({ type: 'location', href: location.href, page: n });
}

function goPage(n) {
  release();
  n = clamp(n, 1, S.pages || n);
  if (S.view === 'images') showImage(n);
  else if (S.viewer && S.viewer.pdfDocument) S.viewer.currentPageNumber = n;
}

// After the viewer scrolls to the quote, the page box shows the cited page, even where the quote is at the
// foot of its page and most of the window shows the next one (PDF.js names the page most in view). It follows
// PDF.js again once the reader moves: a wheel, a key, a touch, a click in the pages, or a page button.
function hold(n) { S.held = n; setPage(n); }
function release() {
  if (!S.held) return;
  S.held = 0;
  if (S.view === 'pdf' && S.viewer && S.viewer.pdfDocument && S.viewer.currentPageNumber !== S.page) {
    setPage(S.viewer.currentPageNumber);
  }
}

// Scroll so the quote sits a quarter of the way down the window, and across so it is in view.
function scrollToQuote(smooth) {
  const rec = S.rec;
  let div;
  if (S.view === 'images') {
    if (S.page !== rec.page) {   // the cited page's image first; its arrival scrolls to the quote
      S.wantQuote = true;
      showImage(rec.page);
      return;
    }
    div = $('imgPage');
  } else {
    const pv = S.viewer && S.viewer.getPageView(rec.page - 1);
    div = pv && pv.div;
  }
  if (!div) return;
  const box = S.view === 'images' ? $('images') : container;
  let fx0 = 0, fy0 = 0, fx1 = 1;
  if (rec.highlight) {
    const [pw, ph] = rec.highlight.page_size;
    const b = rec.highlight.boxes;
    fx0 = Math.min(...b.map((r) => r[0])) / pw;
    fx1 = Math.max(...b.map((r) => r[2])) / pw;
    fy0 = Math.min(...b.map((r) => r[1])) / ph;
  }
  const pr = div.getBoundingClientRect();
  const cr = box.getBoundingClientRect();
  const left = pr.left - cr.left + box.scrollLeft + div.clientLeft;
  const top = pr.top - cr.top + box.scrollTop + div.clientTop;
  const w = div.clientWidth, h = div.clientHeight;
  const y = top + fy0 * h - (rec.highlight ? box.clientHeight * 0.25 : 8);
  const x0 = left + fx0 * w, x1 = left + fx1 * w;
  let x = box.scrollLeft;
  if (x1 - x0 > box.clientWidth - 40) x = x0 - 20;
  else if (x0 < x + 20 || x1 > x + box.clientWidth - 20) x = (x0 + x1) / 2 - box.clientWidth / 2;
  box.scrollTo({ top: Math.max(0, y), left: Math.max(0, x), behavior: smooth ? 'smooth' : 'auto' });
  if (S.view === 'pdf') hold(rec.page);
}

// ------------------------------------------------------------------ size
function showScale(scale, word) {
  $('pct').textContent = `${Math.round(scale * 100)}%`;
  $('zoomOut').disabled = scale <= MIN_SCALE + 1e-6;
  $('zoomIn').disabled = scale >= MAX_SCALE - 1e-6;
  $('fit').setAttribute('aria-pressed', String(word === 'page-width'));
}

function zoomBy(factor, origin, drawingDelay) {
  if (S.view === 'images') {
    S.imgScale = clamp(Math.round(S.imgScale * factor * 100) / 100, MIN_SCALE, MAX_SCALE);
    S.imgFit = false;
    applyImgScale();
    return;
  }
  const v = S.viewer;
  if (!v || !v.pdfDocument) return;
  const cur = v.currentScale;
  const next = clamp(Math.round(cur * factor * 100) / 100, MIN_SCALE, MAX_SCALE);
  if (Math.abs(next - cur) < 0.005) return;
  const c = container.getBoundingClientRect();
  v.updateScale({ scaleFactor: next / cur, origin: origin || [c.left + c.width / 2, c.top + c.height / 2], drawingDelay });
}

function fitWidth() {
  if (S.view === 'images') { S.imgFit = true; applyImgScale(); return; }
  if (S.viewer && S.viewer.pdfDocument) S.viewer.currentScaleValue = 'page-width';
}

// A percentage that would make the page wider than the window (a phone) opens at the window's width instead.
function applyZoom(zoom) {
  if (typeof zoom !== 'number') { S.viewer.currentScaleValue = zoom; return; }
  S.viewer.currentScaleValue = 'page-width';
  const want = clamp(zoom / 100, MIN_SCALE, MAX_SCALE);
  if (want < S.viewer.currentScale) S.viewer.currentScale = want;
}

// ------------------------------------------------------------------ tools: highlight and hand
function handActive() { return S.view === 'images' || S.tool === 'hand' || S.spaceHand; }
function updateCursor() {
  container.classList.toggle('pp-tool-hand', handActive());
  container.classList.toggle('pp-tool-highlight', !handActive());
}
function setTool(t) {
  S.tool = t;
  $('toolHl').setAttribute('aria-checked', String(t === 'highlight'));
  $('toolHand').setAttribute('aria-checked', String(t === 'hand'));
  if (t === 'hand') { deselect(); hideSelPop(); }
  updateCursor();
}

// Drag to pan with a mouse or pen; a finger already pans by itself.
function pannable(box) {
  let drag = null;
  box.addEventListener('pointerdown', (e) => {
    if (!handActive() || e.button !== 0 || e.pointerType === 'touch') return;
    if (e.target.closest('a, button, input, .pp-pop')) return;
    drag = { x: e.clientX, y: e.clientY, l: box.scrollLeft, t: box.scrollTop, id: e.pointerId };
    box.setPointerCapture(e.pointerId);
    box.classList.add('pp-dragging');
    e.preventDefault();
  });
  box.addEventListener('pointermove', (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    box.scrollLeft = drag.l - (e.clientX - drag.x);
    box.scrollTop = drag.t - (e.clientY - drag.y);
  });
  const end = (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    drag = null;
    box.classList.remove('pp-dragging');
    try { box.releasePointerCapture(e.pointerId); } catch (err) { /* already released */ }
  };
  box.addEventListener('pointerup', end);
  box.addEventListener('pointercancel', end);
}

// ------------------------------------------------------------------ the reader's highlights
function storeKey() { return STORE + S.key; }
function validItem(m) {
  return m && typeof m.id === 'string' && posInt(m.page) && Array.isArray(m.rects)
    && m.rects.every((r) => Array.isArray(r) && r.length === 4 && r.every((v) => typeof v === 'number'));
}
function loadMarks() {
  try {
    const raw = localStorage.getItem(storeKey());
    const data = raw ? JSON.parse(raw) : null;
    S.marks = data && Array.isArray(data.items) ? data.items.filter(validItem) : [];
    S.canStore = true;
  } catch (e) {
    S.marks = [];
    S.canStore = false;
  }
  updateClear();
}
function saveMarks() {
  try {
    if (S.marks.length) localStorage.setItem(storeKey(), JSON.stringify({ v: 1, items: S.marks }));
    else localStorage.removeItem(storeKey());
  } catch (e) {
    if (S.canStore) toast('This browser would not keep your highlights (it may be a private window); they last until the page is closed.', 5000);
    S.canStore = false;
  }
  updateClear();
}
function updateClear() {
  const n = S.marks.length;
  $('clearHl').disabled = n === 0;
  $('clearHl').textContent = n ? `Clear my highlights (${n})` : 'Clear my highlights';
  $('storeNote').textContent = S.canStore
    ? 'Your highlights are kept in this browser only.'
    : 'This browser cannot keep highlights (it may be a private window); they last until the page is closed.';
}

function pageDivOf(n) {
  if (S.view === 'images') return S.page === n ? $('imgPage') : null;
  const pv = S.viewer && S.viewer.getPageView(n - 1);
  return pv && pv.div;
}

function draw(n) {
  const div = pageDivOf(n);
  if (!div) return;
  let layer = div.querySelector(':scope > .pp-marks');
  if (!layer) {
    layer = el('div', 'pp-marks');
    div.append(layer);
  }
  layer.textContent = '';
  const add = (cls, [x0, y0, x1, y1]) => {
    const m = el('div', `pp-mark ${cls}`);
    Object.assign(m.style, { left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%` });
    layer.append(m);
    return m;
  };
  const h = S.rec.highlight;
  if (n === S.rec.page && h) {
    const [pw, ph] = h.page_size;
    for (const [x0, y0, x1, y1] of h.boxes) add('pp-q', [x0 / pw, y0 / ph, x1 / pw, y1 / ph]);
  }
  if (S.view === 'images') return;   // the reader's highlights live on the PDF view, where the text is
  for (const m of S.marks) {
    if (m.page !== n) continue;
    for (const r of m.rects) add(m.id === S.selected ? 'pp-h pp-sel' : 'pp-h', r).dataset.id = m.id;
  }
  if (S.selected) {
    const m = S.marks.find((x) => x.id === S.selected && x.page === n);
    if (m) layer.append(removePop(m, div));
  }
}
function drawAll() {
  if (S.view === 'images') { draw(S.page); return; }
  if (!S.viewer || !S.viewer.pdfDocument) return;
  for (let n = 1; n <= S.pages; n++) if (pageDivOf(n) && pageDivOf(n).querySelector('.canvasWrapper')) draw(n);
}

function removePop(m, div) {
  const last = m.rects[m.rects.length - 1];
  const pop = el('div', 'pp-pop');
  const b = el('button', '', 'Remove highlight');
  b.type = 'button';
  b.addEventListener('click', (e) => { e.stopPropagation(); removeMark(m.id); });
  pop.append(b);
  const nearLeft = last[2] * div.clientWidth < 170;
  Object.assign(pop.style, {
    left: `${(nearLeft ? last[0] : last[2]) * 100}%`, top: `${last[3] * 100}%`,
    transform: nearLeft ? 'translate(0, 6px)' : 'translate(-100%, 6px)',
  });
  return pop;
}

function select(id) {
  const old = S.marks.find((x) => x.id === S.selected);
  S.selected = id;
  if (old) draw(old.page);
  const m = S.marks.find((x) => x.id === id);
  if (m) draw(m.page);
}
function deselect() { if (S.selected) select(null); }
function removeMark(id) {
  const m = S.marks.find((x) => x.id === id);
  if (!m) return;
  S.marks = S.marks.filter((x) => x.id !== id);
  if (S.selected === id) S.selected = null;
  saveMarks();
  draw(m.page);
}
function newId() {
  return `h${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

// The selected words, as boxes on each page (fractions of the page), one box per line.
function selectionParts() {
  const sel = getSelection();
  if (!sel || sel.isCollapsed || !sel.rangeCount) return [];
  const viewerDiv = $('viewer');
  const pages = new Map();
  for (let i = 0; i < sel.rangeCount; i++) {
    const range = sel.getRangeAt(i);
    let root = range.commonAncestorContainer;
    if (root.nodeType !== 1) root = root.parentNode;
    if (!viewerDiv.contains(root)) continue;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!range.intersectsNode(node)) continue;
      const span = node.parentElement;
      const pageDiv = span && span.closest('.textLayer') && span.closest('.page');
      if (!pageDiv) continue;
      const s = node === range.startContainer ? range.startOffset : 0;
      const e = node === range.endContainer ? range.endOffset : node.length;
      if (e <= s || !node.data.slice(s, e).trim()) continue;
      const r = document.createRange();
      r.setStart(node, s);
      r.setEnd(node, e);
      const n = Number(pageDiv.dataset.pageNumber);
      if (!pages.has(n)) {
        const pr = pageDiv.getBoundingClientRect();
        pages.set(n, { px: [], text: [], ox: pr.left + pageDiv.clientLeft, oy: pr.top + pageDiv.clientTop,
          w: pageDiv.clientWidth, h: pageDiv.clientHeight });
      }
      const p = pages.get(n);
      p.text.push(node.data.slice(s, e));
      for (const c of r.getClientRects()) {
        if (c.width >= 0.5 && c.height >= 0.5) p.px.push([c.left - p.ox, c.top - p.oy, c.right - p.ox, c.bottom - p.oy]);
      }
    }
  }
  return [...pages].filter(([, p]) => p.px.length).map(([page, p]) => ({
    page,
    rects: mergeLines(p.px).map(([a, b, c, d]) => [round5(a / p.w), round5(b / p.h), round5(c / p.w), round5(d / p.h)]),
    text: p.text.join(' ').replace(/\s+/g, ' ').trim().slice(0, 1000),
  }));
}

// Join the boxes of words on one line into one box: they overlap by half a line in height and nearly touch.
function mergeLines(rects) {
  rects.sort((a, b) => a[1] - b[1] || a[0] - b[0]);
  const lines = [];
  for (const r of rects) {
    const h = r[3] - r[1];
    const line = lines.find((l) => {
      const overlap = Math.min(l[3], r[3]) - Math.max(l[1], r[1]);
      const gap = Math.max(r[0] - l[2], l[0] - r[2]);
      return overlap >= 0.5 * Math.min(h, l[3] - l[1]) && gap <= h;
    });
    if (line) {
      line[0] = Math.min(line[0], r[0]); line[1] = Math.min(line[1], r[1]);
      line[2] = Math.max(line[2], r[2]); line[3] = Math.max(line[3], r[3]);
    } else lines.push([...r]);
  }
  return lines;
}

function sameRects(a, b) {
  return a.length === b.length && a.every((r, i) => r.every((v, j) => Math.abs(v - b[i][j]) < 0.002));
}

function addFromSelection() {
  const parts = selectionParts();
  if (!parts.length) return false;
  const pages = new Set();
  for (const p of parts) {
    if (S.marks.some((m) => m.page === p.page && sameRects(m.rects, p.rects))) continue;
    const m = { id: newId(), page: p.page, rects: p.rects, text: p.text, at: new Date().toISOString() };
    S.marks.push(m);
    S.undo.push(m.id);
    pages.add(p.page);
  }
  getSelection().removeAllRanges();
  hideSelPop();
  if (!pages.size) return false;
  S.selected = null;
  saveMarks();
  pages.forEach(draw);
  S.addedAt = Date.now();
  return true;
}

// On a touch screen a selection is made and adjusted with the fingers, so it becomes a highlight only when the
// reader taps "Highlight" beside it.
let selPop = null;
function hideSelPop() { if (selPop) { selPop.remove(); selPop = null; } }
function showSelPop() {
  const sel = getSelection();
  if (!sel || sel.isCollapsed || !sel.rangeCount || !$('viewer').contains(sel.getRangeAt(0).commonAncestorContainer)) {
    hideSelPop();
    return;
  }
  const rects = [...sel.getRangeAt(sel.rangeCount - 1).getClientRects()].filter((r) => r.width > 0);
  if (!rects.length) return;
  const last = rects[rects.length - 1];
  if (!selPop) {
    selPop = el('div', 'pp-pop');
    const b = el('button', '', 'Highlight');
    b.type = 'button';
    b.addEventListener('pointerdown', (e) => e.preventDefault());   // keep the selection
    b.addEventListener('click', addFromSelection);
    selPop.append(b);
    document.body.append(selPop);
  }
  Object.assign(selPop.style, { position: 'fixed', left: `${clamp(last.right, 120, innerWidth - 8)}px`,
    top: `${clamp(last.bottom, 0, innerHeight - 50)}px` });
}

function wireHighlighting() {
  document.addEventListener('pointerdown', (e) => { S.pointer = e.pointerType || 'mouse'; }, true);
  document.addEventListener('mouseup', (e) => {
    if (e.button !== 0 || S.pointer === 'touch' || handActive() || S.view !== 'pdf') return;
    if (e.target.closest && e.target.closest('.pp-head, .pp-pop')) return;
    addFromSelection();
  });
  let t = 0;
  document.addEventListener('selectionchange', () => {
    if (S.pointer !== 'touch' || handActive()) return;
    clearTimeout(t);
    t = setTimeout(showSelPop, 250);
  });
  container.addEventListener('click', (e) => {
    if (handActive() || Date.now() - S.addedAt < 400) return;
    if (e.target.closest('a, .pp-pop')) return;
    const sel = getSelection();
    if (sel && !sel.isCollapsed) return;
    const pageDiv = e.target.closest('.page');
    if (!pageDiv) { deselect(); return; }
    const n = Number(pageDiv.dataset.pageNumber);
    const pr = pageDiv.getBoundingClientRect();
    const fx = (e.clientX - pr.left - pageDiv.clientLeft) / pageDiv.clientWidth;
    const fy = (e.clientY - pr.top - pageDiv.clientTop) / pageDiv.clientHeight;
    const hit = [...S.marks].reverse().find((m) => m.page === n
      && m.rects.some(([a, b, c, d]) => fx >= a && fx <= c && fy >= b && fy <= d));
    if (hit) select(hit.id === S.selected ? null : hit.id);
    else deselect();
  });
  window.addEventListener('storage', (e) => {   // another tab changed this document's highlights
    if (e.key !== storeKey()) return;
    loadMarks();
    drawAll();
  });
}

// ------------------------------------------------------------------ PDF.js
async function loadPdfjs(legacy) {
  const dir = legacy ? new URL('legacy/', PDFJS) : PDFJS;
  const lib = await import(new URL('build/pdf.min.mjs', dir).href);
  lib.GlobalWorkerOptions.workerSrc = new URL('build/pdf.worker.min.mjs', dir).href;
  globalThis.pdfjsLib = lib;   // the viewer component reads the core library from here
  const ui = await import(new URL('web/pdf_viewer.mjs', dir).href);
  return { lib, ui };
}

function explain(e) {
  const name = (e && e.name) || '';
  if (name === 'PasswordException') return 'This document is protected by a password, which this viewer cannot open.';
  if (name === 'InvalidPDFException') return 'This file is not a PDF that can be read.';
  if (name === 'MissingPDFException' || (name === 'ResponseException' && e.status === 404)) {
    return 'The document was not found at its address.';
  }
  return `The document could not be opened: ${(e && e.message) || e}`;
}
const pdfError = (e) => ['PasswordException', 'InvalidPDFException', 'MissingPDFException', 'ResponseException',
  'UnexpectedResponseException'].includes(e && e.name);

async function openPdf(legacy) {
  const { lib, ui } = await loadPdfjs(legacy);
  S.lib = lib;
  const eventBus = new ui.EventBus();
  const linkService = new ui.PDFLinkService({ eventBus, externalLinkTarget: ui.LinkTarget.BLANK });
  $('viewer').textContent = '';
  const viewer = new ui.PDFViewer({
    container, viewer: $('viewer'), eventBus, linkService, textLayerMode: 1,
    annotationMode: lib.AnnotationMode.ENABLE, imageResourcesPath: new URL('web/images/', PDFJS).href,
  });
  linkService.setViewer(viewer);
  const doc = await lib.getDocument({
    // Only the parts of the file a page needs are fetched, where the server answers range requests.
    url: S.docUrl, disableAutoFetch: true, disableStream: true, isEvalSupported: false, enableXfa: false,
    cMapUrl: new URL('cmaps/', PDFJS).href, cMapPacked: true,
    standardFontDataUrl: new URL('standard_fonts/', PDFJS).href,
    wasmUrl: new URL('wasm/', PDFJS).href, iccUrl: new URL('iccs/', PDFJS).href,
  }).promise;
  S.viewer = viewer;
  S.pages = doc.numPages;
  $('count').textContent = `of ${S.pages}`;
  S.key = S.rec.sha256 || `fp-${(doc.fingerprints && doc.fingerprints[0]) || S.docUrl}`;
  loadMarks();

  const start = clamp(startPage(S.rec), 1, S.pages);
  let first = true;
  eventBus.on('pagesinit', () => {
    applyZoom(S.rec.zoom);
    if (start === S.rec.page && S.rec.highlight) {
      hold(start);
      requestAnimationFrame(() => scrollToQuote(false));
    } else {
      viewer.currentPageNumber = start;
      setPage(start);
    }
  });
  eventBus.on('pagechanging', (e) => { if (!S.held) setPage(e.pageNumber); });
  for (const type of ['wheel', 'touchstart', 'pointerdown', 'keydown']) {
    container.addEventListener(type, release, { passive: true });
  }
  document.addEventListener('keydown', (e) => {   // keys that scroll the pages, wherever the focus is
    if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' '].includes(e.key)) release();
  });
  eventBus.on('scalechanging', (e) => {
    S.fitWord = ZOOM_WORDS.includes(e.presetValue) ? e.presetValue : null;
    showScale(e.scale, S.fitWord);
  });
  const drawn = (e) => {
    draw(e.pageNumber);
    if (first && e.pageNumber === start) {
      first = false;
      $('msg').hidden = true;
      setState('ready');
      toParent({ type: 'ready', title: document.title });
    }
  };
  eventBus.on('pagerendered', drawn);
  eventBus.on('textlayerrendered', (e) => draw(e.pageNumber));
  linkService.setDocument(doc, null);
  viewer.setDocument(doc);
  let pending = 0;
  new ResizeObserver(() => {
    cancelAnimationFrame(pending);
    pending = requestAnimationFrame(() => {
      if (S.fitWord && viewer.pdfDocument) viewer.currentScaleValue = S.fitWord;
    });
  }).observe(container);
}

// ------------------------------------------------------------------ page images and the browser's own viewer
function imageUrl(n) { return new URL(S.rec.images.replace('{page}', String(n)), S.rec.imagesBase).href; }
function showImage(n) {
  n = clamp(n, 1, S.pages || n);
  let img = $('img');
  if (!img) {   // made here, not in the page, so the page never holds an image without an address
    img = el('img');
    img.id = 'img';
    $('imgPage').prepend(img);
  }
  img.onload = () => {
    $('msg').hidden = true;
    if ((!S.imgShown || S.wantQuote) && n === S.rec.page && S.rec.highlight) scrollToQuote(S.imgShown);
    S.imgShown = true;
    S.wantQuote = false;
    setState('ready');
  };
  img.onerror = () => message(`Page ${n} could not be shown.`);
  img.src = imageUrl(n);
  img.alt = `Page ${n}`;
  setPage(n);
  $('images').scrollTop = 0;
  draw(n);
  for (const k of [n + 1, n - 1]) if (k >= 1 && (!S.pages || k <= S.pages)) new Image().src = imageUrl(k);
}
// Page images are sized as PDF.js sizes pages, so a percentage means the same in both views: at 100 % a page
// 8.5 inches wide is 816 pixels. Fit width follows the window.
const IMG_PAGE = 816;
function imgFitScale() { return Math.max(($('images').clientWidth - 24) / IMG_PAGE, MIN_SCALE); }
function applyImgScale() {
  if (S.imgFit) S.imgScale = imgFitScale();
  $('imgPage').style.width = `${Math.round(IMG_PAGE * S.imgScale)}px`;
  showScale(S.imgScale, S.imgFit ? 'page-width' : null);
}

function showImages() {
  S.view = 'images';
  container.hidden = true;
  $('native').hidden = true;
  $('images').hidden = false;
  $('tools').hidden = true;
  $('clearHl').hidden = true;
  $('viewSwitch').textContent = 'Show the PDF with its text';
  $('viewSwitch').hidden = Boolean(S.pdfFailed);   // back to the PDF view, unless PDF.js cannot run here
  if (!S.imgSized) {   // the first time: the record's size, but never wider than the window
    S.imgSized = true;
    const want = typeof S.rec.zoom === 'number' ? S.rec.zoom / 100 : Infinity;
    S.imgFit = want >= imgFitScale();
    S.imgScale = S.imgFit ? imgFitScale() : clamp(want, MIN_SCALE, MAX_SCALE);
    new ResizeObserver(() => { if (S.imgFit && S.view === 'images') applyImgScale(); }).observe($('images'));
  }
  applyImgScale();
  showImage(clamp(S.page || startPage(S.rec), 1, S.pages || 1));
}

function showNative(why) {
  S.view = 'native';
  container.hidden = true;
  $('images').hidden = true;
  const f = $('native');
  const z = typeof S.rec.zoom === 'number' ? S.rec.zoom : 'page-width';
  f.src = `${S.docUrl}#page=${startPage(S.rec)}&zoom=${z}`;
  f.hidden = false;
  for (const g of document.querySelectorAll('.pp-bar > .pp-group')) if (!g.querySelector('#moreBtn')) g.hidden = true;
  $('toQuote').hidden = true;
  $('clearHl').hidden = true;
  toast(why, 6000);
  $('msg').hidden = true;
  setState('ready');
}

// ------------------------------------------------------------------ the toolbar and keys
function wireToolbar() {
  $('prev').addEventListener('click', () => goPage(S.page - 1));
  $('next').addEventListener('click', () => goPage(S.page + 1));
  $('num').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { goPage(posInt(e.target.value) || S.page); e.target.blur(); }
    if (e.key === 'Escape') { e.target.value = String(S.page); e.target.blur(); }
  });
  $('num').addEventListener('blur', (e) => { e.target.value = String(S.page); });
  $('zoomIn').addEventListener('click', () => zoomBy(STEP));
  $('zoomOut').addEventListener('click', () => zoomBy(1 / STEP));
  $('fit').addEventListener('click', fitWidth);
  $('toolHl').addEventListener('click', () => setTool('highlight'));
  $('toolHand').addEventListener('click', () => setTool('hand'));
  $('toQuote').addEventListener('click', () => scrollToQuote(true));

  const menu = $('menu');
  const setMenu = (open) => { menu.hidden = !open; $('moreBtn').setAttribute('aria-expanded', String(open)); };
  $('moreBtn').addEventListener('click', (e) => { e.stopPropagation(); setMenu(menu.hidden); });
  document.addEventListener('click', (e) => { if (!menu.hidden && !menu.contains(e.target)) setMenu(false); });
  menu.addEventListener('click', (e) => { if (e.target.closest('button, a')) setMenu(false); });
  $('copyLink').addEventListener('click', async () => {
    const u = new URL(here());
    u.searchParams.delete('theme');   // the host page's theme is not part of the document's address
    const link = `${u.href}#p=${S.page}`;
    try { await navigator.clipboard.writeText(link); toast('The link to this page is copied.'); }
    catch (e) { window.prompt('Copy this link:', link); }
  });
  $('viewSwitch').addEventListener('click', () => {
    if (S.view === 'images') {
      S.view = 'pdf';
      $('images').hidden = true;
      container.hidden = false;
      $('tools').hidden = false;
      $('clearHl').hidden = false;
      $('viewSwitch').textContent = 'Show page images';
      updateCursor();
      if (S.viewer && S.viewer.pdfDocument) { showScale(S.viewer.currentScale, S.fitWord); S.viewer.currentPageNumber = S.page; }
      else startPdf().catch((e) => message(explain(e), { text: 'Open the PDF file', href: S.docUrl }));
    } else showImages();
  });
  $('clearHl').addEventListener('click', () => {
    const n = S.marks.length;
    if (!n || !window.confirm(`Remove all ${n} of your highlights from this document? The quote's own highlight stays.`)) return;
    const pages = new Set(S.marks.map((m) => m.page));
    S.marks = [];
    S.selected = null;
    saveMarks();
    pages.forEach(draw);
  });
  $('themeBtn').hidden = forcedTheme;
  $('themeBtn').addEventListener('click', () => setTheme(theme() === 'light' ? 'dark' : 'light', true));
  setTheme(theme(), false);

  const typing = (t) => t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
  document.addEventListener('keydown', (e) => {
    if (typing(e.target)) return;
    if (e.code === 'Space' && !e.ctrlKey && !e.metaKey && !(e.target.closest && e.target.closest('button, a'))) {
      e.preventDefault();   // held, the space bar is the hand; it does not scroll
      if (!S.spaceHand) { S.spaceHand = true; updateCursor(); }
      return;
    }
    if (e.ctrlKey || e.metaKey) {
      if (e.key === 'z' && S.view === 'pdf') {   // undo the last highlight
        const id = S.undo.pop();
        if (id && S.marks.some((m) => m.id === id)) { e.preventDefault(); removeMark(id); }
      }
      return;
    }
    if (e.key === '+' || e.key === '=') zoomBy(STEP);
    else if (e.key === '-' || e.key === '_') zoomBy(1 / STEP);
    else if (e.key === 'Escape') { setMenu(false); deselect(); hideSelPop(); }
    else if ((e.key === 'Delete' || e.key === 'Backspace') && S.selected) { e.preventDefault(); removeMark(S.selected); }
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      const box = S.view === 'images' ? $('images') : container;
      if (box.scrollWidth > box.clientWidth + 1) return;   // the arrows scroll across a page wider than the window
      e.preventDefault();
      goPage(S.page + (e.key === 'ArrowLeft' ? -1 : 1));
    }
  });
  document.addEventListener('keyup', (e) => {
    if (e.code === 'Space' && S.spaceHand) { S.spaceHand = false; updateCursor(); }
  });
  window.addEventListener('blur', () => { if (S.spaceHand) { S.spaceHand = false; updateCursor(); } });
  // Ctrl and the wheel, or a pinch on a touchpad, zoom the page around the pointer rather than the whole window.
  container.addEventListener('wheel', (e) => {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    zoomBy(clamp(Math.exp(-e.deltaY / 300), 0.8, 1.25), [e.clientX, e.clientY], 300);
  }, { passive: false });
  window.addEventListener('hashchange', () => {
    const n = startPage(S.rec);
    if (n !== S.page) goPage(n);
  });
  window.addEventListener('message', (e) => {
    if (e.source !== window.parent || !e.data || e.data.pdfpage !== 'theme') return;
    if (e.data.theme === 'light' || e.data.theme === 'dark') setTheme(e.data.theme, false);
  });
  pannable(container);
  pannable($('images'));
  wireHighlighting();
}

// ------------------------------------------------------------------ start
async function startPdf() {
  const legacyFirst = params.get('build') === 'legacy';
  try {
    await openPdf(legacyFirst);
  } catch (e) {
    if (pdfError(e)) throw e;
    if (!legacyFirst) {
      try { await openPdf(true); return; } catch (e2) { if (pdfError(e2)) throw e2; }
    }
    S.pdfFailed = true;
    if (S.rec.images) {
      showImages();
      toast('This browser cannot run the PDF viewer, so the page images are shown.', 6000);
    } else if (navigator.pdfViewerEnabled !== false) {
      showNative('This browser cannot run this viewer, so its own PDF viewer is shown.');
    } else {
      message('This browser can show neither this viewer nor a PDF inside a page.', { text: 'Open the PDF file', href: S.docUrl });
      setState('failed');
    }
  }
}

async function main() {
  wireToolbar();
  let loaded;
  try {
    loaded = await loadRecord();
    S.rec = normalise(loaded.rec, loaded.base);
  } catch (e) {
    $('title').textContent = 'No document';
    message(`This viewer could not start: ${e.message || e}.`);
    setState('failed');
    return;
  }
  S.docUrl = S.rec.doc;
  S.pages = S.rec.pages;
  S.page = startPage(S.rec);
  $('openFile').href = S.docUrl;
  fillHeader(S.rec);
  $('viewSwitch').hidden = !S.rec.images;
  setPage(S.pages ? clamp(S.page, 1, S.pages) : S.page);
  if (S.rec.view === 'images' && S.rec.images) {
    showImages();
    return;
  }
  try {
    await startPdf();
  } catch (e) {
    message(explain(e), { text: 'Open the PDF file', href: S.docUrl });
    setState('failed');
  }
}

main();
