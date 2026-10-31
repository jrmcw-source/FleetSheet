#!/usr/bin/env python3
"""FleetSheet universal print box (build 'av', Jason 2026-10-30).

ONE print box for every Print button in the app: a small centered
overlay (like the Windows print popup, carrying FleetSheet's
choices) that replaces both dropdown print-menu implementations —
the app-shell menu that lived in views_core and the print-sheet
menu that lived in printpack. The box is never anchored to its
button, so no choice can fall off a screen edge.

Choices, in this order everywhere: PRINT (paper), Print to
Screen, Print to Location. Per-context behaviour is unchanged
from the menus it replaces; only the container changed:

- doc mode (data-screen / data-pdf): PRINT presents the
  document's screen path in the in-page screen-view overlay
  and prints it from its frame, Print to Screen presents it
  in the same overlay without printing, Print to Location
  files data-doc = pdf||screen via POST /print/save
  (fsSaveLoc).
- page mode (data-page="1"): PRINT is window.print(), Print to
  Screen presents a document-like view of the current page
  (live values included) in the screen-view overlay, Print to
  Location is fsSavePage(this) via POST /print/save-page.
  Print to Screen presents its view in the screen-view
  overlay in every mode; no print choice opens a new tab or
  window anywhere.
- docs mode (data-docs JSON [{label, screen, pdf}, ...]): the
  paper selector switches the active paper; the choices then act
  on that paper exactly as in doc mode.
- commit mode (data-commit="1"): a choice does NOT act directly.
  It finds the trigger's form, sets the hidden inputs
  fs_print_dest (paper|screen|location) and fs_print_doc (the
  active paper's screen path, else data-screen, else ''), and
  submits the form. The server side then prints after the commit
  and lands back with ?fsprint=<dest>, which the on-load handler
  below performs. With no form around the trigger, the choice
  falls back to its direct action.

This module imports nothing from the app, so printpack (which
views_core imports) and views_core itself can both use it without
a cycle.
"""
from __future__ import annotations

import html
import json

PRINTBOX_CSS = """
#fsprintbox{position:fixed;inset:0;display:none;background:rgba(20,28,38,.45);z-index:1600;align-items:center;justify-content:center}
#fsprintbox.open{display:flex}
#fsprintbox .pbox-card{background:#fff;border-radius:10px;box-shadow:0 18px 50px rgba(16,24,40,.35);width:min(340px,92vw);max-height:calc(100vh - 32px);overflow-y:auto;padding:14px;box-sizing:border-box;font:14px/1.45 Inter,Calibri,'Segoe UI',sans-serif;color:#1a1a1a}
#fsprintbox .pbox-head{display:flex;justify-content:space-between;align-items:center;gap:8px}
#fsprintbox-title{font-weight:700;font-size:15px;color:#1B2A4A}
#fsprintbox .pbox-close{background:none;border:1px solid #c5cdd6;border-radius:6px;padding:4px 10px;font:inherit;font-size:13px;color:#1B2A4A;cursor:pointer}
#fsprintbox-papers{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
#fsprintbox .pbox-paper{background:#fff;border:1px solid #c5cdd6;border-radius:6px;padding:4px 10px;font:inherit;font-size:12px;color:#1B2A4A;cursor:pointer}
#fsprintbox .pbox-paper.on{background:#1B2A4A;border-color:#1B2A4A;color:#fff}
#fsprintbox .pbox-choice{display:block;width:100%;box-sizing:border-box;text-align:left;padding:8px 10px;margin-top:6px;background:#fff;border:1px solid #c5cdd6;border-radius:6px;color:#1B2A4A;font:inherit;cursor:pointer}
#fsprintbox .pbox-choice:hover{background:#eef2f7}
#fsprintbox-note{margin-top:8px;font-size:12px;color:#7a4d00}
#fsprintbox-folder{font-size:12px;color:#49606e;word-break:break-all;margin-top:10px}
#fsprintbox-folder a{color:#1B2A4A}
#fsprintbox .pbox-stat{font-size:12px;color:#49606e;min-height:1.45em;margin-top:6px;white-space:normal}
#fsview{position:fixed;inset:0;display:none;background:rgba(27,42,74,.45);z-index:1700;align-items:center;justify-content:center;padding:24px}
#fsview.open{display:flex}
#fsview .fsview-win{background:#fff;box-shadow:0 12px 40px rgba(0,0,0,.35);width:min(880px,94vw);height:min(640px,88vh);display:flex;flex-direction:column}
#fsview .fsview-bar{display:flex;align-items:center;gap:8px;background:#1B2A4A;color:#fff;padding:8px 12px}
#fsview-title{flex:1;font-weight:700;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#fsview .fsview-bar button{background:#46586E;border:0;color:#fff;border-radius:4px;padding:3px 10px;font-size:12px;cursor:pointer}
#fsview .fsview-bar button:hover{background:#54687F}
#fsview iframe{flex:1;border:0;width:100%;background:#fff}
"""

