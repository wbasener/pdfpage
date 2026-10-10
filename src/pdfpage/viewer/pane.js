/* pdfpage side pane: opens the pdfpage viewer beside a host page.

   On the host page:
     <link rel="stylesheet" href="<assets>/pane.css">
     <script src="<assets>/pane.js" defer></script>
     <button type="button" data-pdfpage="<viewer address>">Show the page in the document</button>
     <a href="<viewer address>" data-pdfpage>Show the page in the document</a>   (opens in a tab without JavaScript)

   A click on an element with data-pdfpage opens the viewer in a pane on the right of the window, which the reader
   can widen or narrow by dragging its left edge (the width is remembered in this browser), close, or open in a new
   tab. At a narrow width (phones) the pane covers the whole window. A link clicked with Ctrl, Shift or the middle
   button opens in a new tab as usual.

   Optional attributes on the clicked element:
     data-pdfpage-label="Cited document"   the words in the pane's bar (default "Document")
     data-pdfpage-target="#selector"       open in that element of the host page instead of the floating pane

   From a script: pdfpage.open(url, {label, target, trigger}) returns the pane's id ("pdfpage-pane" for the
   floating pane, "pdfpage-pane-1" and on for panes inside host elements); pdfpage.close() closes every pane,
   and pdfpage.close(which) one of them: its id, an element in it, its host element (or that element's
   selector), or the element that opened it; pdfpage.isOpen() and pdfpage.isOpen(which) say whether any or that
   one is open.
   Events on document: "pdfpage:open" (detail {url, trigger}) and "pdfpage:close" (detail {trigger}). While its
   document is open, the clicked element has the class "pdfpage-active" and aria-expanded="true".

   The pane follows the host page's theme: <html data-pdfpage-theme="light|dark">, else <html data-theme="...">,
   else the page's color-scheme, else the system's; the viewer is told when it changes. The host page is pushed
   aside while the pane is open (html.pdfpage-pane-open body gets a right margin, the pane's width, which is also the
   CSS variable --pdfpage-pane-width), and the clicked element is kept in view as the page wraps again;
   <html data-pdfpage-push="off"> turns both off. --pdfpage-pane-top sets how far below the top of the window
   the pane starts, for a host with a fixed header. */