PRINTBOX_HTML = """
<div id="fsprintbox" role="dialog" aria-modal="true" aria-labelledby="fsprintbox-title">
<div class="pbox-card">
<div class="pbox-head"><span id="fsprintbox-title">Print</span><button type="button" class="pbox-close" id="fsprintbox-close">Close</button></div>
<div id="fsprintbox-papers"></div>
<button type="button" class="pbox-choice" id="fsprintbox-print">PRINT</button>
<button type="button" class="pbox-choice" id="fsprintbox-screen">Print to Screen</button>
<button type="button" class="pbox-choice" id="fsprintbox-location">Print to Location</button>
<div id="fsprintbox-note" style="display:none">Choosing a destination saves this form first, then prints.</div>
<div id="fsprintbox-folder">Print to Location folder: <span id="fsprintbox-folder-path"></span> <a id="fsprintbox-folder-change" href="/setup/folders?for=print">Change\u2026</a></div>
<div id="fsprintbox-stat" class="pbox-stat"></div>
</div>
</div>
<div id="fsview" role="dialog" aria-modal="true" aria-labelledby="fsview-title">
  <div class="fsview-win">
    <div class="fsview-bar"><span id="fsview-title">Print</span>
      <button type="button" id="fsview-print">Print</button>
      <button type="button" id="fsview-close">Close</button></div>
    <iframe id="fsview-frame" title="Print to Screen"></iframe>
  </div>
</div>
"""