(function () {
  'use strict';
  if (window.pdfpage && window.pdfpage.open) return;   // loaded twice

  var WIDTH_KEY = 'pdfpage-pane-width';
  var NARROW = 900;           // at or below this window width the pane covers the whole window
  var MIN_WIDTH = 320;
  var root = document.documentElement;
  var panes = [];             // {box, frame, link, label, trigger, inline}
  var floating = null;
  var made = 0;               // inline panes made so far, for their ids

  function storedWidth() {
    try { return parseInt(localStorage.getItem(WIDTH_KEY), 10) || 0; } catch (e) { return 0; }
  }
  function clampWidth(w) { return Math.max(MIN_WIDTH, Math.min(w, window.innerWidth - 240)); }
  function setWidth(w, save) {
    w = Math.round(clampWidth(w));
    root.style.setProperty('--pdfpage-pane-width', w + 'px');
    if (save) { try { localStorage.setItem(WIDTH_KEY, String(w)); } catch (e) { /* a private window */ } }
  }
  function defaultWidth() { return storedWidth() || Math.min(window.innerWidth * 0.46, 820); }

  function hostTheme() {
    var forced = root.getAttribute('data-pdfpage-theme');
    if (forced === 'light' || forced === 'dark') return forced;
    var attr = (root.getAttribute('data-theme') || root.getAttribute('data-bs-theme') || '').toLowerCase();
    if (attr === 'light' || attr === 'dark') return attr;
    var cs = (getComputedStyle(root).colorScheme || '').trim();
    if (cs === 'dark' || cs === 'only dark') return 'dark';
    if (cs === 'light' || cs === 'only light') return 'light';
    return window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  function withTheme(url) {
    var u = new URL(url, location.href);
    u.searchParams.set('theme', hostTheme());
    return u.href;
  }

  function build(inline) {
    var box = document.createElement(inline ? 'div' : 'aside');
    box.className = 'pdfpage-pane' + (inline ? ' pdfpage-pane-inline' : '');
    box.id = inline ? 'pdfpage-pane-' + (++made) : 'pdfpage-pane';   // what open() returns and close(id) takes
    box.hidden = true;
    box.setAttribute('aria-label', 'Document');
    box.innerHTML =
      (inline ? '' : '<div class="pdfpage-pane-grip" role="separator" aria-orientation="vertical" tabindex="0" ' +
        'aria-label="Drag to change the width of the pane" title="Drag to change the width of the pane"></div>') +
      '<div class="pdfpage-pane-bar"><span class="pdfpage-pane-label"></span>' +
      '<a class="pdfpage-pane-tab" target="_blank" rel="noopener">Open in a new tab</a>' +
      '<button type="button" class="pdfpage-pane-close">Close</button></div>' +
      '<iframe class="pdfpage-pane-frame" title="Document" allow="clipboard-write; fullscreen"></iframe>';
    var p = { box: box, frame: box.querySelector('iframe'), link: box.querySelector('a'),
      label: box.querySelector('.pdfpage-pane-label'), trigger: null, inline: inline };
    box.querySelector('.pdfpage-pane-close').addEventListener('click', function () { close(p); });
    if (!inline) grip(p, box.querySelector('.pdfpage-pane-grip'));
    box.dataset.theme = hostTheme();
    panes.push(p);
    return p;
  }

  // Drag the left edge, or focus it and use the arrow keys, to change the width.
  function grip(p, g) {
    var dragging = false;
    g.addEventListener('pointerdown', function (e) {
      if (e.button !== 0) return;
      dragging = true;
      g.setPointerCapture(e.pointerId);
      p.box.classList.add('pdfpage-pane-resizing');   // the frame would otherwise take the pointer
      e.preventDefault();
    });
    g.addEventListener('pointermove', function (e) {
      if (dragging) setWidth(window.innerWidth - e.clientX, false);
    });
    function end(e) {
      if (!dragging) return;
      dragging = false;
      p.box.classList.remove('pdfpage-pane-resizing');
      try { g.releasePointerCapture(e.pointerId); } catch (err) { /* already released */ }
      setWidth(parseInt(getComputedStyle(root).getPropertyValue('--pdfpage-pane-width'), 10) || defaultWidth(), true);
    }
    g.addEventListener('pointerup', end);
    g.addEventListener('pointercancel', end);
    g.addEventListener('keydown', function (e) {
      var w = parseInt(getComputedStyle(root).getPropertyValue('--pdfpage-pane-width'), 10) || defaultWidth();
      if (e.key === 'ArrowLeft') { setWidth(w + 40, true); e.preventDefault(); }
      if (e.key === 'ArrowRight') { setWidth(w - 40, true); e.preventDefault(); }
    });
  }

  function paneFor(target) {
    if (!target) return floating || (floating = (function () { var p = build(false); document.body.appendChild(p.box); return p; })());
    var host = typeof target === 'string' ? document.querySelector(target) : target;
    if (!host) throw new Error('pdfpage: no element ' + target);
    for (var i = 0; i < panes.length; i++) if (panes[i].inline && panes[i].box.parentNode === host) return panes[i];
    var p = build(true);
    host.appendChild(p.box);
    return p;
  }

  function mark(trigger, on) {
    if (!trigger || !trigger.classList) return;
    trigger.classList.toggle('pdfpage-active', on);
    trigger.setAttribute('aria-expanded', on ? 'true' : 'false');
  }

  function open(url, opts) {
    opts = opts || {};
    var p = paneFor(opts.target);
    var full = new URL(url, location.href).href;
    if (p.trigger && p.trigger !== opts.trigger) mark(p.trigger, false);
    p.trigger = opts.trigger || null;
    mark(p.trigger, true);
    p.label.textContent = opts.label || 'Document';
    p.label.title = p.label.textContent;
    p.link.href = full;
    p.box.dataset.theme = hostTheme();
    var src = withTheme(full);
    if (p.frame.getAttribute('src') !== src) p.frame.setAttribute('src', src);
    var t = p.trigger && p.trigger.getBoundingClientRect ? p.trigger : null;
    var before = t ? t.getBoundingClientRect().top : 0;
    p.box.hidden = false;
    if (!p.inline) {
      setWidth(defaultWidth(), false);
      root.classList.add('pdfpage-pane-open');
      if (window.innerWidth <= NARROW) p.box.querySelector('.pdfpage-pane-close').focus();
      else if (t && root.getAttribute('data-pdfpage-push') !== 'off') keepInView(t, before);
    } else {
      p.box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    document.dispatchEvent(new CustomEvent('pdfpage:open', { detail: { url: full, trigger: p.trigger } }));
    return p.box.id;
  }

  // The pane narrows the page, so its text wraps again and the clicked element moves. Put it back where the
  // reader saw it, then scroll it into view, across too, inside any scrolling box that holds it (a wide table).
  function keepInView(t, before) {
    var after = t.getBoundingClientRect().top;   // reading it lays the narrower page out
    if (Math.abs(after - before) > 1) window.scrollBy(0, after - before);
    t.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }

  // A pane named by its id (what open() returned), by an element in it, by the element it was opened in
  // (data-pdfpage-target, as an element or a selector), or by the element that opened it.
  function find(which) {
    if (which && typeof which === 'object' && which.box) return which;
    var el = which;
    if (typeof which === 'string') {
      for (var i = 0; i < panes.length; i++) if (panes[i].box.id === which) return panes[i];
      try { el = document.querySelector(which); } catch (e) { el = null; }
      el = el || document.getElementById(which);
    }
    if (!el || el.nodeType !== 1) return null;
    for (var j = 0; j < panes.length; j++) {
      var p = panes[j];
      if (p.box === el || p.box.contains(el) || p.trigger === el || (p.inline && p.box.parentNode === el)) return p;
    }
    return null;
  }

  function close(p) {
    var list = p ? [p] : panes.filter(function (x) { return !x.box.hidden; });
    list.forEach(function (x) {
      if (x.box.hidden) return;
      x.box.hidden = true;
      x.frame.setAttribute('src', 'about:blank');
      if (!x.inline) root.classList.remove('pdfpage-pane-open');
      var t = x.trigger;
      mark(t, false);
      x.trigger = null;
      if (t && typeof t.focus === 'function' && x.box.contains(document.activeElement)) t.focus();
      document.dispatchEvent(new CustomEvent('pdfpage:close', { detail: { trigger: t } }));
    });
  }

  function isOpen(which) {
    if (which === undefined || which === null) return panes.some(function (x) { return !x.box.hidden; });
    var p = find(which);
    return Boolean(p && !p.box.hidden);
  }

  document.addEventListener('click', function (e) {
    var t = e.target.closest && e.target.closest('[data-pdfpage]');
    if (!t) return;
    if (t.tagName === 'A' && (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0)) return;   // a new tab, as asked
    var url = t.getAttribute('data-pdfpage') || t.getAttribute('href');
    if (!url) return;
    e.preventDefault();
    open(url, { trigger: t, label: t.getAttribute('data-pdfpage-label') || '',
      target: t.getAttribute('data-pdfpage-target') || null });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && floating && !floating.box.hidden) close(floating);
  });

  // The viewer reports where the reader is, so "Open in a new tab" opens at that page.
  window.addEventListener('message', function (e) {
    var d = e.data;
    if (!d || d.pdfpage !== 'location' || typeof d.href !== 'string') return;
    panes.forEach(function (p) {
      if (e.source === p.frame.contentWindow) {
        var u = new URL(d.href);
        u.searchParams.delete('theme');
        p.link.href = u.href;
      }
    });
  });

  function themeChanged() {
    var t = hostTheme();
    panes.forEach(function (p) {
      p.box.dataset.theme = t;
      if (!p.box.hidden && p.frame.contentWindow) p.frame.contentWindow.postMessage({ pdfpage: 'theme', theme: t }, '*');
    });
  }
  new MutationObserver(themeChanged).observe(root, { attributes: true,
    attributeFilter: ['data-theme', 'data-bs-theme', 'data-pdfpage-theme', 'class'] });
  if (window.matchMedia) {
    var mq = matchMedia('(prefers-color-scheme: dark)');
    if (mq.addEventListener) mq.addEventListener('change', themeChanged);
  }
  window.addEventListener('resize', function () {
    if (floating && !floating.box.hidden) setWidth(defaultWidth(), false);
  });

  window.pdfpage = {
    open: open,
    // close() closes every open pane; close(which) closes one: its id, an element in it, its host element or
    // selector, or the element that opened it. True when a pane was closed.
    close: function (which) {
      if (which === undefined || which === null) { var any = isOpen(); close(); return any; }
      var p = find(which);
      if (!p || p.box.hidden) return false;
      close(p);
      return true;
    },
    isOpen: isOpen,
    version: '0.2.1',
  };
})();