PRINTBOX_JS = """
<script>
/* Print box actions (carried over from the old print menus,
   Jason 2026-10-18, container changed build 'av' 2026-10-30).
   Print to Screen builds a document-like view of the CURRENT
   page (live values included): controls become their values,
   app chrome is stripped. Print to Location files that same
   view (form pages) or the document's file (document contexts)
   into the operator's print folder. */
var FS_PV_CSS = 'body{font:13px/1.45 Calibri,Segoe UI,sans-serif;color:#1a1a1a;margin:24px}'
  + 'table{border-collapse:collapse}td,th{border-bottom:1px solid #e5e7eb;padding:4px 6px}'
  + '.pv-val{white-space:pre-wrap;word-break:break-word}'
  + 'h1,h2,h3{color:#1B2A4A}';
function fsBuildPrintHTML(){
  var clone = document.documentElement.cloneNode(true);
  var src = document.querySelectorAll('input,select,textarea');
  var dst = clone.querySelectorAll('input,select,textarea');
  for (var i = 0; i < src.length && i < dst.length; i++){
    var el = src[i], c = dst[i];
    if (el.type === 'checkbox' || el.type === 'radio'){
      if (el.checked) c.setAttribute('checked',''); else c.removeAttribute('checked');
    } else if (el.tagName === 'SELECT'){
      Array.prototype.forEach.call(c.options, function(o){ o.selected = (o.value === el.value); });
    } else {
      c.setAttribute('value', el.value);
      if (el.tagName === 'TEXTAREA') c.textContent = el.value;
    }
  }
  // Controls become their values — a document, not a form.
  Array.prototype.slice.call(clone.querySelectorAll('input,select,textarea')).forEach(function(c){
    var span = clone.ownerDocument.createElement('span');
    span.className = 'pv-val';
    if (c.tagName === 'SELECT'){
      var o = c.options[c.selectedIndex];
      span.textContent = o ? o.textContent : '';
    } else if (c.type === 'checkbox' || c.type === 'radio'){
      span.textContent = c.checked ? '\\u2611' : '\\u2610';
    } else {
      span.textContent = c.value || '';
    }
    c.parentNode.replaceChild(span, c);
  });
  Array.prototype.slice.call(clone.querySelectorAll(
    'script,header,footer,nav,button,#fsprintbox,.mark,#morebelow,.pbox-lock,.news-wrap'
  )).forEach(function(n){ n.remove(); });
  var st = clone.ownerDocument.createElement('style');
  st.textContent = FS_PV_CSS;
  clone.querySelector('head').appendChild(st);
  return '<!doctype html>' + clone.outerHTML;
}
function fsPstat(btn, msg){
  /* Status lives in the open box now (build 'av'): when the box
     is open, write into #fsprintbox-stat; otherwise fall back
     silently — the old per-menu status span is gone. */
  var box = document.getElementById('fsprintbox');
  if (!box || !box.classList.contains('open')) return;
  var st = document.getElementById('fsprintbox-stat');
  if (st) st.textContent = msg;
}
function fsSaveLoc(btn){
  fsPstat(btn, 'Saving\\u2026');
  var body = new URLSearchParams(); body.set('doc', btn.getAttribute('data-doc'));
  fetch('/print/save', {method:'POST', body: body}).then(function(r){ return r.json(); })
    .then(function(j){ fsPstat(btn, j.ok ? ('Saved to ' + j.path) : ('Could not save: ' + (j.error || 'error'))); })
    .catch(function(e){ fsPstat(btn, 'Could not save.'); });
}
function fsSavePage(btn){
  fsPstat(btn, 'Saving\\u2026');
  var body = new URLSearchParams();
  body.set('name', document.title || 'FleetSheet document');
  body.set('html', fsBuildPrintHTML());
  fetch('/print/save-page', {method:'POST', body: body}).then(function(r){ return r.json(); })
    .then(function(j){ fsPstat(btn, j.ok ? ('Saved to ' + j.path) : ('Could not save: ' + (j.error || 'error'))); })
    .catch(function(e){ fsPstat(btn, 'Could not save.'); });
}
/* Screen-view overlay (build 'aw'): Print to Screen in every
   mode, and doc-mode PRINT on paper, present in this in-page
   overlay — never a new tab or window. It mirrors the .apop
   shell: fixed dim overlay, centered window, title bar with
   Print and Close, iframe body; printing is by iframe focus
   plus contentWindow.print(). */
var FS_VIEW_PRINT = false;
function fsShowView(title){
  var t = document.getElementById('fsview-title');
  if (t) t.textContent = title || 'Print';
  var v = document.getElementById('fsview');
  if (v) v.classList.add('open');
}
function fsHideView(){
  var v = document.getElementById('fsview');
  if (v) v.classList.remove('open');
  var f = document.getElementById('fsview-frame');
  if (f){ f.removeAttribute('srcdoc'); f.src = 'about:blank'; }
  FS_VIEW_PRINT = false;
}
function fsPrintViewFrame(){
  var f = document.getElementById('fsview-frame');
  if (f && f.contentWindow){
    try { f.contentWindow.focus(); f.contentWindow.print(); } catch(e){}
  }
}
function fsShowScreenDoc(path, title){
  var f = document.getElementById('fsview-frame');
  if (!f) return;
  FS_VIEW_PRINT = false;
  f.removeAttribute('srcdoc');
  f.src = path;
  fsShowView(title);
}
function fsShowPaperDoc(path, title){
  var f = document.getElementById('fsview-frame');
  if (!f) return;
  FS_VIEW_PRINT = true;
  f.removeAttribute('srcdoc');
  f.src = path;
  fsShowView(title);
}
function fsShowScreenPage(title){
  var f = document.getElementById('fsview-frame');
  if (!f) return;
  FS_VIEW_PRINT = false;
  f.removeAttribute('src');
  f.srcdoc = fsBuildPrintHTML();
  fsShowView(title);
}
/* The box itself (build 'av'): FS_PB is the live context the
   trigger handed over in fsOpenPrint; the choice buttons act on
   it. The box never anchors to the trigger — it is one centered
   overlay, identical on every surface. */
var FS_PB = {trigger:null, mode:'doc', title:'Print', screen:'', pdf:'',
             docs:null, active:0, commit:false};
var FS_PB_FOLDER = null;
function fsPBActivePaper(){
  if (FS_PB.docs && FS_PB.docs.length) return FS_PB.docs[FS_PB.active] || FS_PB.docs[0];
  return {label: FS_PB.title, screen: FS_PB.screen, pdf: FS_PB.pdf};
}
function fsPBRenderPapers(){
  var wrap = document.getElementById('fsprintbox-papers');
  if (!wrap) return;
  wrap.innerHTML = '';
  if (!FS_PB.docs || FS_PB.docs.length < 2){ wrap.style.display = 'none'; return; }
  wrap.style.display = '';
  FS_PB.docs.forEach(function(d, i){
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'pbox-paper' + (i === FS_PB.active ? ' on' : '');
    b.textContent = d.label || ('Paper ' + (i + 1));
    b.addEventListener('click', function(){ FS_PB.active = i; fsPBRenderPapers(); });
    wrap.appendChild(b);
  });
}
function fsPBFolderLine(){
  var link = document.getElementById('fsprintbox-folder-change');
  if (link) link.href = '/setup/folders?for=print&ret='
    + encodeURIComponent(location.pathname + location.search);
  var span = document.getElementById('fsprintbox-folder-path');
  if (!span) return;
  if (FS_PB_FOLDER !== null){ span.textContent = FS_PB_FOLDER; return; }
  fetch('/print/folder').then(function(r){ return r.json(); })
    .then(function(j){ FS_PB_FOLDER = j.folder || ''; span.textContent = FS_PB_FOLDER; })
    .catch(function(e){});
}
function fsOpenPrint(trigger){
  if (!trigger) return;
  FS_PB.trigger = trigger;
  FS_PB.active = 0;
  FS_PB.title = trigger.getAttribute('data-title') || 'Print';
  FS_PB.screen = trigger.getAttribute('data-screen') || '';
  FS_PB.pdf = trigger.getAttribute('data-pdf') || '';
  FS_PB.commit = trigger.getAttribute('data-commit') === '1';
  FS_PB.docs = null;
  var raw = trigger.getAttribute('data-docs');
  if (raw){
    try {
      var parsed = JSON.parse(raw);
      if (parsed && parsed.length) FS_PB.docs = parsed;
    } catch(e){ FS_PB.docs = null; }
  }
  FS_PB.mode = FS_PB.docs ? 'docs'
    : (trigger.getAttribute('data-page') === '1' ? 'page' : 'doc');
  var box = document.getElementById('fsprintbox');
  if (!box) return;
  var title = document.getElementById('fsprintbox-title');
  if (title) title.textContent = FS_PB.title;
  var note = document.getElementById('fsprintbox-note');
  if (note) note.style.display = FS_PB.commit ? '' : 'none';
  var stat = document.getElementById('fsprintbox-stat');
  if (stat) stat.textContent = '';
  fsPBRenderPapers();
  fsPBFolderLine();
  box.classList.add('open');
}
function fsClosePrint(){
  var box = document.getElementById('fsprintbox');
  if (box) box.classList.remove('open');
}
function fsPBCommit(dest){
  var trigger = FS_PB.trigger;
  var form = (trigger && trigger.closest) ? trigger.closest('form') : null;
  if (!form) return false;
  function ensure(name){
    var inp = form.querySelector('input[name="' + name + '"]');
    if (!inp){
      inp = document.createElement('input');
      inp.type = 'hidden'; inp.name = name;
      form.appendChild(inp);
    }
    return inp;
  }
  var paper = fsPBActivePaper();
  ensure('fs_print_dest').value = dest;
  ensure('fs_print_doc').value = (paper && paper.screen) || FS_PB.screen || '';
  fsClosePrint();
  form.submit();
  return true;
}
function fsPBAct(dest){
  if (FS_PB.commit && fsPBCommit(dest)) return;
  if (FS_PB.mode === 'page'){
    if (dest === 'paper'){ fsClosePrint(); window.print(); }
    else if (dest === 'screen'){ fsShowScreenPage(FS_PB.title); fsClosePrint(); }
    else { fsSavePage(document.getElementById('fsprintbox-location')); }
    return;
  }
  var paper = fsPBActivePaper();
  if (!paper) return;
  var scr = paper.screen || paper.pdf || '';
  if (dest === 'paper'){ if (scr) fsShowPaperDoc(scr, FS_PB.title); fsClosePrint(); }
  else if (dest === 'screen'){ if (scr) fsShowScreenDoc(scr, FS_PB.title); fsClosePrint(); }
  else {
    var shim = document.createElement('button');
    shim.setAttribute('data-doc', paper.pdf || paper.screen || '');
    fsSaveLoc(shim);
  }
}
(function(){
  function wire(id, dest){
    var el = document.getElementById(id);
    if (el && !el._fsWired){
      el._fsWired = true;
      el.addEventListener('click', function(){ fsPBAct(dest); });
    }
  }
  wire('fsprintbox-print', 'paper');
  wire('fsprintbox-screen', 'screen');
  wire('fsprintbox-location', 'location');
  var close = document.getElementById('fsprintbox-close');
  if (close && !close._fsWired){
    close._fsWired = true;
    close.addEventListener('click', fsClosePrint);
  }
  var box = document.getElementById('fsprintbox');
  if (box && !box._fsWired){
    box._fsWired = true;
    box.addEventListener('click', function(e){ if (e.target === box) fsClosePrint(); });
  }
  var vprint = document.getElementById('fsview-print');
  if (vprint && !vprint._fsWired){
    vprint._fsWired = true;
    vprint.addEventListener('click', fsPrintViewFrame);
  }
  var vclose = document.getElementById('fsview-close');
  if (vclose && !vclose._fsWired){
    vclose._fsWired = true;
    vclose.addEventListener('click', fsHideView);
  }
  var view = document.getElementById('fsview');
  if (view && !view._fsWired){
    view._fsWired = true;
    view.addEventListener('click', function(e){ if (e.target === view) fsHideView(); });
  }
  var vframe = document.getElementById('fsview-frame');
  if (vframe && !vframe._fsWired){
    vframe._fsWired = true;
    vframe.addEventListener('load', function(){
      if (!FS_VIEW_PRINT) return;
      try {
        if (!vframe.contentWindow || !vframe.contentWindow.location
            || vframe.contentWindow.location.href === 'about:blank') return;
      } catch(e){ return; }
      FS_VIEW_PRINT = false;
      fsPrintViewFrame();
    });
  }
  document.addEventListener('keydown', function(e){
    if (e.key === 'Escape' || e.key === 'Esc'){ fsClosePrint(); fsHideView(); }
  });
})();
/* Print-after-commit landing (build 'av'): a commit-mode Print
   posts the form, and the server lands back here carrying
   ?fsprint=paper|screen|location — perform that one action,
   then strip the param so a reload does not print again. */
function fsPBHandleFsPrint(){
  if (window._fsPBParamDone) return;
  window._fsPBParamDone = true;
  var params;
  try { params = new URLSearchParams(location.search); } catch(e){ return; }
  var v = params.get('fsprint');
  if (!v) return;
  if (v === 'paper') window.print();
  else if (v === 'screen') fsShowScreenPage(document.title || 'Print');
  else if (v === 'location') fsSavePage({});
  params.delete('fsprint');
  var qs = params.toString();
  try {
    history.replaceState(null, '', location.pathname
      + (qs ? ('?' + qs) : '') + location.hash);
  } catch(e){}
}
if (document.readyState === 'loading'){
  document.addEventListener('DOMContentLoaded', fsPBHandleFsPrint);
} else {
  fsPBHandleFsPrint();
}
</script>
"""


def print_trigger(title=None, label="Print", screen=None, pdf=None,
                  page=False, docs=None, commit=False, compact=False,
                  extra=None):
    """The Print button that opens the universal print box.

    Data-attribute contract (read by fsOpenPrint in PRINTBOX_JS):
      data-title   box head text (omitted = "Print")
      data-screen  doc mode: the document's screen (/print/…) path
      data-pdf     doc mode: the document's PDF path (Print to
                   Location files this one when present)
      data-page    "1" in page mode (choices act on the live page)
      data-docs    docs mode: JSON [{label, screen, pdf}, ...];
                   docs entries may be dicts or (label, screen,
                   pdf) tuples/lists
      data-commit  "1" in commit mode (choice submits the form
                   with fs_print_dest / fs_print_doc set instead
                   of acting directly)
      extra        optional dict of additional attributes; keys
                   without a data- prefix get one, values are
                   escaped like the rest (True renders as "1",
                   None is skipped)

    Classes keep the trigger's established appearance: "pmenu-sum"
    for the standard trigger, "pmenu-link" for compact, plus
    "pbtn" on both.
    """
    cls = "pmenu-link" if compact else "pmenu-sum"
    attrs = []
    if title:
        attrs.append(
            f'data-title="{html.escape(str(title), quote=True)}"')
    if screen:
        attrs.append(
            f'data-screen="{html.escape(str(screen), quote=True)}"')
    if pdf:
        attrs.append(
            f'data-pdf="{html.escape(str(pdf), quote=True)}"')
    if page:
        attrs.append('data-page="1"')
    if docs:
        norm = []
        for d in docs:
            if isinstance(d, dict):
                norm.append({"label": d.get("label", ""),
                             "screen": d.get("screen", ""),
                             "pdf": d.get("pdf", "")})
            else:
                seq = (list(d) + ["", "", ""])[:3]
                norm.append({"label": seq[0], "screen": seq[1],
                             "pdf": seq[2]})
        attrs.append('data-docs="{}"'.format(
            html.escape(json.dumps(norm), quote=True)))
    if commit:
        attrs.append('data-commit="1"')
    if extra:
        for key, val in extra.items():
            if val is None:
                continue
            name = key if str(key).startswith("data-") else f"data-{key}"
            if val is True:
                val = "1"
            attrs.append(
                f'{name}="{html.escape(str(val), quote=True)}"')
    attr_txt = (" " + " ".join(attrs)) if attrs else ""
    return (f'<button type="button" class="{cls} pbtn"{attr_txt} '
            f'onclick="fsOpenPrint(this)">{html.escape(str(label))}</button>')
