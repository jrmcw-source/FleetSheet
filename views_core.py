#!/usr/bin/env python3
"""FleetSheet local app. Open http://127.0.0.1:8765 — SQLite is the book."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import html
import json
import os
import re
import socket
import threading
import time
import hmac
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, quote_plus, urlparse

import engine
import printpack
import exportpack

CSS = """
:root { --frame:#2B3542; --gold:#E8B923; --ink:#1a1a1a; --mute:#5C6B7A; --bg:#f8f9fa; --surface:#fdfdfc; --ok:#0f7a43; --bad:#b42318; }
/* Inter: the mainstream business-software typeface, bundled for offline use. (2026-10-06) */
@font-face{font-family:'Inter';font-style:normal;font-weight:400;font-display:swap;src:url('/fonts/inter-400.ttf') format('truetype')}
@font-face{font-family:'Inter';font-style:normal;font-weight:500;font-display:swap;src:url('/fonts/inter-500.ttf') format('truetype')}
@font-face{font-family:'Inter';font-style:normal;font-weight:600;font-display:swap;src:url('/fonts/inter-600.ttf') format('truetype')}
@font-face{font-family:'Inter';font-style:normal;font-weight:700;font-display:swap;src:url('/fonts/inter-700.ttf') format('truetype')}
@font-face{font-family:'Inter';font-style:normal;font-weight:800;font-display:swap;src:url('/fonts/inter-800.ttf') format('truetype')}
*{box-sizing:border-box} body{margin:0;font:14px/1.45 Inter,Calibri,'Segoe UI',sans-serif;background:var(--bg);color:var(--ink)}
header{background:var(--frame);color:#fff;padding:8px 16px;display:flex;align-items:center;flex-wrap:wrap;gap:10px 16px;position:sticky;top:0;z-index:50}
header .brand{font-size:26px;font-weight:700;margin-right:4px;letter-spacing:.02em;
  padding-right:16px;border-right:1px solid rgba(255,255,255,.25);display:flex;align-items:center}
header .brand img{height:34px;max-width:120px;object-fit:contain;margin-right:10px;background:#fff;border-radius:4px;padding:2px}
header nav.main{display:flex;flex-wrap:wrap;gap:4px 14px;align-items:center;flex:1} /* flex:1 lets the lock justify far right (Jason 2026-10-06) */
header nav.main a{padding:8px 14px;border-radius:6px}
header nav.main a:hover{background:rgba(255,255,255,.14)}
header nav.main a:focus-visible{outline:3px solid var(--gold);outline-offset:2px}
header nav.main a.on{background:var(--gold);color:var(--frame);font-weight:700}
header nav.aside{margin-left:8px;display:flex;gap:6px;align-items:center}
header nav.main .tabright{margin-left:auto;display:inline-flex;gap:4px 14px;align-items:center}
header a{color:#fff;text-decoration:none;font-size:13px;white-space:nowrap;position:relative}
header .yardnote{font-size:11px;color:#c9d2dc;border:1px solid #3d4f68;border-radius:10px;padding:2px 9px;white-space:nowrap}
header a[data-tip]::after,.tabs a[data-tip]::after{content:attr(data-tip);position:absolute;left:0;top:calc(100% + 8px);background:#1a1a1a;color:#fff;font-size:11px;line-height:1.35;font-weight:400;letter-spacing:0;padding:8px 10px;border-radius:4px;width:220px;white-space:normal;opacity:0;pointer-events:none;z-index:40;box-shadow:0 4px 12px rgba(0,0,0,.25);transition:opacity .12s linear}
.news{background:#FFF8E1;border-bottom:2px solid var(--gold);padding:3px 16px;display:flex;flex-direction:column;gap:2px;position:relative}
/* Ticker category filter popover: quiet, compact, desk-sized. (2026-10-06) */
.news .filterbox{align-self:flex-end;position:relative}
.tickfilter{position:absolute;right:0;top:calc(100% + 4px);background:var(--surface);border:1px solid #d0d5dd;border-radius:6px;box-shadow:0 4px 12px rgba(0,0,0,.15);padding:10px 12px;z-index:60;min-width:170px}
.tickfilter form{display:flex;flex-direction:column;gap:6px}
.tickfilter label{display:flex;align-items:center;gap:7px;font-size:13px;cursor:pointer;white-space:nowrap}
.tickfilter .vbtn{align-self:flex-start;margin-top:2px}
.news .tap{font-size:12.5px;line-height:1.5;display:flex;align-items:center;flex-wrap:wrap;gap:2px 8px;
  background:var(--surface);border:1px solid #e8dcc0;border-radius:6px;padding:3px 10px;margin:2px 0}
.news .tap .vbtn{margin-left:0}
.news .tap .msg{font-weight:600;color:#5d4a00;margin-right:6px}
.news .tap.calm .msg{font-weight:400;color:var(--mute)}
.news .tap.top .msg{color:#7a5c00;text-transform:uppercase;font-size:11px;letter-spacing:.04em}
.news .tap.top{font-size:12px}
.news .tap.top .msg{color:var(--mute);font-size:10px}
.news .tapbox{border:1px solid var(--gold);border-radius:6px;background:var(--surface);
  padding:5px 10px;margin:3px 0;display:flex;flex-wrap:wrap;align-items:center;
  gap:4px 12px;font-size:12.5px}
.news .tapbox .msg{font-weight:600;color:#5d4a00}
.news .tapbox .go{font-weight:600}
/* Billing-tab ticker: squeezed — same information, less vertical space. */
.news.squeeze{padding:2px 16px}
.news.squeeze .tapbox{padding:2px 8px;margin:2px 0;font-size:12px;gap:2px 10px}
/* Escalation ladder: tap / slap / punch — the box grows as the consequence
   approaches. Gold stays the cue; red is for real bad states. */
.news .tapbox.lv1{border-width:2px}
.news .tapbox.lv2{border-width:3px;background:#fffdf2}
.news .tapbox.lv2 .msg{color:#7a5c00}
.ackf{display:inline;background:none;border:none;padding:0;width:auto;margin:0}
.ackf input[type=number]{width:2.2em;font-size:12px;padding:1px 3px}
/* Walkthrough #3: snooze/sleep ride right-justified and apart; the thin box
   outline on .tapbox above already ties each item's buttons to that item. */
.news .tapbox .ack-right{margin-left:auto;display:inline-flex;gap:22px;align-items:center}
.news .tap .ack-right{margin-left:auto;display:inline-flex;gap:22px;align-items:center}
.news .tap.top a{font-weight:700;color:var(--frame);margin-right:14px}
.news .tap form,.news .tapbox form{display:inline;background:none;border:none;padding:0;width:auto;margin:0 0 0 6px}
.news .tap button,.news .tapbox button{font-size:11px !important;padding:2px 8px !important;border-radius:3px;border:1px solid #c9a227;background:var(--surface);color:#1a1a1a;cursor:pointer;width:auto;min-width:0;line-height:1.4}
.news .tap button.go,.news .tapbox button.go{background:var(--frame);color:#fff;border-color:var(--frame);text-decoration:none;display:inline-block}
.news .tap a.go,.news .tapbox a.go{font-size:11px;padding:2px 8px;border-radius:3px;background:var(--frame);color:#fff;text-decoration:none}
.todo{padding:4px 0;border-bottom:1px solid #e8e8e8;font-size:14px}
.todo a{color:var(--frame);font-weight:600}
.ytag{display:inline-block;font-size:11px;font-weight:600;color:#5C6B7A;background:#f1f3f5;
  border:1px solid #d0d5dd;border-radius:10px;padding:1px 8px;margin-left:6px;white-space:nowrap}
/* Sticky notes: quiet desk reminders. Plain lines, no gold, no urgency
   chrome — ticker-style awareness, not shoulder-taps. */
.sticky{padding:6px 8px;border-bottom:1px solid #e8e8e8;font-size:14px;border-radius:6px;margin:4px 0}
.sticky .tiny{font-size:11px;color:var(--mute);text-decoration:none;margin-left:10px}
.sticky button.tiny{font-size:11px;color:var(--mute);background:none;border:0;padding:0;margin-left:10px;cursor:pointer;text-decoration:underline}
.sticky form{display:inline;background:none;border:none;padding:0;width:auto;margin:0}
.sticky .tform input{flex:2 1 240px;width:auto;min-width:0}
.sticky-ctl{margin-top:6px;display:flex;flex-wrap:wrap;gap:4px;align-items:center}
.sticky-ctl select,.sticky-ctl input{font-size:12px;padding:2px 4px}
.sticky-ctl button{font-size:12px;padding:2px 8px}
.pbox{border:1px solid #e0e4ea;border-radius:8px;padding:4px 10px 8px;margin:8px 0;background:var(--surface)}
.pbox:has(> section.dcard){border:none;background:none;padding:0}
.pbox.dragging{opacity:0.5}
.pbox.drop-target{outline:2px dashed var(--gold);outline-offset:2px}
/* Fenced layout: boxes live in a 2-col grid (never overlap, never offscreen).
   Default span matches today's look: full-width rows on plain pages,
   side-by-side on the dashboard. The Half/Full toggle flips one box. */
.pbox-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;align-items:start}
.pbox-grid>.pbox{margin:0;min-width:0;grid-column:1/-1}
.pbox-grid>.pbox[data-span="half"]{grid-column:span 1}
.dashgrid>.pbox{min-width:0}
.dashgrid>.pbox[data-span="full"]{grid-column:1/-1}
.pbox-lock{float:right;width:auto;font-size:12px;padding:3px 10px;margin:2px 0 8px 8px;background:#fffdf2;border:1px solid #c9a227;border-radius:4px;cursor:pointer;color:#5d4a00}
header .pbox-lock{float:none;margin:0 0 0 16px;font-size:11px;font-weight:600;padding:5px 11px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.55);border-radius:4px;color:#fff;cursor:pointer;white-space:nowrap}
header .pbox-lock:hover{background:rgba(255,255,255,.22);border-color:#fff}
header .pbox-lock:focus-visible{outline:3px solid var(--gold);outline-offset:2px}
.pbox-width{width:auto;font-size:11px;padding:1px 8px;margin-left:6px;background:#eef3fa;border:1px solid #d0d5dd;border-radius:3px;cursor:pointer}
.pbox-grip{cursor:grab;margin-right:10px;color:#3d4f68;letter-spacing:1px;font-size:16px;font-weight:700;user-select:none}
.pbox-grip:active{cursor:grabbing}
.pbox-move{font-size:12px;font-weight:400;width:22px;height:22px;line-height:1;padding:0;margin-right:4px;cursor:pointer;background:transparent;border:1px solid #c5cdd6;border-radius:4px;color:var(--mute)}
.pbox-move:hover{background:#0f2a52;border-color:#0f2a52}
#morebelow{position:fixed;left:50%;bottom:14px;transform:translateX(-50%);background:#fffdf2;
  border:1px solid #c9a227;color:#5d4a00;border-radius:20px;padding:4px 14px;font-size:12px;
  cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.12);z-index:60;white-space:nowrap}
.stepper{display:inline-flex;align-items:center;gap:3px;margin:0 4px;vertical-align:middle}
.stepper button{width:24px;height:24px;line-height:1;padding:0;font-size:14px;background:#eef3fa;border:1px solid #d0d5dd;border-radius:4px;cursor:pointer}
.stepper input[type=number]{width:2.2em;text-align:center}
button.mini{font-size:11px;padding:2px 8px;background:var(--surface);color:var(--frame);border:1px solid var(--frame)}
.calm{background:#f0f7f0;border:1px solid #b8d8b8;border-radius:6px;padding:8px 10px;margin:8px 0}
.nudge{background:#FFF8E1;border:1px solid var(--gold);border-radius:6px;padding:6px 10px;margin:8px 0;font-size:13px}
.nudge form{display:inline;background:none;border:none;padding:0;width:auto;margin:0}
.tform{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.todo form{display:inline;background:none;border:none;padding:0;width:auto;margin:0}
.tform input{flex:2 1 240px;width:auto;min-width:0}
.tform select{flex:0 1 160px;width:auto}
header a[data-tip]:hover::after,.tabs a[data-tip]:hover::after,
button[data-tip]:hover::after,a.btn[data-tip]:hover::after,select[data-tip]:hover::after{opacity:1;transition-delay:.7s}
button[data-tip],a.btn[data-tip],select[data-tip]{position:relative}
button[data-tip]::after,a.btn[data-tip]::after,select[data-tip]::after{content:attr(data-tip);position:absolute;left:0;top:calc(100% + 8px);background:#1a1a1a;color:#fff;font-size:11px;line-height:1.35;font-weight:400;letter-spacing:0;padding:8px 10px;border-radius:4px;width:220px;white-space:normal;opacity:0;pointer-events:none;z-index:40;box-shadow:0 4px 12px rgba(0,0,0,.25);transition:opacity .12s linear}
body.notips [data-tip]::after{display:none !important}
[data-tip].tip-open::after{opacity:1 !important;transition-delay:0s}
/* Flipped by JS when the tip would cross the viewport's right edge. */
[data-tip].tip-left::after{left:auto;right:0}
main{max-width:1200px;margin:12px auto;padding:0 12px 16px;overflow-x:clip}
/* overflow-x:clip (not hidden): a hidden tooltip's 220px box can never widen
   the page, yet no scroll container is created so sticky tabs keep working
   and hovered tips (flipped inward by JS at the viewport edge) still show. */
.actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0}
.mark{position:fixed;bottom:8px;right:12px;font-size:11px;letter-spacing:.08em;color:#1B2A4A;opacity:.28;pointer-events:none;z-index:1}
.tabs{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 8px;padding-bottom:6px;border-bottom:1px solid #d0d5dd;position:sticky;top:58px;z-index:40;background:var(--bg);padding-top:6px}
.tabs.grouped{gap:6px 18px}.tabgroup{display:inline-flex;align-items:center;gap:8px}
.tabgrouplab{font-size:11px;color:var(--mute);text-transform:uppercase;letter-spacing:.5px}
.tabs a{display:inline-block;padding:6px 10px;border-radius:4px;background:var(--surface);border:1px solid #d0d5dd;color:var(--frame);text-decoration:none;font-size:13px;position:relative}
.tabs a.on{background:var(--frame);color:#fff;border-color:var(--frame)}
.tabs .tabright{margin-left:auto;display:inline-flex;gap:8px;flex-wrap:wrap;align-items:center}
/* Tooltips on right-aligned tabs open leftward: readable on hover, and the
   hidden 220px box can't stretch the page sideways (the phantom scrollbar). */
.tabs .tabright a[data-tip]::after,header .tabright a[data-tip]::after{left:auto;right:0}
/* Backstop: a hidden tooltip's box must never widen the page. clip (not
   hidden) keeps sticky positioning working and never makes a scroller. */
.tabs{overflow-x:clip}
header{overflow-x:clip}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px}
.card{background:var(--surface);border:1px solid #d0d5dd;border-radius:10px;padding:14px 16px;overflow-wrap:break-word;box-shadow:0 1px 2px rgba(20,35,55,.04)}
.card b{display:block;font-size:22px;color:var(--frame)}
.card span{color:var(--mute);font-size:12px;text-transform:uppercase}
.eyebrow{display:block;color:#6b5600;font-size:10px;font-weight:800;letter-spacing:.09em;margin-bottom:3px}
.onboarding{border:1px solid #d7c16b;background:linear-gradient(180deg,#fffdf5,#fff);margin:0 0 12px}
.onboarding h2{margin:0 0 3px;font-size:19px}
.onboarding .hint{max-width:720px;margin:0 0 10px}
.setupsteps{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px;margin:8px 0}
.setupstep{min-height:44px;padding:6px 8px;border:1px solid #dfe4ea;border-radius:6px;background:#f8fafc;font-size:12px;display:flex;gap:6px;align-items:flex-start}
.setupstep a{font-weight:700;color:var(--frame);text-decoration:none}
.setupstep.done{background:#f3f8f4;border-color:#c9dfcf;color:#41624b}
.setupstep.done span:first-child{font-weight:800;color:var(--ok)}
.onboarding .actions{margin:10px 0 0}
.empty-action{border:1px dashed #c9d2dc;border-radius:8px;background:#fafcfe;padding:14px 16px;margin:10px 0}
.empty-action strong{display:block;color:var(--frame);font-size:15px;margin-bottom:3px}
.empty-action p{margin:0 0 9px;color:var(--mute)}
form,table{background:var(--surface);border:1px solid #d0d5dd;border-radius:8px;padding:10px 12px;width:100%}
label{display:block;font-size:12px;color:var(--mute);margin:4px 0 2px}
label:has(input[type=checkbox]){display:flex;align-items:center;gap:6px;font-size:14px;color:var(--ink,#222)}
input,select{width:100%;padding:5px 8px;border:1px solid #c5cdd6;border-radius:4px;font:inherit;background:var(--surface)}
/* Input widths, sized to the expected content: a street address doesn't
   need the whole screen. */
input.w-xs,select.w-xs{max-width:96px}
input.w-sm,select.w-sm{max-width:180px}
input.w-md,select.w-md{max-width:320px}
select{padding-right:26px;appearance:auto;cursor:pointer;
 background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='8'><path d='M1 1l5 5 5-5' fill='none' stroke='%231B2A4A' stroke-width='2.4'/></svg>");
 background-repeat:no-repeat;background-position:right 8px center}
.dollar{position:relative;display:block}
.dollar::before{content:'$';position:absolute;left:10px;top:50%;transform:translateY(-50%);color:var(--mute);font-size:14px;pointer-events:none}
.dollar>input{padding-left:24px}
.field-err{border:2px solid #8a5a00 !important;background:#fffaeb !important} /* validation: amber, not red (2026-10-06) */
#formerr{display:none;background:#fffaeb;color:#8a5a00;padding:8px;border-radius:6px;margin:8px 0;font-weight:600}
input[type=checkbox]{width:auto;flex:0 0 auto}
.row{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.row3{display:grid;grid-template-columns:2fr 1fr 1fr;gap:8px} /* city/state/zip on one row (Jason 2026-10-06) */
.row4{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px}
.row>*{min-width:0} /* let tracks shrink: wrap inside the column, never widen the page */
.row3>*{min-width:0}
/* Compact form grid (Jason 2026-10-06): two-column dense layout for setup-style
   forms. Opt-in per form — not a global change. */
.fgrid{display:grid;grid-template-columns:1fr 1fr;gap:4px 14px}
.fgrid>.span2{grid-column:span 2}
.fgrid>*{min-width:0}
.fgrid label{margin:3px 0 1px}
.fgrid input,.fgrid select{padding:5px 7px}
/* Tight inline form row (Jason 2026-10-06): label+input pairs sit side by
   side, bottom-aligned, wrapping on narrow screens. */
.frow{display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap}
.frow>*{min-width:0}
button,.btn{background:var(--frame);color:#fff;border:0;padding:9px 14px;border-radius:6px;cursor:pointer;font:inherit;display:inline-block;text-decoration:none;transition:background .12s ease,box-shadow .12s ease,transform .05s ease}
button:hover,.btn:hover{background:#1a2431}
button:active,.btn:active{transform:translateY(1px)}
/* .btn-gold: the primary eye-catcher CTA. Gold is reserved for "look here" actions. (2026-10-06) */
.btn-gold{background:var(--gold);color:#2B3542;font-weight:700;border:0;padding:9px 16px;border-radius:6px;cursor:pointer;font:inherit;display:inline-block;text-decoration:none}
.btn-gold:hover{background:#d4a51f;color:#1a2431}
button:focus-visible,.btn:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid #1a1a1a;outline-offset:2px}
button.secondary{background:var(--surface);color:var(--frame);border:1px solid #aab5c2}
button.secondary:hover{background:#f4f7fa;border-color:var(--frame)}
button.danger{background:var(--bad)}
.err{background:#fdecec;color:var(--bad);padding:8px;border-radius:6px;margin:8px 0}
.critical-banner{background:#fdecec;color:var(--bad);padding:8px;border-radius:6px;margin:8px 0;border:2px solid var(--bad)} /* do-or-die banner (2026-10-06) */
.ok{background:#e7f3ec;color:var(--ok);padding:8px;border-radius:6px;margin:8px 0}
.backup-bar{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:8px 10px;margin:0;width:auto;font-size:12.5px}
.backup-bar .backup-msg{flex:1 1 100%;font-size:12.5px;margin:0}
.backup-bar input{width:110px;padding:5px 7px;font-size:12.5px}
.backup-bar button,.backup-bar .btn{padding:5px 10px;font-size:12.5px}
.backup-bar button{padding:6px 12px;font-size:13px}
table{border-collapse:collapse;padding:0}
th,td{padding:5px 8px;border-bottom:1px solid #eee;text-align:left;font-size:13px}
th{background:#e8eef4;color:var(--frame)}
.fail{color:#8a5a00;font-weight:700} /* routine negative: overdue, expired, FAIL — amber, not red (2026-10-06) */
.critical{color:var(--bad);font-weight:700} /* do-or-die only: data loss, critical integrity (2026-10-06) */
.pass{color:var(--ok)}
h1{font-size:20px;color:var(--frame);margin:6px 0 4px}
h2{font-size:17px;color:var(--frame);margin:8px 0 5px}
h3{font-size:14px;color:var(--frame);margin:6px 0 3px}
.hint{color:var(--mute);font-size:13px}
details{border:1px solid #e0e4ea;border-radius:8px;background:var(--surface);margin:8px 0;padding:0}
details[open]{padding-bottom:10px}
details>summary{list-style:none;cursor:pointer;padding:8px 12px;font-size:13px;color:var(--frame);
  display:flex;align-items:center;user-select:none}
details>summary::-webkit-details-marker{display:none}
details>summary::before{content:'▸';display:inline-block;margin-right:8px;font-size:11px;
  color:var(--mute);transition:transform .12s linear}
details[open]>summary::before{transform:rotate(90deg)}
details>summary:hover{background:#f4f6f9}
details>*:not(summary){padding-left:12px;padding-right:12px}
details>.row:first-of-type{margin-top:8px}
@media (max-width:640px){
  .row,.row3,.row4,.fgrid{grid-template-columns:1fr}
  .setupsteps{grid-template-columns:1fr}
  table{display:block;overflow-x:auto;-webkit-overflow-scrolling:touch;white-space:nowrap}
  .backup-bar input{width:100%}
  header{gap:6px 10px;padding:8px 10px}
  header nav.main{flex-wrap:nowrap;overflow-x:auto;max-width:100%;padding-bottom:4px}
  header nav.aside{margin-left:0}
  .mark{display:none}
}
/* Yard device UI: big touch targets, minimal chrome. */
/* Yard device: the same FleetSheet language, at glove density.
   Same header, cards, and buttons as the desk — just bigger targets,
   so the yard page feels like FleetSheet in work boots, not another app. */
.yd{background:var(--bg);color:var(--ink);margin:0;font:16px/1.4 Calibri,Segoe UI,sans-serif}
.yd header{background:var(--frame);color:#fff;padding:10px 16px;display:flex;align-items:center;gap:10px}
.yd header .brand{font-size:20px;font-weight:700;letter-spacing:.02em}
.yd main{max-width:640px;margin:0 auto;padding:10px 12px 48px}
.yd .trow{display:block;background:var(--surface);border:1px solid #d0d5dd;border-radius:8px;
  padding:14px;margin:8px 0;color:var(--frame);text-decoration:none;font-size:17px}
.yd .trow small{display:block;color:var(--mute);font-size:13px}
.yd button.big,.yd .bigbtn{display:block;width:100%;text-align:center;padding:14px 18px;
  font-size:18px;margin:8px 0;border-radius:6px;background:var(--frame);color:#fff;border:0;cursor:pointer}
.yd form{background:var(--surface);border:1px solid #d0d5dd;border-radius:8px;padding:12px;margin:8px 0}
.yd label{display:block;font-size:13px;color:var(--mute);margin:8px 0 3px}
.yd input,.yd select{font-size:17px;padding:10px;width:100%;border:1px solid #c5cdd6;border-radius:4px;background:var(--surface)}
.yd .stat{background:var(--surface);border:1px solid #d0d5dd;border-radius:8px;padding:10px 12px;margin:8px 0}
.yd .qrbox{background:var(--surface);border:1px solid #d0d5dd;border-radius:8px;padding:20px;
  text-align:center;margin:16px 0;word-break:break-all}
.yd .code{font-family:monospace;font-size:14px;background:#eef1f5;padding:10px;border-radius:6px}
.yd h2{font-size:19px;color:var(--frame);margin:8px 0 6px}
.yd h3{font-size:16px;color:var(--frame);margin:8px 0 4px}
.yd a{color:var(--frame)}
/* Dashboard cards: capped lists, quiet "+ N more", audit popup. */
.dashgrid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;align-items:start}
.dashgrid>.pbox[data-title="Today"]{grid-row:span 2;align-self:stretch}
.dcard{background:var(--surface);border:1px solid #d0d5dd;border-radius:10px;padding:10px 12px;min-width:0}
.dcard.today{grid-row:span 4;align-self:stretch}
/* Today tiers: priority by styling, not labels. */
.todo.tier-must{font-size:16px;font-weight:600;border-left:4px solid var(--gold);padding-left:10px}
.todo.tier-can{font-size:14px}
.todo.tier-later{font-size:13px;color:var(--mute)}
.todo.tier-later a{color:var(--mute)}
.vbtn{background:var(--surface);color:var(--frame);border:1px solid var(--frame);border-radius:3px;
  font-size:11px;padding:2px 8px;cursor:pointer;margin-left:auto;white-space:nowrap}
.dcard h2.cardtitle .vbtn{margin-left:auto}
.donebox{margin-top:18px;background:#f1f7f1;border:1px solid #cfdfcf;border-radius:8px;padding:10px 14px}
.donebox h3{margin:0 0 4px;font-size:13px;color:#2e6b34}
.donebox .dtodo{padding:4px 0;font-size:13.5px;color:#33402f;border-bottom:1px dashed #dde8dd}
.donebox .dtodo:last-child{border-bottom:0}
.donebox .tick{color:#2e7d32;font-weight:800;margin-right:6px}
.donebox .dmeta{color:var(--mute);font-size:12px;margin-left:8px}
.donebox .daudit{margin:8px 0 0;font-size:12.5px}
.dcard h2.cardtitle{margin:0 0 6px;font-size:17px;color:var(--frame);display:flex;align-items:center}
.dcard h2.cardtitle .full{margin-left:auto;font-size:12px;font-weight:400}
.dcard h3{margin:8px 0 3px;font-size:13px;color:var(--frame)}
.dcard .mstat{margin:4px 0 8px}
.dcard .mstat span{display:block;font-size:12px;color:var(--mute)}
.dcard .mstat b{font-size:30px;color:var(--frame);font-weight:800;letter-spacing:-.5px}
.rgroup{font-size:19px;color:var(--frame);margin:30px 0 6px;padding-top:12px;border-top:2px solid #d0d5dd}
.more{display:inline-block;background:none;border:0;color:var(--mute);
  font-size:12px;padding:4px 8px;cursor:pointer}
.more:hover{color:var(--frame);text-decoration:underline}
.apop{position:fixed;inset:0;background:rgba(27,42,74,.45);z-index:100;display:flex;
  align-items:center;justify-content:center;padding:24px}
.apop[hidden]{display:none}
.apop-win{background:var(--surface);border-radius:10px;box-shadow:0 12px 40px rgba(0,0,0,.35);
  width:min(880px,94vw);height:min(640px,88vh);min-width:320px;min-height:240px;
  display:flex;flex-direction:column;resize:both;overflow:hidden}
.apop-bar{display:flex;align-items:center;gap:8px;background:var(--frame);color:#fff;
  padding:8px 12px;cursor:move;user-select:none;flex:0 0 auto}
.apop-bar .t{flex:1;font-weight:700;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.apop-bar button,.apop-bar a{background:none;border:1px solid rgba(255,255,255,.45);color:#fff;
  border-radius:4px;padding:2px 8px;font-size:12px;cursor:pointer;text-decoration:none;width:auto}
.apop-win iframe{flex:1;border:0;width:100%;background:var(--surface)}
@media (max-width:900px){
  .dashgrid{grid-template-columns:1fr}
  .pbox-grid{grid-template-columns:minmax(0,1fr)}
  .dcard.today{grid-row:auto}
  .dcard.hidephone{display:none}}
@media (max-width:700px){
  .apop{padding:0}
  .apop-win{width:100%;height:100%;border-radius:0;resize:none}
  .apop-bar{cursor:default}
}
/* Text size shifts the responsive breakpoints the way browser zoom does
   (CSS zoom alone can't move them): large=1.15x, xlarge=1.3x. */
@media (max-width:736px){
  body.ts-large .row,.row3,.fgrid{grid-template-columns:1fr}
  body.ts-large table{display:block;overflow-x:auto;-webkit-overflow-scrolling:touch;white-space:nowrap}
  body.ts-large .backup-bar input{width:100%}
  body.ts-large header{gap:6px 10px;padding:8px 10px}
  body.ts-large header nav.main{flex-wrap:nowrap;overflow-x:auto;max-width:100%;padding-bottom:4px}
  body.ts-large header nav.aside{margin-left:0}
  body.ts-large .mark{display:none}
}
@media (max-width:832px){
  body.ts-xlarge .row,.row3,.fgrid{grid-template-columns:1fr}
  body.ts-xlarge table{display:block;overflow-x:auto;-webkit-overflow-scrolling:touch;white-space:nowrap}
  body.ts-xlarge .backup-bar input{width:100%}
  body.ts-xlarge header{gap:6px 10px;padding:8px 10px}
  body.ts-xlarge header nav.main{flex-wrap:nowrap;overflow-x:auto;max-width:100%;padding-bottom:4px}
  body.ts-xlarge header nav.aside{margin-left:0}
  body.ts-xlarge .mark{display:none}
}
@media (max-width:805px){
  body.ts-large .apop{padding:0}
  body.ts-large .apop-win{width:100%;height:100%;border-radius:0;resize:none}
  body.ts-large .apop-bar{cursor:default}
}
@media (max-width:910px){
  body.ts-xlarge .apop{padding:0}
  body.ts-xlarge .apop-win{width:100%;height:100%;border-radius:0;resize:none}
  body.ts-xlarge .apop-bar{cursor:default}
}
@media (max-width:1035px){
  body.ts-large .dashgrid{grid-template-columns:1fr}
  body.ts-large .pbox-grid{grid-template-columns:minmax(0,1fr)}
  body.ts-large .dcard.today{grid-row:auto}
  body.ts-large .dcard.hidephone{display:none}
}
@media (max-width:1170px){
  body.ts-xlarge .dashgrid{grid-template-columns:1fr}
  body.ts-xlarge .pbox-grid{grid-template-columns:minmax(0,1fr)}
  body.ts-xlarge .dcard.today{grid-row:auto}
  body.ts-xlarge .dcard.hidephone{display:none}
}
"""

"""FleetSheet views: core — page chrome, auth/session plumbing (desk PIN, yard devices), dashboard, setup, export/print handlers. Mixins: CoreViews."""

__all__ = ['page', 'tabs', 'tabs_reports', 'tabs_boards', 'weekly_tabs', 'tabs_setup', 'tabs_invoice', 'tabs_quotes', 'tabs_money', '_cstat', '_trigger_opts', 'opts', 'lan_urls', 'phone_card', '_nav_section', '_local_qr_img', 'money_val', 'quote_expiry_panel', 'task_nudge', 'more_link', 'DASH_CAP', 'view_button', 'AUDIT_TABLE_JS', 'news_strip', 'combo_field', 'combo_opts', 'COMBO_JS', 'capped_table', 'SETUP_FLOW', 'next_setup_step', 'setup_in_progress']

# How many rows a landing-page list shows before the quiet "+ N more" hint.
DASH_CAP = 5


def more_link(total, shown, audit_url, audit_title):
    """Quiet '+ N more' hint under a capped list; opens the audit popup.

    The audit views (/today/all, /money/*/audit, /assets/all, ...) stay complete —
    this never hides anything, it just keeps the working list short."""
    n = total - shown
    if n <= 0:
        return ""
    return (f"<button type='button' class='more' data-audit='{html.escape(audit_url, quote=True)}' "
            f"data-title='{html.escape(audit_title)}'>+ {n} more</button>")


def combo_field(fid, name, options, value="", placeholder="Type to search…", label="",
                required=False, narrow=False):
    """Typeahead combobox (walkthrough #3, global): a text input backed by a
    datalist. Typing filters the known values; picking one or typing free text
    both work — nothing is forced to match. `options` is a list of
    (value, label[, id]) tuples; the visible text submits as `name`, and the
    data-id syncs to hidden fields via COMBO_JS."""
    opts = "".join(
        f"<option value=\"{html.escape(lab, quote=True)}\""
        f"{(' data-id=\"' + html.escape(i, quote=True) + '\"') if i else ''}>"
        for _v, lab, i in [t if len(t) == 3 else (t[0], t[1], "") for t in options])
    cls = "w-sm" if narrow else ""
    req = " required" if required else ""
    lab = f"<label>{html.escape(label)}</label>" if label else ""
    return (
        f"<div>{lab}<input id=\"{fid}\" name=\"{html.escape(name, quote=True)}\" "
        f"list=\"{fid}_list\" value=\"{html.escape(value, quote=True)}\" "
        f"placeholder=\"{html.escape(placeholder, quote=True)}\"{req} class=\"{cls}\" "
        f"autocomplete=\"off\" data-combo=\"1\">"
        f"<datalist id=\"{fid}_list\">{opts}</datalist></div>"
    )


def combo_opts(rows, value_key, label_key, selected="", disp=None):
    """Build combo_field options from row dicts, plus the current display text.
    Returns (options, current). Display defaults to 'label (value)', matching
    the old opts() dropdown look; `disp(v, lab)` overrides the display text.
    `selected` is the currently-selected value (or '')."""
    options = []
    current = ""
    for r in rows:
        v, lab = str(r[value_key]), str(r[label_key])
        d = disp(v, lab) if disp else f"{lab} ({v})"
        options.append((v, d, v))
        if str(v) == str(selected or ""):
            current = d
    return options, current


COMBO_JS = """
<script>
/* Typeahead combobox sync: when the visible text exactly matches a known
   option, submit its id; otherwise submit the free text via data-freetext. */
document.querySelectorAll('input[data-combo]').forEach(function(inp){
  var dl = document.getElementById(inp.getAttribute('list'));
  if(!dl) return;
  function sync(){
    var t = inp.value.trim(), id = '', free = '';
    Array.prototype.forEach.call(dl.options, function(o){
      if(o.value.trim() === t){ id = o.getAttribute('data-id') || ''; }
    });
    var hid = document.getElementById(inp.id + '_id');
    var hfree = document.getElementById(inp.id + '_free');
    if(hid) hid.value = id;
    if(hfree) hfree.value = id ? '' : t;
  }
  inp.addEventListener('input', sync);
  inp.addEventListener('change', sync);
  sync();
});
</script>
"""


def capped_table(headers, row_html_list, cap=5, empty_note="None yet."):
    """A table showing `cap` rows with a quiet '+ N more' expander (walkthrough #3:
    Setup lists and other full tables obey the 5-cap like everything else).
    When empty, a one-line hint (Jason 2026-10-07 compact standard).
    The '+ N more' expands into a scrollable div (Jason 2026-10-07) so the
    page never scrolls off."""
    rows = row_html_list
    if not rows:
        return f"<p class='hint' style='margin:4px 0'>{html.escape(empty_note)}</p>"
    shown = "".join(rows[:cap])
    extra = ""
    toggle = ""
    if len(rows) > cap:
        extra_rows = "".join(rows[cap:])
        extra = (f"<div class='cap-extra' hidden style='max-height:220px;overflow-y:auto;"
                 f"border:1px solid #e0e4ea;border-radius:4px;margin-top:4px'>"
                 f"<table><tr>{''.join(f'<th>{html.escape(h)}</th>' for h in headers)}</tr>"
                 f"{extra_rows}</table></div>")
        toggle = (f"<p class='mute'><button type='button' class='more' "
                  f"onclick=\"this.parentElement.nextElementSibling.hidden=false;"
                  f"this.parentElement.remove()\">+ {len(rows) - cap} more</button></p>")
    return (f"<table><tr>{''.join(f'<th>{html.escape(h)}</th>' for h in headers)}</tr>"
            f"{shown}</table>{toggle}{extra}")


AUDIT_POPUP_HTML = """
<div class="apop" id="apop" hidden>
  <div class="apop-win" role="dialog" aria-label="audit">
    <div class="apop-bar"><span class="t"></span>
      <a class="fullpage" href="#" target="_blank">Full page</a>
      <button data-apop-reload>Reload</button>
      <button data-apop-close>Close</button>
    </div>
    <iframe title="audit"></iframe>
  </div>
</div>
"""

PBOX_JS = """
<script>
(function(){
  // Page boxes: collapsible, with a per-page layout lock. Unlocked, boxes
  // drag to reorder and flip full/half width; locked, the layout freezes.
  // Everything is fenced: boxes stay in a 2-col grid (1 col when narrow),
  // so they can never overlap or slide offscreen. Persisted per-page.
  var KEY = 'pbox:' + location.pathname + location.search;
  var state = {};
  try { state = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch(e){}
  function persist(){ try { localStorage.setItem(KEY, JSON.stringify(state)); } catch(e){} }
  function locked(){ return state.locked !== false; }
  var main = document.querySelector('main');
  if (!main) return;
  // Wrap each h2/h3 section in a .pbox. A section starts at a direct
  // child that IS an h2/h3, or whose first element child is one (the
  // header-row pattern: <div><h2>..</h2><a class=btn>..</a></div>).
  var boxes = [];
  // Box candidates: direct children of main, plus the dashboard cards
  // inside .dashgrid (each section.dcard carries its own h2.cardtitle).
  var cands = [];
  Array.prototype.forEach.call(main.children, function(el){
    if (el.classList && el.classList.contains('dashgrid')) {
      Array.prototype.forEach.call(el.children, function(c){
        cands.push({el: c, parent: el, pkey: 'dashgrid'});
      });
    } else {
      cands.push({el: el, parent: main, pkey: 'main'});
    }
  });
  var cur = null, curParent = null;
  function headOf(el){
    if (/^H[23]$/.test(el.tagName)) return el;
    var f = el.firstElementChild;
    if (f && /^H[23]$/.test(f.tagName)) return f;
    if (el.tagName === 'SECTION') {
      var h = el.querySelector('h2, h3');
      if (h) return h;
    }
    return null;
  }
  cands.forEach(function(c){
    var el = c.el, sh = headOf(el);
    if (el.classList && el.classList.contains('pbox')) {
      // Pre-wrapped by the server (e.g. dashboard cards): register directly.
      // Without this the heading is nested DIV>SECTION>H2, headOf() misses it,
      // and the box silently gets no arrows, grip, or drag (seen 2026-10-07).
      if (!el.dataset.title) {
        var h0 = el.querySelector('h2, h3');
        el.dataset.title = h0 ? h0.textContent.trim().slice(0, 40) : 'Box';
      }
      el.dataset.pkey = el.dataset.pkey || c.pkey;
      boxes.push(el);
      cur = null;
      curParent = null;
      return;
    }
    if (sh) {
      cur = document.createElement('div');
      cur.className = 'pbox';
      cur.dataset.title = sh.textContent.trim().slice(0, 40);
      cur.dataset.pkey = c.pkey;
      c.parent.insertBefore(cur, el);
      boxes.push(cur);
      curParent = c.parent;
    } else if (c.pkey === 'dashgrid' || (cur && curParent !== c.parent)) {
      // Dashboard cards stand alone: never absorb the backup bar or
      // anything else into the previous card's box.
      cur = null;
    }
    if (cur) cur.appendChild(el);
  });
  if (!boxes.length) return;
  // Fence: group consecutive main-keyed boxes into 2-col grids.
  // Dashboard boxes stay in .dashgrid (already a grid).
  (function(){
    var run = [];
    function flush(){
      if (!run.length) return;
      var g = document.createElement('div');
      g.className = 'pbox-grid';
      run[0].parentNode.insertBefore(g, run[0]);
      run.forEach(function(b){ g.appendChild(b); });
      run = [];
    }
    boxes.forEach(function(b){
      if (b.dataset.pkey === 'dashgrid') { flush(); return; }
      if (run.length && b.previousElementSibling !== run[run.length-1]) flush();
      run.push(b);
    });
    flush();
  })();
  // Restore order, per parent (wrapper-safe: re-append inside the box's
  // own grid, dashboard cards stay inside .dashgrid).
  var order = state.order || [];
  order.forEach(function(it){
    var t = (it && it.t) || it, pk = (it && it.p) || 'main';
    var b = null;
    for (var i = 0; i < boxes.length; i++) {
      if (boxes[i].dataset.pkey === pk && boxes[i].dataset.title === t) { b = boxes[i]; break; }
    }
    if (b && b.parentNode) b.parentNode.appendChild(b);
  });
  // Lock toggle: lives in the blue header, right-justified (walkthrough #3).
  var lockBtn = document.createElement('button');
  lockBtn.type = 'button';
  lockBtn.className = 'pbox-lock';
  var hdrSlot = document.getElementById('hdr-lock');
  if (hdrSlot) hdrSlot.appendChild(lockBtn);
  else main.insertBefore(lockBtn, main.firstChild);
  function defSpan(box){ return box.dataset.pkey === 'dashgrid' ? 'half' : 'full'; }
  function curSpan(box){ return (state.span || {})[box.dataset.title] || defSpan(box); }
  function saveOrder(){
    state.order = Array.prototype.map.call(
      main.querySelectorAll('.pbox'),
      function(x){ return {p: x.dataset.pkey || 'main', t: x.dataset.title}; });
    persist();
  }
  // Arrow mover: the reliable reorder — no drag acrobatics, no drop-target
  // timing, works below the fold and on touch. Swaps with the adjacent box.
  function moveBox(box, dir){
    var sib = dir < 0 ? box.previousElementSibling : box.nextElementSibling;
    while (sib && !(sib.classList && sib.classList.contains('pbox')))
      sib = dir < 0 ? sib.previousElementSibling : sib.nextElementSibling;
    if (!sib) return;
    if (dir < 0) box.parentNode.insertBefore(box, sib);
    else box.parentNode.insertBefore(box, sib.nextSibling);
    saveOrder();
  }
  function renderSpan(box){
    var v = curSpan(box);
    if (v === defSpan(box)) box.removeAttribute('data-span'); else box.dataset.span = v;
    var wb = box.querySelector('.pbox-width');
    if (wb) wb.textContent = v === 'full' ? 'Half' : 'Full';
  }
  function applyLock(){
    var isLocked = locked();
    lockBtn.textContent = isLocked ? '🔒 Layout locked' : '🔓 Layout unlocked';
    lockBtn.title = isLocked
      ? 'Unlock to move boxes and change widths'
      : 'Drag a box by its heading, or use the ↑ ↓ arrows, to move it. Half/Full sets its width. Click here to lock.';
    boxes.forEach(function(box){
      var h = box.querySelector('h2, h3');
      box.draggable = !isLocked;
      if (!h) return;
      h.style.cursor = isLocked ? '' : 'move';
      var wb = h.querySelector('.pbox-width');
      if (wb) wb.style.display = isLocked ? 'none' : '';
      var gr = h.querySelector('.pbox-grip');
      if (gr) gr.style.display = isLocked ? 'none' : '';
      Array.prototype.forEach.call(h.querySelectorAll('.pbox-move'), function(m){
        m.style.display = isLocked ? 'none' : '';
      });
    });
  }
  lockBtn.onclick = function(){
    state.locked = !locked();
    persist();
    applyLock();
  };
  boxes.forEach(function(box){
    var h = box.querySelector('h2, h3');
    if (!h) return;
    var title = box.dataset.title;
    // Collapse via double-click on the heading (Jason 2026-10-06): no
    // toggle button — the heading itself is the control.
    function toggleCollapse(){
      var c = state.collapsed || {};
      c[title] = !c[title];
      state.collapsed = c;
      persist();
      applyCollapse(box, c[title]);
    }
    applyCollapse(box, (state.collapsed || {})[title]);
    // Move arrows: hidden while locked via applyLock() (Jason 2026-10-06).
    var mvUp = document.createElement('button');
    mvUp.type = 'button'; mvUp.className = 'pbox-move'; mvUp.textContent = '↑';
    mvUp.title = 'Move this box up';
    mvUp.onclick = function(){ moveBox(box, -1); };
    var mvDn = document.createElement('button');
    mvDn.type = 'button'; mvDn.className = 'pbox-move'; mvDn.textContent = '↓';
    mvDn.title = 'Move this box down';
    mvDn.onclick = function(){ moveBox(box, 1); };
    h.insertBefore(mvDn, h.firstChild);
    h.insertBefore(mvUp, mvDn);
    // Grip handle: the visible "grab here" cue while unlocked.
    var grip = document.createElement('span');
    grip.className = 'pbox-grip';
    grip.textContent = '⋮⋮';
    grip.title = 'Drag to move this box';
    h.insertBefore(grip, h.firstChild);
    // Double-click / double-tap the heading collapses (not the buttons).
    h.addEventListener('dblclick', function(e){
      if (e.target.closest('button')) return;
      toggleCollapse();
    });
    h.title = 'Double-click to collapse/expand';
    // Width toggle (unlock-gated).
    var wb = document.createElement('button');
    wb.type = 'button';
    wb.className = 'pbox-width';
    wb.title = 'Full / half width';
    wb.onclick = function(){
      var s = state.span || {};
      var next = curSpan(box) === 'full' ? 'half' : 'full';
      if (next === defSpan(box)) delete s[title]; else s[title] = next;
      state.span = s;
      persist();
      renderSpan(box);
    };
    h.insertBefore(wb, mvDn.nextSibling);
    renderSpan(box);
    // Drag to reorder (unlock-gated).
    box.addEventListener('dragstart', function(e){
      if (locked()) { e.preventDefault(); return; }
      e.dataTransfer.setData('text/plain', title);
      e.dataTransfer.effectAllowed = 'move';
      box.classList.add('dragging');
    });
    box.addEventListener('dragend', function(){ box.classList.remove('dragging'); });
    box.addEventListener('dragenter', function(e){
      if (!locked()) { e.preventDefault(); box.classList.add('drop-target'); }
    });
    box.addEventListener('dragleave', function(){ box.classList.remove('drop-target'); });
    box.addEventListener('dragover', function(e){
      if (!locked()) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; }
    });
    box.addEventListener('drop', function(e){
      if (locked()) return;
      e.preventDefault();
      e.stopPropagation(); // container also listens; the box handles it.
      box.classList.remove('drop-target');
      var srcTitle = e.dataTransfer.getData('text/plain');
      var src = null;
      for (var i = 0; i < boxes.length; i++) {
        if (boxes[i].dataset.title === srcTitle) { src = boxes[i]; break; }
      }
      // Same parent is the real requirement — the pkey check silently
      // rejected drops it shouldn't have (2026-10-04).
      if (src && src !== box && src.parentNode === box.parentNode) {
        var parent = box.parentNode;
        // Drop onto the box below: insert AFTER it; drop onto the box
        // above: insert BEFORE it. (Plain insertBefore(src, box) is a
        // no-op when src already sits right above box — 2026-10-04.)
        var kids = Array.prototype.slice.call(parent.children);
        if (kids.indexOf(src) < kids.indexOf(box)) {
          parent.insertBefore(src, box.nextSibling);
        } else {
          parent.insertBefore(src, box);
        }
        saveOrder();
      }
    });
  });
  // Container-level drop: releasing over a grid GAP (not directly on a box)
  // used to snap the box back — the drop event never reached a box.
  // The box's own parent accepts the drop and slots it under the cursor.
  // (2026-10-04: the Compliance-card snap-back.)
  (function(){
    var parents = [];
    boxes.forEach(function(b){
      if (parents.indexOf(b.parentNode) < 0) parents.push(b.parentNode);
    });
    parents.forEach(function(container){
      container.addEventListener('dragover', function(e){
        if (!locked()) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; }
      });
      container.addEventListener('drop', function(e){
        if (locked()) return;
        e.preventDefault();
        var srcTitle = e.dataTransfer.getData('text/plain');
        var src = null;
        for (var i = 0; i < boxes.length; i++) {
          if (boxes[i].dataset.title === srcTitle) { src = boxes[i]; break; }
        }
        if (!src || src.parentNode !== container) return;
        var el = document.elementFromPoint(e.clientX, e.clientY);
        var target = (el && el.closest) ? el.closest('.pbox') : null;
        if (target && target !== src && target.parentNode === container) {
          var r = target.getBoundingClientRect();
          if ((e.clientY - r.top) > r.height / 2) {
            container.insertBefore(src, target.nextSibling);
          } else {
            container.insertBefore(src, target);
          }
        } else {
          container.appendChild(src);
        }
        saveOrder();
      });
    });
  })();
  applyLock();
  function applyCollapse(box, collapsed){
    var hh = box.querySelector('h2, h3');
    Array.prototype.forEach.call(box.children, function(el){
      // Never hide the heading itself or the row that carries it —
      // that's where the expand toggle lives.
      if (el !== hh && !el.contains(hh)) el.style.display = collapsed ? 'none' : '';
    });
  }
})();
</script>
"""

AUDIT_POPUP_JS = """
<script>
function openAudit(url, title){
  var w = document.getElementById('apop'); if(!w) return;
  w.querySelector('.t').textContent = title || 'Everything';
  w.querySelector('a.fullpage').href = url;
  w.querySelector('iframe').src = url;
  w.hidden = false; document.body.style.overflow = 'hidden';
}
function closeAudit(){
  var w = document.getElementById('apop'); if(!w) return;
  w.hidden = true; w.querySelector('iframe').src = 'about:blank';
  document.body.style.overflow = '';
}
document.addEventListener('click', function(e){
  var m = e.target.closest('.more,.vbtn');
  if (m) { openAudit(m.getAttribute('data-audit'), m.getAttribute('data-title')); return; }
  if (e.target.closest('[data-apop-close]')) { closeAudit(); return; }
  var r = e.target.closest('[data-apop-reload]');
  if (r) { var f = r.closest('.apop-win').querySelector('iframe'); f.src = f.src; return; }
  if (e.target.closest('.apop') && !e.target.closest('.apop-win')) { closeAudit(); }
});
document.addEventListener('keydown', function(e){ if (e.key === 'Escape') closeAudit(); });
(function(){
  var bar = document.querySelector('.apop-bar'), win = document.querySelector('.apop-win');
  if (!bar || !win) return;
  var drag = false, sx = 0, sy = 0, ox = 0, oy = 0;
  bar.addEventListener('pointerdown', function(e){
    if (window.innerWidth <= 700) return;
    if (e.target.closest('button') || e.target.closest('a')) return;
    drag = true; sx = e.clientX; sy = e.clientY;
    var r = win.getBoundingClientRect(); ox = r.left; oy = r.top;
    win.style.position = 'fixed'; win.style.left = ox + 'px'; win.style.top = oy + 'px';
    win.style.margin = '0';
    try { bar.setPointerCapture(e.pointerId); } catch (err) {}
  });
  bar.addEventListener('pointermove', function(e){
    if (!drag) return;
    win.style.left = Math.max(0, ox + e.clientX - sx) + 'px';
    win.style.top = Math.max(0, oy + e.clientY - sy) + 'px';
  });
  bar.addEventListener('pointerup', function(){ drag = false; });
  bar.addEventListener('pointercancel', function(){ drag = false; });
})();
</script>
"""

def money_val(v):
    """Format any value for a money <input>: always two decimals ('150.50')."""
    try:
        return f"{float(v or 0):.2f}"
    except (TypeError, ValueError):
        return "0.00"

def quote_expiry_panel(con, quote_no):
    """Amber non-blocking quote-expiry nudge. Same pattern as the PO amber
    nudge: the expiry is logged on the quote record, the ticket/WO/invoice
    carries the quote_no, and the warning is presented when problematic —
    never a gate, never printed as a line."""
    qc = engine.quote_check(con, quote_no)
    if not qc["expired"]:
        return ""
    return f"""
    <div style="background:#fdf3e3;border:1px solid #e8b923;border-radius:8px;padding:12px 16px;margin:12px 0">
      <b>Quote check:</b> quote {html.escape(qc['quote_no'])} expired {html.escape(qc['date_str'])} —
      pricing may have changed. The money on this record is the quote's; re-price before it goes out.
    </div>"""

TIPS_ON = True

# Desk text-size preference ("standard" | "large" | "xlarge"), set per
# request by app.py from the ui_text_size option. Rendered as CSS zoom on
# <html> so the whole px-based stylesheet scales exactly like browser zoom.
TEXT_SIZE = "standard"
TEXT_ZOOM = {"standard": "", "large": "1.15", "xlarge": "1.3"}

def _text_size_style() -> str:
    z = TEXT_ZOOM.get(TEXT_SIZE, "")
    return f"<style>html{{zoom:{z}}}</style>" if z else ""

def _body_classes(extra="") -> str:
    cls = []
    if not TIPS_ON:
        cls.append("notips")
    if TEXT_SIZE in ("large", "xlarge"):
        cls.append("ts-" + TEXT_SIZE)
    if extra:
        cls.append(extra)
    return " ".join(cls)

def lan_urls(port: int = 8765) -> list[str]:
    found = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            found.append(ip)
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found and not ip.startswith("127."):
                found.append(ip)
    except OSError:
        pass
    return [f"http://{ip}:{port}" for ip in found]


def _local_qr_img(url: str) -> str:
    """Inline <img> for a QR code generated locally with segno — no outside service."""
    try:
        import segno
    except ImportError:
        return ""
    uri = segno.make(url, error="m").png_data_uri(scale=6)
    return (f'<img src="{html.escape(uri)}" width="180" height="180" '
            'alt="Scan to open FleetSheet" '
            'style="background:var(--surface);padding:8px;border-radius:6px">')


def phone_card() -> str:
    # MANUAL-SOURCE (removed from screen 2026-10-08, belongs in manual):
    # - "Desk: http://127.0.0.1:8765. Phone on the same Wi-Fi: <addr> — scan
    #   the QR, or type that address."
    # - "QR unavailable on this machine — type the address below into the
    #   phone's browser."
    phones = lan_urls()
    target = phones[0] if phones else "http://127.0.0.1:8765"
    qr_img = _local_qr_img(target)
    qr_block = (f"<p>{qr_img}</p>" if qr_img else "")
    return f"""
        <div class="card" style="margin:10px 0">
          <p><b>Browser Access at:</b> {html.escape(target)}</p>
          <p>or Scan QR Code</p>
          {qr_block}
        </div>
        """


TIPS_ON = True


# Which top-nav section a given path belongs to, for active-state highlighting.
_NAV_SECTIONS = [
    ("ticketnew", ("/ticket/new", "/wos", "/wo/", "/quote", "/changes")),
    ("acct", ("/invoice", "/pay", "/credit", "/petty", "/money")),
    ("assets", ("/assets", "/unit")),
    ("compliance", ("/compliance", "/compack", "/ucompliance")),
    ("reports", ("/reports", "/tickets", "/ticket/", "/export")),
    ("setup", ("/setup", "/customers", "/customer", "/sites", "/site")),
]


def _nav_section(path):
    if path == "/":
        return "dash"
    for section, prefixes in _NAV_SECTIONS:
        if any(path.startswith(p) for p in prefixes):
            return section
    return ""


def view_button(audit_url, audit_title):
    """One small always-visible View button that opens the audit popup.
    Quiet like '+ N more', but always there — even when the list is short."""
    return (f"<p style='text-align:right;margin:8px 0 0'>"
            f"<button type='button' class='vbtn' style='margin-left:0' "
            f"data-audit='{html.escape(audit_url, quote=True)}' "
            f"data-title='{html.escape(audit_title)}'>View</button></p>")


AUDIT_TABLE_JS = """
<script>
function auditFilter(t, q){
  q = q.toLowerCase();
  Array.from(t.rows).forEach(function(r, i){
    if (i === 0) return;
    r.style.display = r.textContent.toLowerCase().indexOf(q) >= 0 ? '' : 'none';
  });
}
function auditSort(t, c){
  var rows = Array.from(t.rows).slice(1);
  var asc = t.getAttribute('data-sorted') != String(c);
  rows.sort(function(a, b){
    var x = a.cells[c] ? a.cells[c].textContent.trim() : '';
    var y = b.cells[c] ? b.cells[c].textContent.trim() : '';
    var xn = parseFloat(x.replace(/[$,]/g, '')), yn = parseFloat(y.replace(/[$,]/g, ''));
    var cmp = (!isNaN(xn) && !isNaN(yn) && x !== '' && y !== '') ? xn - yn : x.localeCompare(y);
    return asc ? cmp : -cmp;
  });
  rows.forEach(function(r){ t.appendChild(r); });
  t.setAttribute('data-sorted', asc ? String(c) : '');
}
document.querySelectorAll('table.audit').forEach(function(t){
  Array.from(t.rows[0].cells).forEach(function(th, c){
    if (th.textContent.trim()){
      th.style.cursor = 'pointer'; th.title = 'Sort';
      th.onclick = function(){ auditSort(t, c); };
    }
  });
});
</script>
"""


def _ack_forms(key, path, minutes=30, days=7):
    """Snooze (minutes, stepper) / Sleep (days, stepper) forms riding
    the alert-ack machinery. Steppers are always visible: minus on the
    left of the number, plus on the right (walkthrough 2026-10-04 —
    the old hover-only number spinner hid the +/- until hovered).
    Walkthrough 2026-10-04 #3: the two groups sit right-justified and
    apart inside .ack-right; number inputs are narrow (1-2 digits)."""
    key = html.escape(key, quote=True)
    nxt = html.escape(path, quote=True)
    return (
        f"<span class='ack-right'>"
        f"<form method='post' action='/alert/ack' class='ackf'>"
        f"<input type='hidden' name='key' value='{key}'>"
        f"<input type='hidden' name='next' value='{nxt}'>"
        f"<span class='stepper'><button type='button' data-step='-1' title='Less time'>&minus;</button>"
        f"<input type='number' name='minutes' value='{minutes}' min='1' max='1440' step='1' title='Snooze minutes'>m"
        f"<button type='button' data-step='1' title='More time'>+</button></span>"
        f"<button type='submit' name='action' value='snooze' title='Snooze this item'>Snooze</button></form>"
        f"<form method='post' action='/alert/ack' class='ackf'>"
        f"<input type='hidden' name='key' value='{key}'>"
        f"<input type='hidden' name='next' value='{nxt}'>"
        f"<span class='stepper'><button type='button' data-step='-1' title='Fewer days'>&minus;</button>"
        f"<input type='number' name='days' value='{days}' min='1' max='90' step='1' title='Sleep days'>d"
        f"<button type='button' data-step='1' title='More days'>+</button></span>"
        f"<button type='submit' name='action' value='dismiss' title='Sleep this item'>Sleep</button></form>"
        f"</span>"
    )


def news_strip(alerts, path="/", top_items=None, alert_total=None, cats=None):
    """Two tiers, visually distinct. The ticker is the top-of-the-day glance;
    each shoulder-tap gets its own gold-bordered box: boxed means this needs
    a decision from you.

    All five items carry an action-verb button ("Record payment", "Set date",
    ...) naming the decision — the button goes where the decision gets made —
    plus Snooze/Sleep, so the operator sees what's coming and can act on any
    of the five. Anything past five alerts is a quiet "+ N more". Handling,
    snoozing, or sleeping an item lets the next one roll up. Calm line when
    there is nothing to tap about (dashboard only).

    `cats` is the enabled ticker-category set (from get_ticker_cats). When
    provided, a quiet Filter button at the strip's right end opens a small
    popover to choose which categories earn a slot. (2026-10-06)"""
    bits = ""
    for i, it in enumerate(top_items or []):
        href = html.escape(it['href'], quote=True)
        key = it.get("key") or ""
        verb = it.get("verb") or "Open"
        btns = ""
        if key:
            btns = (f"<a class='vbtn' href='{href}' title='{html.escape(verb, quote=True)}'>{html.escape(verb)}</a>"
                    + _ack_forms(key, path, minutes=30, days=2))
        bits += (
            f"<div class='tap top'><span class='msg'>Top of the day</span>"
            f"<a href='{href}'>{html.escape(it['text'])}</a>{btns}</div>"
        )
    tick_keys = [it.get("key") for it in (top_items or []) if it.get("key")]
    util_row = ""
    if tick_keys:
        # Clear: dismiss every ticker item currently showing, for today.
        util_row += (
            f"<form method='post' action='/alert/ack' class='ackf' style='display:inline'>"
            f"<input type='hidden' name='keys' value='{html.escape(','.join(tick_keys), quote=True)}'>"
            f"<input type='hidden' name='next' value='{html.escape(path, quote=True)}'>"
            f"<button type='submit' name='action' value='clear' title='Clear the ticker for today'>Clear</button></form>"
        )
    for i, a in enumerate(alerts or []):
        key = a["key"]
        verb = a.get("verb") or "Handle now"
        href = html.escape(a['href'], quote=True)
        lv = int(a.get("level") or 0)
        go = f"<a class='go' href='{href}'>{html.escape(verb)}</a>"
        bits += (
            f"<div class='tapbox lv{lv}'><span class='msg'>{html.escape(a['text'])}</span>"
            f"{go}{_ack_forms(key, path)}"
            f"</div>"
        )
    if alert_total is not None and alert_total > len(alerts or []):
        more = alert_total - len(alerts or [])
        bits += (f"<div class='tap calm'><span class='msg'>+ {more} more — "
                 f"handle, snooze, or sleep above and the next one rolls up.</span></div>")
    if cats is not None:
        # Category filter: quiet funnel button at the strip's right end.
        # Popover with three checkboxes + Save, posting to /ticker/cats.
        boxes = ""
        for c in engine.TICKER_CATS:
            chk = " checked" if c in cats else ""
            boxes += (f"<label><input type='checkbox' name='cat_{c}' value='1'{chk}> "
                      f"{html.escape(engine.CAT_LABELS[c])}</label>")
        util_row += (
            f"<div class='tapbox filterbox' style='display:inline-block'>"
            f"<button type='button' class='vbtn' title='Choose which alerts show on the ticker' "
            f"onclick=\"var f=document.getElementById('tickf');"
            f"f.style.display=(f.style.display==='none'?'block':'none')\">⧩ Filter</button>"
            f"<div id='tickf' class='tickfilter' style='display:none'>"
            f"<form method='post' action='/ticker/cats'>{boxes}"
            f"<input type='hidden' name='next' value='{html.escape(path, quote=True)}'>"
            f"<button type='submit' class='vbtn'>Save</button>"
            f"</form></div></div>"
        )
    if util_row:
        bits += f"<div style='display:flex;gap:8px;align-items:center;margin:4px 0'>{util_row}</div>"
    if not bits:
        if path == "/":
            return ("<div class='news'><div class='tap calm'>"
                    "<span class='msg'>Nothing overdue — get a head start on tomorrow.</span>"
                    "</div></div>")
        return ""
    n = len(alerts or []) + len(top_items or [])
    if n == 0:
        return ""
    return (f"<details class='news-wrap' style='margin:0' "
            f"ontoggle=\"this.querySelector('summary').textContent="
            f"'Alerts ({n}) — click to '+(this.open?'collapse':'expand')\">"
            f"<summary style='cursor:pointer;font-size:12px;color:#666;padding:4px 0'>"
            f"Alerts ({n}) — click to expand</summary>"
            f"<div class='news'>{bits}</div></details>")


# Heartbeat: every open FleetSheet page (desk, yard, PIN-lock, EULA) tells the
# server "I'm still here" once a minute. When every tab is closed the beats
# stop and the server's idle watchdog shuts it down — closing the browser IS
# closing FleetSheet. On failure a slim banner appears once; no auto-reload.
HEARTBEAT_JS = """
<script>
(function(){
  var lost=false, warned=false;
  function showLost(){
    if(lost)return;lost=true;
    var b=document.createElement('div');
    b.textContent='Connection to FleetSheet lost.';
    b.style.cssText='position:fixed;top:0;left:0;right:0;background:#b42318;color:#fff;'+
      'text-align:center;padding:8px;font:14px Calibri,Segoe UI,sans-serif;z-index:9999';
    if(document.body)document.body.insertBefore(b,document.body.firstChild);
  }
  function onBefore(e){e.preventDefault();e.returnValue='';}
  function armBefore(on){
    if(on&&!warned){warned=true;window.addEventListener('beforeunload',onBefore);}
    else if(!on&&warned){warned=false;window.removeEventListener('beforeunload',onBefore);}
  }
  // In-app clicks and form submits disarm the close warning first, so
  // ordinary navigation never nags — only a real window close does.
  document.addEventListener('click',function(e){
    if(e.target&&e.target.closest&&e.target.closest('a'))armBefore(false);
  },true);
  document.addEventListener('submit',function(){armBefore(false);},true);
  function setYardNote(n){
    var el=document.getElementById('fs-yardnote');
    if(n>0){
      var t=n+' yard device'+(n===1?'':'s')+' connected';
      if(!el){
        el=document.createElement('span');
        el.id='fs-yardnote';el.className='yardnote';
        var h=document.querySelector('header .brand');
        if(h&&h.parentNode)h.parentNode.insertBefore(el,h.nextSibling);
      }
      if(el&&el.textContent!==t)el.textContent=t;
    }else if(el){el.remove();}
    armBefore(n>0);
  }
  function beat(){
    try{
      fetch('/heartbeat',{method:'POST',keepalive:true}).then(function(r){
        if(r.status===200)return r.json();return null;
      }).then(function(j){
        if(j&&typeof j.yard_clients==='number')setYardNote(j.yard_clients);
      }).catch(showLost);
    }catch(e){showLost();}
  }
  beat();
  setInterval(beat,60000);
})();
</script>"""

# Set by app.py at startup to a callable returning the number of yard
# devices heartbeating recently. Lets desk pages show a quiet "N yard
# devices connected" note (and arm the close warning) without a
# views_core -> app import cycle.
yard_status_hook = None


# Yard heartbeat: /d pages beat every 15s instead of 60s so a desk-window
# close is noticed inside the grace window. When the server reports a
# shutdown countdown, the page shows a plain banner and auto-submits any
# open form the user has touched (dirty-tracked), so a half-filled
# check-in/check-out isn't lost. Server-side validation still applies —
# an unnamed entry is rejected, never written half-formed.
HEARTBEAT_JS_YARD = """
<script>
(function(){
  var lost=false, remain=null, saved=false, ticking=false;
  function showLost(){
    if(lost)return;lost=true;
    var b=document.createElement('div');
    b.textContent='Connection to FleetSheet lost.';
    b.style.cssText='position:fixed;top:0;left:0;right:0;background:#b42318;color:#fff;'+
      'text-align:center;padding:8px;font:14px Calibri,Segoe UI,sans-serif;z-index:9999';
    if(document.body)document.body.insertBefore(b,document.body.firstChild);
  }
  function showBanner(){
    var b=document.getElementById('fs-shutdown');
    if(!b){
      b=document.createElement('div');b.id='fs-shutdown';
      b.style.cssText='position:fixed;top:0;left:0;right:0;background:#7a5c14;color:#fff;'+
        'text-align:center;padding:8px;font:14px Calibri,Segoe UI,sans-serif;z-index:9998';
      if(document.body)document.body.insertBefore(b,document.body.firstChild);
    }
    b.textContent='The desk window closed. Server stops in '+remain+'s — entries save as you go.';
  }
  function markDirty(){
    var fs=document.querySelectorAll('form[data-autosave]');
    for(var i=0;i<fs.length;i++){
      (function(f){f.addEventListener('input',function(){f.setAttribute('data-dirty','1');});})(fs[i]);
    }
  }
  function markClean(){
    // A real submit means the user saved it themselves — don't re-fire.
    var fs=document.querySelectorAll('form[data-autosave]');
    for(var i=0;i<fs.length;i++){
      (function(f){f.addEventListener('submit',function(){f.removeAttribute('data-dirty');});})(fs[i]);
    }
  }
  function autosaveDirty(){
    if(saved)return;saved=true;
    var fs=document.querySelectorAll('form[data-autosave][data-dirty="1"]');
    for(var i=0;i<fs.length;i++){
      try{fetch(fs[i].action,{method:'POST',body:new FormData(fs[i])}).catch(function(){});}
      catch(e){}
    }
  }
  function beat(){
    try{
      fetch('/heartbeat',{method:'POST',keepalive:true}).then(function(r){
        if(r.status===200)return r.json();return null;
      }).then(function(j){
        if(j&&typeof j.shutdown_in==='number'){
          remain=j.shutdown_in;showBanner();
          if(!ticking){ticking=true;setInterval(function(){
            if(remain>0){remain--;showBanner();}
          },1000);}
          // First notice of the shutdown: save dirty forms NOW. A later
          // heartbeat may never arrive inside the grace window.
          autosaveDirty();
        }
      }).catch(showLost);
    }catch(e){showLost();}
  }
  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',function(){markDirty();markClean();});}
  else{markDirty();markClean();}
  beat();
  setInterval(beat,15000);
})();
</script>"""



def page(title, body, company="FleetSheet", path="", alerts=None, top_items=None,
         alert_total=None, cats=None):
    body_cls = _body_classes()
    sec = _nav_section(path)
    def cls(name):
        return ' class="on"' if sec == name else ""
    # Quiet desk-side awareness: when yard devices are heartbeating, the
    # header says so on first paint; the heartbeat script then keeps the
    # note current and arms the browser's "Leave site?" confirm for real
    # window closes (disarmed for in-app navigation by the script itself).
    yard_n = yard_status_hook() if yard_status_hook else 0
    if yard_n:
        yard_note = (f'<span class="yardnote" id="fs-yardnote">{yard_n} yard device'
                     f'{"s" if yard_n != 1 else ""} connected</span>')
    else:
        yard_note = ""
    return f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<link rel="icon" href="/favicon.ico">
<title>{html.escape(title)} · {html.escape(company)}</title><style>{CSS}</style>{_text_size_style()}</head>
<body class="{body_cls}"><header><div class="brand"><img src="/company-logo" alt="" onerror="this.remove()">{html.escape(company)}</div>
<nav class="main">
<a href="/"{cls('dash')}>Today</a>
<a href="/ticket/new"{cls('ticketnew')}>Equipment</a>
<a href="/money"{cls('acct')}>Billing</a>
<a href="/assets"{cls('assets')}>Assets</a>
<a href="/compliance"{cls('compliance')}>Compliance</a>
<a href="/reports"{cls('reports')}>Reports</a>
<span class="tabright"><a href="/setup"{cls('setup')}>Setup</a></span>
<nav class="aside"><span id="hdr-lock"></span></nav>
</nav>
{yard_note}</header>{"" if path in ("/assets", "/compliance") else news_strip(alerts, path, top_items, alert_total, cats)}<main>{body}</main>
<footer style="text-align:center;font-size:10px;color:#6b7280;padding:8px 0;border-top:1px solid #eee;margin-top:16px;opacity:.85">FleetSheet · © 2026 FleetSheet</footer>
{('<div id="morebelow" style="display:none">&#9660; more below</div>'
  '<script>(function(){var p=document.getElementById("morebelow");if(!p)return;'
  'function u(){var more=document.documentElement.scrollHeight-window.innerHeight-window.scrollY;'
  'p.style.display=more>120?"":"none";}'
  'window.addEventListener("scroll",u,{passive:true});window.addEventListener("resize",u);u();'
  'p.onclick=function(){window.scrollBy({top:window.innerHeight*0.8,behavior:"smooth"});};})();</script>')
 if path.startswith("/setup") else ""}
<div class="mark">FleetSheet</div>{AUDIT_POPUP_HTML}
{PBOX_JS}
{COMBO_JS}
<script>
/* Money inputs everywhere: a $ prefix on the box, and a lone 0 clears on
   focus so typing 5 reads $ 5.00 instead of 05.00.
   Quantity fields (qty, q0..qn) are NOT money — skip them (2026-10-07). */
(function(){{
  document.querySelectorAll('input[type=number][step="0.01"]').forEach(function(el){{
    if (el.closest('.dollar')) return;
    var nm = (el.name || '').toLowerCase();
    if (/^(qty|q\\d+|quantity)$/.test(nm)) return;
    var w = document.createElement('span'); w.className = 'dollar';
    el.parentNode.insertBefore(w, el); w.appendChild(el);
    el.addEventListener('focus', function(){{
      if (/^0(\\.0{{1,2}})?$/.test(el.value)) el.value = '';
    }});
  }});
}})();
/* Example text clears on focus (Jason 2026-10-08): inputs rendered with
   data-example="..." clear their value on first focus, but only if the value
   still matches the example — real user data is never touched. */
(function(){{
  document.querySelectorAll('input[data-example]').forEach(function(el){{
    el.addEventListener('focus', function(){{
      if (el.value === el.dataset.example) el.value = '';
    }});
  }});
}})();
(function(){{
  if (document.body.classList.contains('notips')) return;
  var TIPS = {{
    "Save Rental":"Saves the rental and stays here — it pops into the list below.",
    "Save customer":"Stores the account. Tax exempt is not on this form — set it on the site.",
    "Save unit":"Stores the iron and rates. Cert flags decide FIT on a ticket.",
    "Save site":"Stores the job. Tax rate and exempt follow this location.",
    "Save work order":"Yard expense if internal. Billable if charged to the customer.",
    "Save setup":"Letterhead, invoice prefix, waiver and env percents.",
    "Save options":"Saves the tip switch. Phone files do not need this button.",
    "Create invoice":"One customer. Tick only ready rentals and completed billable work.",
    "Apply cash":"Drops that invoice balance only. Cannot exceed the balance. No on-account slush.",
    "Issue credit memo":"Opens a CM. Apply some or all to that customer’s open invoices. Remainder waits.",
    "Apply leftover":"Uses unapplied credit on more invoices for the same customer.",
    "Pay from box":"Takes cash out of the petty-cash box. Cannot overdraw.",
    "Put in box":"Opening float, replenish from the bank, or cash you chose to drop in the box.",
    "Save float":"Target amount the box should hold after a replenish.",
    "New customer":"Open a blank account form. ID is assigned.",
    "New unit":"Add a piece of iron. Rates and cert stamps live here.",
    "New site":"Add a job or pad and pick its tax location.",
    "New work order":"Repair, cert, or service call on a unit.",
    "Work ticket":"On-screen print sheet for the crew.",
    "Delivery ticket":"Sign-off sheet. Charges stay on the invoice.",
    "Show stays":"Units that were on rent in the dates you picked.",
    "Phone button file":"HTML file for the phone. Open it and tap Open FleetSheet.",
    "Windows shortcut":".url file for another PC on this Wi-Fi.",
    "Tickets CSV":"Rental fact table: days, rate, tax, total, month.",
    "Invoices CSV":"Invoice headers and balances.",
    "Work orders CSV":"Internal cost and billable service rows.",
    "Units CSV":"Fleet list and rates.",
    "Customers CSV":"Account list.",
    "All tables JSON":"One file for Power Query / Tableau / Python.",
    "All CSV + JSON zip":"Everything in one zip for charts.",
    "Quoted":"Estimate only. Does not block the unit.",
    "Reserved":"Holds the unit for a start date.",
    "Dispatched":"On the truck, not yet on rent.",
    "On Rent":"Clock is running. Off-rent date is required to leave this.",
    "Off Rent":"Clock stopped. Next is Ready to Bill.",
    "Ready to Bill":"Waiting for an invoice.",
    "Invoiced":"On an invoice. Do not edit money here.",
    "Void":"Kills the ticket. Unit is free."
  }};
  document.querySelectorAll('button, a.btn').forEach(function(el){{
    if (el.getAttribute('data-tip')) return;
    var t = (el.value || el.textContent || '').trim();
    if (TIPS[t]) el.setAttribute('data-tip', TIPS[t]);
  }});
  /* Flip tooltips leftward when they'd run past the viewport's right edge.
     Keeps the hidden 220px box from widening the page (phantom scrollbar)
     and keeps the shown tip fully readable. */
  function flipTips(){{
    var vw = document.documentElement.clientWidth;
    document.querySelectorAll('[data-tip]').forEach(function(el){{
      var r = el.getBoundingClientRect();
      el.classList.toggle('tip-left', r.left + 240 > vw && r.left > 240);
    }});
  }}
  flipTips();
  window.addEventListener('resize', flipTips);
  document.addEventListener('mouseover', function(e){{
    var el = e.target.closest('[data-tip]');
    if (!el) return;
    var r = el.getBoundingClientRect();
    el.classList.toggle('tip-left', r.left + 240 > document.documentElement.clientWidth && r.left > 240);
  }});
}})();
(function(){{
  // Touch fallback: hover tooltips (data-tip) are invisible on touchscreens.
  // Trap the FIRST tap only when it genuinely came from a touch finger.
  // 2026-10-04: capability sniffing (maxTouchPoints>0) misfired for mouse
  // users on touch-screen desktops and forced double-click navigation —
  // now we go by the actual pointer type of the tap.
  if (document.body.classList.contains('notips')) return;
  var lastPointer = 'mouse';
  document.addEventListener('pointerdown', function(e){{
    lastPointer = e.pointerType || 'mouse';
  }}, true);
  var openEl = null;
  function close(){{ if (openEl) {{ openEl.classList.remove('tip-open'); openEl = null; }} }}
  document.addEventListener('click', function(e){{
    var el = e.target.closest('[data-tip]');
    if (!el) {{ close(); return; }}
    if (el === openEl) {{ close(); return; }}
    if (lastPointer !== 'touch') return;  // mouse/pen/keyboard: first click acts, hover tip still works
    // Never trap taps on navigation (Jason 2026-10-08): a tap on a link always navigates.
    if (el.tagName === 'A' && el.getAttribute('href')) {{ close(); return; }}
    e.preventDefault();
    close();
    el.classList.add('tip-open');
    openEl = el;
  }}, true);
}})();
(function(){{
  // Stepper buttons: minus sits left of the number, plus right; both always
  // visible (walkthrough 2026-10-04 — the old hover-only number spinner hid
  // the +/- until hovered). Adjusts the adjacent number input in place.
  document.addEventListener('click', function(e){{
    var b = e.target.closest('.stepper button[data-step]');
    if (!b) return;
    var inp = b.parentNode.querySelector('input[type=number]');
    if (!inp) return;
    var v = parseInt(inp.value, 10);
    if (isNaN(v)) v = 0;
    v += parseInt(b.getAttribute('data-step'), 10) || 0;
    var mn = parseInt(inp.min, 10), mx = parseInt(inp.max, 10);
    if (!isNaN(mn)) v = Math.max(mn, v);
    if (!isNaN(mx)) v = Math.min(mx, v);
    inp.value = v;
  }});
}})();
</script>{AUDIT_POPUP_JS}{HEARTBEAT_JS}
</body></html>"""



def tabs(active, items):
    bits = []
    right_bits = []
    for item in items:
        href, lab = item[0], item[1]
        tip = item[2] if len(item) > 2 else ""
        right = len(item) > 3 and item[3] == "right"
        cls = "on" if href == active else ""
        tip_attr = f' data-tip="{html.escape(tip)}"' if tip else ""
        bit = f'<a class="{cls}" href="{href}"{tip_attr}>{lab}</a>'
        (right_bits if right else bits).append(bit)
    out = '<div class="tabs">' + "".join(bits)
    if right_bits:
        out += '<span class="tabright">' + "".join(right_bits) + "</span>"
    return out + "</div>"


def tabs_reports(active="/reports"):
    return tabs(active, [
        ("/reports", "Operations", "Availability, upcoming certs, invoicing status, recap, stays, maintenance."),
        ("/tickets", "Tickets", "Every rental ticket and its status. Open one to change status or print."),
        ("/wos", "Work orders", "Yard work and billable service calls. Internal cost is expense; customer charge is income."),
        ("/export", "Data", "Occasional data out: weekly reports, quick exports, and custom builds — CSV, Excel, PDF, print."),
    ])


def weekly_tabs(active=""):
    """The three weekly push-button reports — AR aging, fleet utilization,
    this week's flow. One row, always one click away."""
    items = [
        ("/reports/weekly/money", "Weekly money", "AR aging — who owes what, and how late."),
        ("/reports/weekly/fleet", "Fleet utilization", "Days on rent vs idle vs down, per unit."),
        ("/reports/weekly/flow", "This week's flow", "Reservations, quotes pending, job ends, shop work."),
    ]
    bits = []
    for href, lab, tip in items:
        cls = "on" if href == active else ""
        bits.append(
            f'<a class="{cls}" href="{href}" data-tip="{html.escape(tip)}">{lab}</a>'
        )
    return '<div class="tabs" style="margin-bottom:12px">' + "".join(bits) + "</div>"


def tabs_boards(active="avail", days=14, period="mtd"):
    """Second-level sub-tabs inside the Reports > Operations tab."""
    qs = f"&days={days}&p={html.escape(period)}"
    items = [
        ("avail", "Availability", "Daily availability, upcoming certs, off-rent window, maintenance status."),
        ("money", "Billing", "Invoicing status, recap, work orders vs income."),
        ("stays", "Stays", "Asset stays over a date range."),
    ]
    bits = []
    for key, lab, tip in items:
        cls = "on" if key == active else ""
        bits.append(
            f'<a class="{cls}" href="/reports?b={key}{qs}" data-tip="{html.escape(tip)}">{lab}</a>'
        )
    return '<div class="tabs" style="margin-bottom:12px">' + "".join(bits) + "</div>"


def tabs_setup(active="/setup", heading=""):
    # Heading renders ABOVE the sub-tabs (Jason 2026-10-06): the page title
    # leads, the section tabs follow. Company comes first in the order.
    h = f"<h1>{heading}</h1>" if heading else ""
    return h + tabs(active, [
        ("/setup", "Company", "Company identity, address, phone numbers, and business profile."),
        ("/customers", "Customers", "Customers, locations, contacts, and commercial terms."),
        ("/sites", "Job Sites", "Physical work locations and their optional tax treatment."),
        ("/setup/vendors", "Vendors", "Outside vendors and services — your go-to list for repairs, inspections, and rentals."),
        ("/setup/security", "Security", "Desk PIN and protected-function access.", "right"),
        ("/setup/billing", "Billing", "Invoice numbering, payment terms, billing email, and billing defaults.", "right"),
        ("/setup/admin", "Administration", "Devices, backups, data health, and system maintenance.", "right"),
    ])


# Setup flow order (Jason 2026-10-08): during first-time setup, saving a step
# advances to the next incomplete step. After setup completes, saves stay put.
SETUP_FLOW = [
    ("/setup", "company"),
    ("/customers", "customer"),
    ("/sites", "site"),
    ("/setup/vendors", "vendor"),
    ("/setup/security", "security"),
    ("/setup/billing", "billing"),
    ("/setup/admin", "admin"),
    ("/setup/devices", "devices"),
]

def _setup_step_done(con, step, progress=None):
    """Is a setup flow step complete? progress is a dict for data-driven steps."""
    if step == "vendor":
        try:
            return con.execute("SELECT 1 FROM vendors LIMIT 1").fetchone() is not None
        except Exception:
            return False
    if step == "security":
        try:
            return bool(engine.pin_is_set(con))
        except Exception:
            return False
    if step in ("billing", "admin", "devices"):
        # Visit steps: done once their form is saved (tracked via options).
        try:
            return engine.get_option(con, "setup_%s_done" % step, "") == "1"
        except Exception:
            return False
    # company/customer/site come from the progress dict.
    if progress is None:
        return False
    return bool(progress.get(step))

def next_setup_step(con, current_path):
    """Next incomplete setup step after current_path, or None if setup done."""
    try:
        c = con.execute("SELECT name FROM company WHERE id=1").fetchone()
        cname = (c["name"] if c else "") or ""
        company_done = bool(cname.strip()) and cname.strip().upper() not in ("YOUR COMPANY LLC", "FLEETSHEET")
        progress = {
            "company": company_done,
            "site": company_done and con.execute("SELECT 1 FROM sites LIMIT 1").fetchone() is not None,
            "customer": company_done and con.execute("SELECT 1 FROM customers LIMIT 1").fetchone() is not None,
        }
    except Exception:
        progress = {}
    idx = -1
    # Exact match first ("/setup/security" must not match "/setup" prefix).
    for i, (path, _step) in enumerate(SETUP_FLOW):
        if current_path == path or current_path.startswith(path + "?"):
            idx = i
            break
    if idx < 0:
        for i, (path, _step) in enumerate(SETUP_FLOW):
            if current_path.startswith(path + "/"):
                idx = i
                break
    for j in range(idx + 1, len(SETUP_FLOW)):
        path, step = SETUP_FLOW[j]
        # Security skip (Jason 2026-10-08): PIN already set → skip the step.
        if step == "security" and _setup_step_done(con, "security"):
            continue
        if not _setup_step_done(con, step, progress):
            return path
    return None

def setup_in_progress(con):
    """True if any setup flow step is incomplete."""
    return next_setup_step(con, "") is not None


def _cstat(status):
    """Compliance status badge."""
    return {
        "overdue": "<b class='fail'>Overdue</b>",
        "due": "<b style='color:#b26a00'>Due</b>",
        "ok": "<span class='pass'>OK</span>",
        "info": "<span class='hint'>—</span>",
    }.get(status, html.escape(status))


def _trigger_opts(selected=""):
    return "".join(
        f'<option value="{k}"{" selected" if k == selected else ""}>{v}</option>'
        for k, v in engine.TRIGGER_LABELS.items()
    )


def tabs_invoice(active="/invoice/new"):
    """Money tabs: exactly four, flat, no groupings — Invoice, Record
    payment, Credit memo, Petty cash. Quotes and change orders are not
    here; they live on their own pages under New Ticket."""
    items = [
        ("/invoice/new", "Invoice", "Bill ready tickets and completed billable work. Optional quote number."),
        ("/pay", "Record payment", "Cash against one existing invoice."),
        ("/credit", "Credit memo", "Negative money event on an invoice."),
        ("/petty", "Petty cash", "Petty-cash register."),
    ]
    bits = []
    for href, lab, tip in items:
        on = (href == active or
              (href == "/invoice/new" and active in ("/invoices", "/money/all")))
        cls = "on" if on else ""
        bits.append(
            f'<a class="{cls}" href="{href}" data-tip="{html.escape(tip)}">{lab}</a>')
    return '<div class="tabs">' + "".join(bits) + "</div>"


def tabs_quotes(active="/quotes"):
    """Quiet home for Quotes and Change orders — off the money tabs."""
    items = [
        ("/quotes", "Quotes", "Stand-alone estimate. Ties to tickets, work orders, and invoices."),
        ("/changes", "Change orders", "Add or subtract against a quote. Paper only."),
        ("/quote/new", "New quote", "Start a fresh estimate."),
    ]
    bits = []
    for href, lab, tip in items:
        cls = "on" if href == active else ""
        bits.append(
            f'<a class="{cls}" href="{href}" data-tip="{html.escape(tip)}">{lab}</a>')
    return '<div class="tabs">' + "".join(bits) + "</div>"


def tabs_money(active="invoice"):
    """Money sub-tabs: exactly four — New Invoice, Record Payment, Credit
    Memo, Petty Cash. Flat, no groupings; quotes and change orders live
    under New Ticket, not here."""
    items = [
        ("invoice", "New Invoice", "Bill ready tickets and completed billable work."),
        ("pay", "Record Payment", "Cash against an invoice that still has a balance."),
        ("credit", "Credit Memo", "Negative money event on an invoice."),
        ("petty", "Petty Cash", "Petty-cash register: cash in, cash out."),
    ]
    bits = []
    for key, lab, tip in items:
        cls = "on" if key == active else ""
        bits.append(
            f'<a class="{cls}" href="/money?tab={key}" data-tip="{html.escape(tip)}">{lab}</a>')
    return '<div class="tabs">' + "".join(bits) + "</div>"




def format_phone(value):
    """Normalize common US phone presentation without changing stored data."""
    raw = str(value or '').strip()
    digits = ''.join(ch for ch in raw if ch.isdigit())
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]
    if len(digits) == 10:
        return f"+1 ({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return raw

def opts(rows, value_key, label_key, selected=""):
    out = ['<option value="">— pick —</option>']
    for r in rows:
        v, lab = r[value_key], r[label_key]
        sel = " selected" if str(v) == str(selected) else ""
        out.append(f'<option value="{html.escape(str(v))}"{sel}>{html.escape(str(lab))} ({html.escape(str(v))})</option>')
    return "\n".join(out)


# --- Desk PIN: gates the money pages -------------------------------------------
# Money routes need a signed fspin cookie, issued by /pin after the desk PIN
# is entered. The PIN itself is set in Setup -> Security and stored in the
# engine as a salted hash. Yard-device (/d) routes are never PIN-gated.
PIN_SESSION_HOURS = 8
PIN_MAX_FAILS = 5
PIN_LOCK_SECONDS = 600
MONEY_PREFIXES = ("/invoice", "/invoices", "/pay", "/credit", "/petty",
                  "/export", "/backup", "/money", "/setup/devices",
                  "/print/invoice", "/print/credit", "/print/petty", "/print/quote",
                  "/print/change", "/print/work", "/print/delivery", "/print/report/aging")
_pin_fails: dict = {}  # ip -> [fails, window_start_epoch]


def _pin_fail_state(ip):
    st = _pin_fails.get(ip)
    now = time.time()
    if not st or now - st[1] > PIN_LOCK_SECONDS:
        return 0, 0
    return st[0], int(PIN_LOCK_SECONDS - (now - st[1]))


def _pin_note_fail(ip):
    now = time.time()
    fails, start = _pin_fails.get(ip, (0, now))
    if now - start > PIN_LOCK_SECONDS:
        fails, start = 0, now
    _pin_fails[ip] = [fails + 1, start]


def _pin_reset(ip):
    _pin_fails.pop(ip, None)


# --- GET routing table -----------------------------------------------------
# Exact-path routes: path -> (title, view(self, con, q) -> body_html)

def _task_from_row(text, link, back):
    """Inline 'make it a task' form for audit rows: user picks the tier."""
    return (
        f"<form method='post' action='/today/task/from' style='display:inline;white-space:nowrap'>"
        f"<input type='hidden' name='text' value='{html.escape(text, quote=True)}'>"
        f"<input type='hidden' name='link' value='{html.escape(link, quote=True)}'>"
        f"<input type='hidden' name='back' value='{html.escape(back, quote=True)}'>"
        f"<select name='tier' title='Which stack' style='width:86px;font-size:11px;padding:2px'>"
        f"<option value='must'>Must</option>"
        f"<option value='can' selected>Can</option>"
        f"<option value='later'>Later</option></select> "
        f"<button class='mini' title='Put this on the Today list'>Task</button></form>"
    )


def task_nudge(con, link):
    """Gold nudge on a record page when open Today tasks point at it.

    Looking never clears anything — only the Done button does, and it
    lands the user right back on this record.
    """
    tasks = engine.tasks_for_link(con, link or "")
    if not tasks:
        return ""
    items = "".join(
        f"<div>▸ <b>[{html.escape(t['tier'])}]</b> {html.escape(t['text'])} "
        f"<form method='post' action='/today/task/done' style='display:inline'>"
        f"<input type='hidden' name='task_id' value='{t['task_id']}'>"
        f"<input type='hidden' name='back' value='{html.escape(link, quote=True)}'>"
        f"<button class='mini'>Done</button></form></div>"
        for t in tasks
    )
    return f"<div class='nudge'><b>On your Today list</b> — handled it? {items}</div>"


def _ago(ts):
    """'YYYY-MM-DD HH:MM:SS' -> 'just now' / '12 min ago' / '3 hrs ago'.

    The Done box is the desk's memory — "what did I just do?" A relative
    time answers that faster than a clock time."""
    import datetime as _dt
    try:
        dt = _dt.datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return ""
    mins = int((_dt.datetime.now() - dt).total_seconds() // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins} min ago"
    hrs = mins // 60
    return f"{hrs} hr ago" if hrs == 1 else f"{hrs} hrs ago"


class CoreViews:
    """Session/auth/dashboard/setup/export views mixed into Handler."""
    def _send(self, html_doc, code=200):
        data = html_doc.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_bytes(self, data: bytes, ctype: str, filename: str | None = None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, loc, cookie=None):
        # B5: the Location header must be ASCII — a raw non-ASCII error
        # message (e.g. "→") kills the HTTP connection. Percent-encode
        # anything outside the URL-safe set; existing +-encoded params
        # pass through untouched.
        loc = quote(loc, safe="/:?&=+%#")
        self.send_response(303)
        self.send_header("Location", loc)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    # B6: where a failed POST action should land. Action URLs like
    # /credit/apply or /ticket/T-1/status have no GET view — bouncing the
    # error back to them shows an "unknown" page. Parents are real pages.
    _ACTION_PARENTS = {
        "/pay": "/pay",
        "/credit": "/credit",
        "/credit/apply": "/credit",
        "/invoice/create": "/invoices",
        "/quote/save": "/quotes",
        "/change/save": "/changes",
        "/petty": "/petty",
        "/petty/float": "/petty",
        "/customer/save": "/customers",
        "/unit/save": "/assets/all",
        "/site/save": "/sites",
        "/wo/save": "/wos",
        "/ticket/new": "/tickets",
        "/export/run": "/export",
        "/export/save": "/export",
        "/export/saved/del": "/export",
        "/export/custom/save": "/export",
        "/export/custom/del": "/export",
        "/setup": "/setup",
        "/setup/crew": "/setup",
        "/setup/crew/del": "/setup",
        "/setup/options": "/setup/devices",
        "/backup": "/backup",
        "/backup/restore": "/backup",
        "/setup/devices/issue": "/setup/devices",
        "/setup/devices/revoke": "/setup/devices",
        "/setup/devices/rotate": "/setup/devices",
        "/pin": "/pin",
        "/pin/forgot": "/pin/forgot",
        "/setup/security/pin": "/setup/security",
        "/today/sticky/add": "/",
        "/today/sticky/edit": "/",
        "/today/sticky/remove": "/",
    }

    def _action_parent(self, path):
        if path in self._ACTION_PARENTS:
            return self._ACTION_PARENTS[path]
        parts = path.strip("/").split("/")
        # /ticket/<id>/<action>, /invoice/<ino>/<action>, /quote/<qn>/<action>
        if len(parts) == 3 and parts[0] in ("ticket", "invoice", "quote"):
            return f"/{parts[0]}/{parts[1]}"
        # /d/ticket/<id>/<action> -> the device ticket page
        if len(parts) == 4 and parts[0] == "d" and parts[1] == "ticket":
            return f"/d/ticket/{parts[2]}"
        return path

    def _form(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode()
        q = parse_qs(raw, keep_blank_values=True)
        return {k: (v[0] if v else "") for k, v in q.items()}

    def _multipart(self, max_bytes=100 * 1024 * 1024):
        """Parse a multipart/form-data body.

        Returns (fields, files). fields maps name -> text value; files maps
        name -> (filename, content_type, bytes). Raises ValueError on junk.
        """
        ctype = self.headers.get("Content-Type") or ""
        m = re.search(r'boundary=([^;]+)', ctype)
        if not m:
            raise ValueError("Missing multipart boundary")
        boundary = m.group(1).strip().strip('"').encode()
        n = int(self.headers.get("Content-Length") or 0)
        if n > max_bytes:
            raise ValueError("Upload too large")
        raw = self.rfile.read(n)
        fields, files = {}, {}
        for part in raw.split(b"--" + boundary):
            if not part or part in (b"--", b"--\r\n"):
                continue
            if b"\r\n\r\n" not in part:
                continue
            head, body = part.split(b"\r\n\r\n", 1)
            if body.endswith(b"\r\n"):
                body = body[:-2]
            htext = head.decode("latin-1")
            nm = re.search(r'name="([^"]*)"', htext)
            if not nm:
                continue
            name = nm.group(1)
            fn = re.search(r'filename="([^"]*)"', htext)
            if fn and fn.group(1):
                ct = re.search(r"Content-Type:\s*([^\r\n]+)", htext, re.I)
                files[name] = (fn.group(1),
                               (ct.group(1).strip() if ct else
                                "application/octet-stream"),
                               body)
            else:
                fields[name] = body.decode("utf-8", "replace")
        return fields, files

    def company(self, con):
        return con.execute("SELECT * FROM company WHERE id=1").fetchone()

    def desk(self, con):
        # Header name (Jason 2026-10-06): DBA if filled, else legal name.
        # The separate "Display name" field is gone.
        c = self.company(con)
        try:
            return c["dba"] or c["name"] or ""
        except Exception:
            return ""

    def _crew_block(self, con):
        crew = [(r[0], r[1] if len(r) > 1 else "") for r in
                con.execute("SELECT name, COALESCE(position,'') FROM crew ORDER BY name COLLATE NOCASE")]
        if crew:
            items = "".join(
                f"<tr><td>{html.escape(n)}</td><td>{html.escape(p)}</td>"
                f"<td style='text-align:right'>"
                f"<form method=post action='/setup/crew/del' style='display:inline;margin:0'>"
                f"<input type=hidden name=crew_name value='{html.escape(n)}'>"
                f"<button type=submit class='secondary'>Remove</button></form></td></tr>"
                for n, p in crew)
            table = f"<table><tr><th>Name</th><th>Position</th><th></th></tr>{items}</table>"
        else:
            table = "<p class='hint' style='margin:4px 0'>No crew yet.</p>"
        return f"""
        <h2 style="font-size:16px;color:var(--frame)">Crew Members</h2>
        {table}
        <form method=post action="/setup/crew" style="margin-top:4px">
          <div class="frow">
            <div><label>First Name</label><input name=crew_first maxlength=30 required></div>
            <div><label>MI <span class="hint">(optional)</span></label><input name=crew_mi maxlength=5 style="max-width:7ch"></div>
            <div><label>Last Name</label><input name=crew_last maxlength=30 required></div>
            <div><label>Suffix <span class="hint">(optional)</span></label><input name=crew_suffix maxlength=10 style="max-width:10ch" placeholder="Jr, Sr, III&hellip;"></div>
            <div><label>Position</label><input name=crew_position maxlength=40 placeholder="Foreman, Mechanic&hellip;"></div>
            <div style="flex:1;display:flex;align-items:flex-end"><button class="secondary" style="width:100%">Add to list</button></div>
          </div>
        </form>
        """

    def clerk_field(self, con, extra=""):
        d = html.escape(self.desk(con))
        opts = "".join(f'<option value="{html.escape(n)}"></option>' for n in engine.list_crew(con))
        return (
            f'<div><label>Name</label>'
            f'<input name=clerk list=crew value="{d}" required maxlength=40 {extra}>'
            f'<datalist id=crew>{opts}</datalist></div>'
        )

    def _photo_field(self, tid, side, current, locked=False):
        """File input plus thumbnail for a ticket condition photo (JPG/PNG/WebP)."""
        thumb = ""
        if engine.safe_photo_name(current):
            url = f"/photo/{html.escape(tid, quote=True)}/{side}"
            thumb = (
                f'<p style="margin:4px 0"><a href="{url}">'
                f'<img src="{url}" alt="condition photo" '
                f'style="max-width:160px;border:1px solid #999"></a></p>'
            )
        elif current:
            thumb = f'<p class="hint">On file: {html.escape(str(current))}</p>'
        ro = "disabled" if locked else ""
        return (
            "<label>Photo (JPG, PNG, or WebP)</label>"
            f'<input type=file name=photo accept="image/*" {ro}>' + thumb
        )

    # --- Yard device authorization (QR) ------------------------------------
    # A device scans a QR code once, gets a cookie, and sees only the /d/*
    # yard UI: check-out / check-in and a small set of status moves. No
    # invoices, payments, credits, reports, or export. Tokens expire, revoke
    # instantly, and rotate with a 24h grace so a device is never stranded.
    DEVICE_COOKIE = "fsdev"
    DEVICE_STATUSES = ("Standby", "Dispatched", "On Rent", "Off Rent")
    DEVICE_LIST_STATUSES = ("Reserved", "Dispatched", "On Rent", "Standby")

    def _cookies(self):
        raw = self.headers.get("Cookie") or ""
        out = {}
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip()] = v.strip()
        return out

    def _device(self, con):
        """The authorized device for this request, or (None, reason)."""
        ok, reason, dev = engine.device_check(con, self._cookies().get(self.DEVICE_COOKIE, ""))
        if ok:
            engine.touch_device(con, dev["token"])
        return (dev if ok else None), reason

    def _device_page(self, title, body, label="Yard"):
        return (
            "<!doctype html><html><head><meta charset=utf-8>"
            "<meta name=viewport content=\"width=device-width,initial-scale=1\">"
            "<link rel=\"icon\" href=\"/favicon.ico\">"
            f"<title>{html.escape(title)} · Yard</title><style>{CSS}</style>{_text_size_style()}</head>"
            f"<body class=\"{_body_classes('yd')}\"><header><span class=\"brand\">FleetSheet</span>"
            f"<span class=\"yardnote\">{html.escape(label)}</span></header>"
            f"<main>{body}</main>{HEARTBEAT_JS_YARD}</body></html>"
        )

    def _device_denied(self, reason):
        return self._device_page(
            "Not authorized",
            f"<div class='stat'><b>Device not authorized.</b><br>{html.escape(reason)}.<br>"
            "Scan the QR code from the desk again, or ask the office to re-issue it.<br><br>"
            "<a href='/'>Back to the desk</a> · <a href='/setup/devices'>Pair a device</a></div>",
        )

    def _device_qr_data_uri(self, url):
        try:
            import segno
        except ImportError:
            raise ValueError("QR needs the 'segno' package: pip install segno")
        return segno.make(url, error="m").png_data_uri(scale=6)

    # --- Desk PIN ----------------------------------------------------------
    PIN_COOKIE = "fspin"

    def _pin_session_ok(self, con):
        """True when no PIN is set, or this browser holds a valid PIN cookie."""
        if not engine.pin_is_set(con):
            return True
        raw = self._cookies().get(self.PIN_COOKIE, "")
        if not raw or "." not in raw:
            return False
        exp, _, sig = raw.partition(".")
        try:
            exp_i = int(exp)
        except ValueError:
            return False
        if exp_i < time.time():
            return False
        want = hmac.new(engine.get_pin_secret(con).encode(), exp.encode(),
                        "sha256").hexdigest()
        return hmac.compare_digest(sig, want)

    def _pin_issue(self, con):
        exp = str(int(time.time()) + PIN_SESSION_HOURS * 3600)
        sig = hmac.new(engine.get_pin_secret(con).encode(), exp.encode(),
                       "sha256").hexdigest()
        return f"{self.PIN_COOKIE}={exp}.{sig}; Path=/; HttpOnly; SameSite=Lax"

    def _money_path(self, path):
        return any(path == p or path.startswith(p + "/") for p in MONEY_PREFIXES)

    def _pin_gate(self, con, path, is_post=False):
        """Redirect to /pin when a money route needs the desk PIN.

        Returns True when the request may continue."""
        # Test harnesses set FLEETSHEET_TEST_MODE=1 to bypass the PIN gate
        # entirely — they manage their own auth state. (2026-10-06)
        if os.environ.get("FLEETSHEET_TEST_MODE") == "1":
            return True
        if not self._money_path(path):
            return True
        if not engine.pin_is_set(con):
            # Money functions are deliberately closed until the owner chooses
            # a desk PIN. This is especially important on LAN-enabled yards.
            self._redirect("/setup/security?next=" + quote_plus(path))
            return False
        if self._pin_session_ok(con):
            return True
        nxt = path
        if is_post:
            # POSTs have no PIN form; send them at the money page itself.
            nxt = self._action_parent(path)
        self._redirect("/pin?next=" + quote_plus(nxt))
        return False

    def view_pin(self, con, q):
        if not engine.pin_is_set(con):
            return ("<div class=stat><b>Billing is locked until you set a Desk PIN.</b><br>"
                    "This protects invoices, payments, credits, petty cash, and exports on this computer or yard network. "
                    "<a class='btn' href='/setup/security'>Set Desk PIN →</a></div>")
        fails, wait = _pin_fail_state(self.client_address[0])
        nxt = q.get("next") or "/invoices"
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = "/invoices"
        lock_note = (f"<div class=err>Too many wrong tries — wait {wait // 60 + 1} min.</div>"
                     if fails >= PIN_MAX_FAILS else "")
        return (
            "<div class=card style='max-width:420px;margin:24px auto'>"
            "<h2 style='margin-top:0'>Desk PIN</h2>"
            "<p class=mute>Billing pages need the desk PIN. It stays unlocked on this "
            f"browser for {PIN_SESSION_HOURS} hours.</p>"
            f"{lock_note}"
            "<form method=post action='/pin'>"
            f"<input type=hidden name=next value='{html.escape(nxt)}'>"
            "<label>Desk PIN</label>"
            "<input type=password name=pin inputmode=numeric autocomplete=off "
            "maxlength=8 required style='font-size:24px;letter-spacing:6px;text-align:center;max-width:16ch'>"
            "<button class=big type=submit style='margin-top:12px'>Unlock money pages</button>"
            "</form>"
            "<p class=mute style='margin-top:16px'><a href='/pin/forgot'>Forgot the PIN?</a> "
            "· <a href='/'>Back to dashboard</a></p></div>"
        )

    def _sq_fields(self, q1sel=0, q2sel=1):
        """Two security-question dropdowns + answer inputs."""
        opts = []
        for i, q in enumerate(engine.PIN_SECURITY_QUESTIONS):
            opts.append(
                f"<option value='{i}'{' selected' if i == q1sel else ''}>"
                f"{html.escape(q)}</option>")
        opts2 = []
        for i, q in enumerate(engine.PIN_SECURITY_QUESTIONS):
            opts2.append(
                f"<option value='{i}'{' selected' if i == q2sel else ''}>"
                f"{html.escape(q)}</option>")
        return (
            "<label>Security question 1</label>"
            f"<select name='sq1'>{''.join(opts)}</select>"
            "<label>Answer 1</label>"
            "<input name='sa1' autocomplete=off required style='max-width:40ch'>"
            "<label>Security question 2</label>"
            f"<select name='sq2'>{''.join(opts2)}</select>"
            "<label>Answer 2</label>"
            "<input name='sa2' autocomplete=off required style='max-width:40ch'>")

    def view_pin_forgot(self, con, q):
        err = q.get("err") or ""
        err_box = f"<div class=err>{html.escape(err)}</div>" if err else ""
        sq_section = ""
        if engine.pin_security_is_set(con):
            q1, q2 = engine.pin_security_questions(con)
            qs = engine.PIN_SECURITY_QUESTIONS
            sq_section = (
                "<h3 style='margin-top:24px'>Or answer your security questions</h3>"
                f"{err_box}"
                "<form method=post action='/pin/forgot/questions'>"
                f"<label>{html.escape(qs[q1])}</label>"
                "<input name='sa1' autocomplete=off required>"
                f"<label>{html.escape(qs[q2])}</label>"
                "<input name='sa2' autocomplete=off required>"
                "<button class=big type=submit style='margin-top:12px'>"
                "Clear the PIN</button></form>")
        return (
            "<div class=card style='max-width:420px;margin:24px auto'>"
            "<h2 style='margin-top:0'>Reset the desk PIN</h2>"
            "<p class=mute>Answer your security questions to clear the PIN, "
            "then set a new one in Setup → Security.</p>"
            f"{err_box if not sq_section else ''}"
            f"{sq_section}"
            "<p class=mute><a href='/pin'>Back</a></p></div>"
        )

    def view_security(self, con, q):
        is_set = engine.pin_is_set(con)
        _pin_style = "font-size:24px;letter-spacing:6px;text-align:center;max-width:16ch"
        # MANUAL-SOURCE (removed from screen 2026-10-08, belongs in manual):
        # - "4–8 digits. Billing pages (invoices, payments, credits, petty cash,
        #   exports) will ask for it on this Wi-Fi. Yard devices are never asked."
        # - "Answer these two questions resets the PIN. Pick ones only you could
        #   answer."
        # - "Used to reset a forgotten PIN. Changing them needs the current PIN."
        if not is_set:
            form = (
                "<h3>Set a desk PIN</h3>"
                "<form method=post action='/setup/security/pin'>"
                "<input type=hidden name=mode value='set'>"
                "<div class=\"row3\">"
                f"<div><label>New PIN</label><input type=password name=pin1 inputmode=numeric maxlength=8 required style='{_pin_style}'></div>"
                f"<div><label>Repeat PIN</label><input type=password name=pin2 inputmode=numeric maxlength=8 required style='{_pin_style}'></div>"
                "<div></div>"
                "</div>"
                "<h3 style='margin-top:20px'>Security questions</h3>"
                f"{self._sq_fields()}"
                "<button class=big type=submit style='margin-top:12px'>Set PIN</button></form>")
        else:
            q1, q2 = engine.pin_security_questions(con)
            form = (
                "<h3>Change the desk PIN</h3>"
                "<form method=post action='/setup/security/pin'>"
                "<input type=hidden name=mode value='change'>"
                "<div class=\"row3\">"
                f"<div><label>Current PIN</label><input type=password name=cur inputmode=numeric maxlength=8 required style='{_pin_style}'></div>"
                f"<div><label>New PIN</label><input type=password name=pin1 inputmode=numeric maxlength=8 required style='{_pin_style}'></div>"
                f"<div><label>Repeat new PIN</label><input type=password name=pin2 inputmode=numeric maxlength=8 required style='{_pin_style}'></div>"
                "</div>"
                "<button class=big type=submit style='margin-top:12px'>Change PIN</button></form>"
                "<h3 style='margin-top:24px'>Security questions</h3>"
                "<form method=post action='/setup/security/questions'>"
                "<div class=\"row3\">"
                f"<div><label>Current PIN</label><input type=password name=cur inputmode=numeric maxlength=8 required style='{_pin_style}'></div>"
                "<div></div><div></div>"
                "</div>"
                f"{self._sq_fields(q1, q2)}"
                "<button class=big type=submit style='margin-top:12px'>Save questions</button></form>")
        return tabs_setup("/setup/security") + f"<div class=card>{form}</div>"

    def view_welcome(self, con, q):
        """First-run onboarding: set the desk PIN right after the EULA.

        The money pages are PIN-gated, so the PIN is collected up front as
        part of setup rather than as a surprise wall mid-workflow. (2026-10-06)
        """
        err = q.get("err") or ""
        err_box = f"<p class=err>{html.escape(err)}</p>" if err else ""
        return (
            "<div class='card' style='max-width:560px;margin:32px auto'>"
            "<h2 style='margin-top:0'>One last thing: set your desk PIN</h2>"
            "<p class=mute>Your money pages — invoices, payments, credits, petty cash — "
            "are protected by a desk PIN. Set it now; you'll enter it once per session. "
            "Yard devices are never asked.</p>"
            f"{err_box}"
            "<form method=post action='/setup/security/pin'>"
            "<input type=hidden name=mode value='set'>"
            "<input type=hidden name=next value='/'>"
            "<label>New PIN</label><input type=password name=pin1 inputmode=numeric "
            "maxlength=8 required style='font-size:24px;letter-spacing:6px;text-align:center;max-width:16ch'>"
            "<label>Repeat PIN</label><input type=password name=pin2 inputmode=numeric "
            "maxlength=8 required style='font-size:24px;letter-spacing:6px;text-align:center;max-width:16ch'>"
            "<h3 style='margin-top:20px'>Security questions</h3>"
            "<p class=mute>Answer these two "
            "questions resets the PIN. Pick ones only you could answer.</p>"
            f"{self._sq_fields()}"
            "<button class=big type=submit style='margin-top:12px'>Set PIN and start</button></form>"
            "</div>")

    def view_setup_complete(self, con):
        # Setup Complete acknowledgement (Jason 2026-10-08): shown once after
        # the Devices Done button during first-time setup, then to Today.
        return """<div class=card style="max-width:560px;margin:40px auto;text-align:center">
          <h1>Setup Complete</h1>
          <p>FleetSheet is ready. Your company, customers, sites, vendors,
          security, billing, backups, and devices are set up.</p>
          <p><a class="btn big" href="/">Start Using FleetSheet →</a></p>
        </div>"""

    def view_devices(self, con, q):
        devs = engine.list_devices(con)
        saved_base = engine.get_option(con, "device_base_url", "")
        lan = lan_urls()
        guess = saved_base or (lan[0] if lan else "http://127.0.0.1:8765")
        rows = []
        for d in devs:
            tok = d["token"]
            state = d["state"]
            exp = d["expires_at"] or "—"
            if d["state"] == "expiring":
                exp = f"{exp} ({d['days_left']}d left)"
            seen = d["last_seen_at"] or "never"
            show_f = (f"<form method=get action='/setup/devices/show' style='display:inline'>"
                      f"<input type=hidden name=token value='{html.escape(tok)}'>"
                      f"<button class='secondary' style='padding:6px 10px'>QR</button></form>")
            rot_f = (f"<form method=post action='/setup/devices/rotate' style='display:inline'>"
                     f"<input type=hidden name=token value='{html.escape(tok)}'>"
                     f"<button class='secondary' style='padding:6px 10px'>Rotate</button></form>")
            rev_f = (f"<form method=post action='/setup/devices/revoke' style='display:inline' "
                     f"onsubmit=\"return confirm('Revoke this device now?')\">"
                     f"<input type=hidden name=token value='{html.escape(tok)}'>"
                     f"<button class='secondary' style='padding:6px 10px'>Revoke</button></form>")
            acts = show_f + " " + (rot_f + " " + rev_f if state in ("active", "expiring") else "")
            rows.append(
                f"<tr><td>{html.escape(d['label'])}</td><td>{state}</td>"
                f"<td>{html.escape(exp)}</td>"
                f"<td>{html.escape(seen)}</td><td style='white-space:normal'>{acts}</td></tr>"
            )
        c = self.company(con)
        try:
            tips_on = int(c["tooltips"]) != 0
        except Exception:
            tips_on = True
        text_size = engine.get_option(con, "ui_text_size", "standard")
        if text_size not in ("standard", "large", "xlarge"):
            text_size = "standard"
        def _tsel(v):
            return " selected" if text_size == v else ""
        bind_mode = os.environ.get("FLEETSHEET_BIND", "localhost").strip().lower()
        if bind_mode in ("lan", "0.0.0.0", "all"):
            net_note = ("<div class='err'><b>LAN access is enabled.</b> FleetSheet is listening "
                        "for other devices on the yard network. Use this only on a trusted "
                        "private network and restrict the Windows firewall to the intended network.</div>")
        else:
            net_note = ("<div class='ok'><b>Local-only mode.</b> Phones/tablets cannot connect until "
                        "FleetSheet is restarted with <code>FLEETSHEET_BIND=lan</code> or an explicit LAN interface.</div>")
        return tabs_setup("/setup/devices") + f"""
        {net_note}
        <div class="row">
          <div>
            <h2 style="font-size:16px;color:var(--frame)">Authorized Devices</h2>
            <form method=post action="/setup/devices/issue">
              <label>Device Name</label>
              <input name=label maxlength=60 required placeholder="Yard tablet 1" style="max-width:220px">
              <div class="row">
                <div><label>Expires (days)</label><input name=days value="90" inputmode=numeric style="max-width:80px"></div>
                <div><label>Server address in QR</label>
                  <input name=base_url value="{html.escape(guess)}" style="max-width:220px"></div>
              </div>
              {self.clerk_field(con)}
              <p><button>Issue + show QR</button></p>
            </form>
            <table><tr><th>Device</th><th>State</th><th>Expires</th><th>Last seen</th><th>Actions</th></tr>
            {"".join(rows) or "<tr><td colspan=5>No devices yet.</td></tr>"}</table>
          </div>
          <div>
            <h2 style="font-size:16px;color:var(--frame)">Add a Yard Device</h2>
            {phone_card()}
            {self._devices_done_button(con, q)}
            <h2 style="font-size:16px;color:var(--frame)">Display Preferences</h2>
            <form method=post action="/setup/options">
              <label><input type=checkbox name=tooltips value=1 {"checked" if tips_on else ""}> Show delayed tips</label>
              <label for="text_size">Text size</label>
              <select name=text_size id=text_size data-tip="Scales every FleetSheet page up or down — like browser zoom, but built in, so it stays put.">
                <option value="standard"{_tsel("standard")}>Standard</option>
                <option value="large"{_tsel("large")}>Large</option>
                <option value="xlarge"{_tsel("xlarge")}>Extra large</option>
              </select>
              <p><button class="secondary">Save</button></p>
            </form>
          </div>
        </div>
        """

    def _devices_done_button(self, con, q):
        # Done button only during first-time setup (Jason 2026-10-08): marks
        # setup complete and leads to the Setup Complete acknowledgement.
        # MANUAL-SOURCE: "Create a temporary authorization for a phone, tablet,
        #   or scanner. Desk PIN is under Security."
        try:
            if not setup_in_progress(con):
                return ""
        except Exception:
            return ""
        return """
        <form method=post action="/setup/devices/done" style="margin-top:12px">
          <button class="big" type=submit>Done</button>
        </form>"""

    def view_device_show(self, con, token, base):
        dev = engine.get_device(con, token or "")
        if not dev:
            return tabs_setup("/setup/devices") + "<p>Unknown device.</p>"
        url = (base or "").rstrip("/") + "/d/" + token
        try:
            qr_uri = self._device_qr_data_uri(url)
            img = f"<img src=\"{qr_uri}\" alt=\"device QR\" width=240 height=240>"
            dl = (f"<p><a class=\"btn\" href=\"{qr_uri}\" "
                  f"download=\"fleetsheet-device.png\">Download QR image</a></p>")
        except ValueError as e:
            img = f"<p class='err'>{html.escape(str(e))}</p>"
            dl = ""
        return tabs_setup("/setup/devices") + f"""
        <h1>Device QR — {html.escape(dev['label'])}</h1>
        <div class="qrbox" style="max-width:340px">
          {img}
        </div>
        {dl}
        <p>Link (type it on a scanner with no camera):</p>
        <p class="code">{html.escape(url)}</p>
        <p class="hint">Expires {html.escape(dev['expires_at'] or '—')}.
        Rotating issues a new code; the old one works 24 more hours. Revoking kills it at once.</p>
        <p><a class="btn" href="/setup/devices">Back to devices</a></p>
        """

    def view_device_home(self, con, dev):
        ph = ",".join("?" * len(self.DEVICE_LIST_STATUSES))
        rows = con.execute(
            f"SELECT ticket_id, customer_id, asset_id, status, on_rent FROM tickets "
            f"WHERE status IN ({ph}) ORDER BY status, on_rent", self.DEVICE_LIST_STATUSES
        ).fetchall()
        items = "".join(
            f"<a class=trow href='/d/ticket/{html.escape(r['ticket_id'])}'>"
            f"<b>{html.escape(r['ticket_id'])}</b> · {html.escape(r['status'])}"
            f"<small>{html.escape(r['customer_id'])} · {html.escape(r['asset_id'])} · on {html.escape(r['on_rent'] or '—')}</small></a>"
            for r in rows
        ) or "<div class='stat'>No yard tickets right now.</div>"
        exp = f"Code good through {dev['expires_at']}." if dev.get("expires_at") else ""
        return self._device_page(
            "Yard", f"<h2 style='margin:4px 0 8px'>Yard Tickets</h2>{items}"
                    f"<p class='hint' style='color:#5C6B7A'>{html.escape(exp)}</p>"
                    f"<p><a href='/d/forget' style='color:#5C6B7A;font-size:14px'>"
                    f"Not this device? Sign out of yard mode</a></p>",
            label=f"Yard · {dev['label']}",
        )

    def view_device_ticket(self, con, dev, tid, flash=""):
        t = con.execute("SELECT * FROM tickets WHERE ticket_id=?", (tid,)).fetchone()
        if not t:
            return self._device_page("Yard", "<div class='stat'>Unknown ticket.</div>",
                                     label=f"Yard · {dev['label']}")
        conds = list(engine.COND_RANK.keys())
        def sel(cur):
            return "".join(f"<option{' selected' if cur == c else ''}>{html.escape(c)}</option>" for c in conds)
        crew_opts = "".join(f'<option value="{html.escape(n)}"></option>' for n in engine.list_crew(con))
        name_field = (f"<label>Your Name</label><input name=clerk list=dcrew required maxlength=40>"
                      f"<datalist id=dcrew>{crew_opts}</datalist>")
        nxt = [s for s in engine.ALLOWED_NEXT.get(t["status"], ()) if s in self.DEVICE_STATUSES]
        status_btns = "".join(
            f"<form method=post action='/d/ticket/{html.escape(tid)}/status' style='margin:0'>"
            f"<input type=hidden name=status value='{html.escape(s)}'>"
            f"<label>Your Name</label><input name=clerk list=dcrew required maxlength=40>"
            f"<datalist id=dcrew>{crew_opts}</datalist>"
            + (f"<label>Off-rent date (only for Off Rent)</label><input type=date name=off_rent value=\"{date.today().isoformat()}\">" if s == "Off Rent" else "")
            + f"<button class='big' type=submit>Mark {html.escape(s)}</button></form>"
            for s in nxt
        ) or "<div class='stat'>No yard moves from here — the desk handles the rest.</div>"
        cust = con.execute("SELECT account_name FROM customers WHERE customer_id=?", (t["customer_id"],)).fetchone()
        cust_name = cust["account_name"] if cust else t["customer_id"]
        return self._device_page(
            tid,
            f"""{flash}
            <div class="stat"><b>{html.escape(tid)}</b> · {html.escape(t["status"])}<br>
            <small>{html.escape(cust_name)} · {html.escape(t["asset_id"])} ·
            out: {html.escape(t["out_condition"] or "—")} · in: {html.escape(t["in_condition"] or "—")}</small></div>
            <form method=post action="/d/ticket/{html.escape(tid)}/condition" data-autosave enctype="multipart/form-data">
              <input type=hidden name=side value=out>
              <h3 style="margin:0 0 4px">Check out</h3>
              {name_field}
              <label>Out Condition</label><select name=condition required>{sel(t["out_condition"])}</select>
              <label>Meter / hours / fuel</label><input name=meter value="{html.escape(t["out_meter"] or "")}">
              {self._photo_field(tid, "out", t["out_photo"])}
              <label>Note</label><input name=note value="{html.escape(t["out_note"] or "")}">
              <button class="big" type=submit>Save check-out</button>
            </form>
            <form method=post action="/d/ticket/{html.escape(tid)}/condition" data-autosave enctype="multipart/form-data">
              <input type=hidden name=side value=in>
              <h3 style="margin:0 0 4px">Check in</h3>
              {name_field}
              <label>In Condition</label><select name=condition required>{sel(t["in_condition"])}</select>
              <label>Meter / hours / fuel</label><input name=meter value="{html.escape(t["in_meter"] or "")}">
              {self._photo_field(tid, "in", t["in_photo"])}
              <label>Note</label><input name=note value="{html.escape(t["in_note"] or "")}">
              <button class="big" type=submit>Save check-in</button>
            </form>
            <h3>Status</h3>
            {status_btns}
            <p><a class="bigbtn" style="display:block;text-align:center" href="/d">← All yard tickets</a></p>
            """,
            label=f"Yard · {dev['label']}",
        )

    def _pin_nag(self, con):
        """Desk-PIN reminder: stays up top until the PIN is set, or dismissed
        for this browser session (the nag returns next visit — not forgotten)."""
        if engine.pin_is_set(con):
            return ""
        if self._cookies().get("pin_nag") == "off":
            return ""
        return ("<div class=err><b>Billing pages are open on this Wi-Fi.</b> "
                "Set a desk PIN in <a href='/setup/security'>Setup → Security</a>. "
                "<form method='post' action='/pin/nagoff' style='display:inline'>"
                "<button type='submit' style='margin-left:10px'>Sleep</button>"
                "</form></div>")

    def _done_box(self, con, back="/"):
        """Done today: what got done. Explicit completions only — tasks clicked
        off the to-do list plus hand-logged 'Other done' entries. Nothing is
        pulled in from anywhere else; payments and everything else live behind
        the View audit button. One coordinated box: every section page renders
        this same log. `back` keeps Undo / Remove / Other-done on this page."""
        back_esc = html.escape(back or "/", quote=True)
        rows = ""
        for d in engine.done_today(con):
            by = f" — {html.escape(d['done_by'])}" if d["done_by"] else ""
            text = html.escape(d["text"])
            if d["link"]:
                text = f"<a href='{html.escape(d['link'], quote=True)}'>{text}</a>"
            if d["kind"] == "manual":
                undo = (
                    f" <form method='post' action='/today/done/other/remove' style='display:inline'>"
                    f"<input type='hidden' name='entry_id' value='{d['entry_id']}'>"
                    f"<input type='hidden' name='back' value='{back_esc}'>"
                    f"<button class='mini'>Remove</button></form>")
            else:
                undo = (
                    f" <form method='post' action='/today/task/undone' style='display:inline'>"
                    f"<input type='hidden' name='task_id' value='{d['task_id']}'>"
                    f"<input type='hidden' name='back' value='{back_esc}'>"
                    f"<button class='mini'>Undo</button></form>")
            rows += (
                f"<div class='dtodo'><span class='tick'>✓</span>{text}"
                f"<span class='dmeta'>{_ago(d['done_at'])}{by}</span>{undo}</div>")
        if not rows:
            rows = "<p class='mute' style='font-size:13px'>Nothing done yet today.</p>"
        return (f"<div class='donebox' id='done-today'><h3>Done today</h3>{rows}"
                f"<p class='daudit'>"
                f"<button type='button' class='vbtn' data-audit='/today/done/other?back={quote(back or '/', safe='')}' "
                f"data-title='Other done'>Other done</button> "
                f"<button type='button' class='vbtn' "
                f"data-audit='/done?period=week' data-title='Done — this week'>View</button></p></div>")

    def view_done_other(self, con, q=None):
        """'Other done' pop-up: log an ad-hoc completion by hand. Opens in the
        audit pop-up; the form targets _top so saving lands back on the page
        that opened it."""
        desk = html.escape(self.desk(con), quote=True)
        back = html.escape(((q or {}).get("back") or "/"), quote=True)
        return f"""
        <h1>Other Done</h1>
        <p class='hint'>Something got done that wasn't on the list? Put it on the Done list.</p>
        <form method="post" action="/today/done/other" target="_top" class="tform">
        <input type="hidden" name="clerk" value="{desk}">
        <input type="hidden" name="back" value="{back}">
        <p><input name="text" placeholder="What got done?" size="40" maxlength="200" required></p>
        <p><input name="link" placeholder="Link to record (optional, e.g. /invoice/INV-1024)" size="40" maxlength="200"></p>
        <p><button>Log it</button></p>
        </form>
        """

    def view_done(self, con, q=None):
        """Done-log audit: explicit completions — today, this week, this year.
        Clicked-off tasks plus hand-logged entries, then payments collected.
        Dump to CSV, or print."""
        period = (q or {}).get("period") or "week"
        if period not in ("today", "week", "year"):
            period = "week"
        start, end, label = engine.done_period(con, period)
        tasks = engine.done_tasks(con, start, end)
        pays = engine.done_payments(con, start, end)
        tabs = " · ".join(
            f"<b>{t}</b>" if p == period else f"<a href='/done?period={p}'>{t}</a>"
            for p, t in (("today", "Today"), ("week", "This week"), ("year", "This year")))
        trows = "".join(
            f"<tr><td>{html.escape((t['done_at'] or '')[:16])}</td>"
            f"<td>{html.escape(t['text'])}</td>"
            f"<td>{html.escape(t['tier'])}</td>"
            f"<td>{html.escape(t['done_by'] or '—')}</td></tr>"
            for t in tasks) or "<tr><td colspan=4 class='mute'>Nothing logged.</td></tr>"
        prows = "".join(
            f"<tr><td>{html.escape((p['pay_date'] or '')[:16])}</td>"
            f"<td><a href='/invoice/{html.escape(p['invoice_no'], quote=True)}'>"
            f"{html.escape(p['invoice_no'])}</a></td>"
            f"<td>{html.escape(p['account_name'])}</td>"
            f"<td style='text-align:right'>${p['amount']:,.2f}</td>"
            f"<td>{html.escape(p['method'])}</td>"
            f"<td>{html.escape(p['clerk'] or '—')}</td></tr>"
            for p in pays) or "<tr><td colspan=6 class='mute'>No payments collected.</td></tr>"
        ptotal = sum(p["amount"] for p in pays)
        return f"""
        <h1>Done log · {label}</h1>
        <p class='hint'>{tabs}</p>
        <p><a class='btn secondary' href='/done/dump?period={period}'>Dump CSV</a>
           <a class='btn secondary' href='/print/done?period={period}'>Print</a></p>
        <h2>Completed ({len(tasks)})</h2>
        <table><tr><th>When</th><th>Task</th><th>Tier</th><th>By</th></tr>{trows}</table>
        <h2>Payments collected ({len(pays)}) — ${ptotal:,.2f}</h2>
        <table><tr><th>When</th><th>Invoice</th><th>Customer</th>
        <th style='text-align:right'>Amount</th><th>Method</th><th>By</th></tr>{prows}</table>
        """

    def _backup_bar(self, con, d):
        b = d.get("backup") or engine.backup_status(con)
        stale = b.get("stale")
        last = b.get("last") or "never"
        folder = html.escape(b.get("folder") or "")
        sched = (b.get("schedule") or "weekly")
        every_days = b.get("every_days") or 7
        sched_phrase = {
            "nightly": "Backup every night.",
            "weekly": "Backup every week.",
            "monthly": "Backup every month.",
            "custom": f"Backup every {every_days} day{'s' if every_days != 1 else ''}.",
            "never": "Automatic backup off.",
        }.get(sched, "Backup every week.")
        cls = "err" if stale else "ok"
        if sched == "never":
            msg = f"{sched_phrase} Last backup {html.escape(last)}."
        elif stale:
            msg = (f"{sched_phrase} Backup overdue "
                   f"(last {html.escape(last)}).")
        else:
            msg = f"{sched_phrase} Last backup {html.escape(last)}."
        desk = html.escape(self.desk(con))
        opts = "".join(f'<option value="{html.escape(n)}"></option>' for n in engine.list_crew(con))
        return f"""
        <form method=post action="/backup" class="{cls} backup-bar" data-tip="Copies the book to a new dated file. Does not log into a cloud account.">
          <span class="backup-msg">{msg} Folder: {folder}</span>
          <input name=clerk list=crew value="{desk}" required maxlength=40 aria-label="Your name" placeholder="Name">
          <datalist id=crew>{opts}</datalist>
          <button class="secondary">Backup now</button>
          <a class="btn secondary" href="/backup" style="text-decoration:none">Manage</a>
        </form>
        """

    def view_health(self, con):
        # System Health page (master plan Step 1): self-diagnosing. Green/yellow/red
        # checks in plain language, one primary action per problem, and a single
        # "Copy diagnostics" button. Uses engine.health_snapshot().
        import os
        db_path = os.environ.get("FLEETSHEET_DB", "fleetsheet.db")
        backup_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")
        try:
            snap = engine.health_snapshot(db_path, backup_dir)
        except Exception as e:
            snap = {"_error": str(e)}
        if "_error" in snap:
            body = f"<p>Could not run diagnostics: {html.escape(snap['_error'])}</p>"
        else:
            rows = []
            def row(label, ok, detail, action=""):
                color = "var(--ok)" if ok else "var(--bad)"
                dot = "●"
                rows.append(
                    f"<tr><td style='color:{color};font-size:16px'>{dot}</td>"
                    f"<td><b>{html.escape(label)}</b><br><span style='color:var(--mute);font-size:12px'>{html.escape(detail)}</span></td>"
                    f"<td>{action}</td></tr>")
            # 1. Integrity
            ok = bool(snap.get("integrity_ok"))
            row("Data file integrity", ok,
                "Your business records passed their health check." if ok else "A problem was found in the data file — restore from a backup below.",
                "" if ok else "<a class='btn secondary' href='/backup'>Go to backups</a>")
            # 2. Foreign keys
            ok = bool(snap.get("foreign_keys_ok"))
            row("Record links", ok,
                "All linked records are consistent." if ok else "Some linked records don't match — restore from a backup.")
            # 3. Disk space
            free = snap.get("disk_free_mb") or 0
            ok = free > 1000
            warn = 100 < free <= 1000
            row("Disk space", ok or warn,
                f"{free:.0f} MB free on the data drive." + ("" if ok else " Low — free up space so the app can keep saving."))
            # 4. Backup age
            age = snap.get("backup_age_hours")
            if age is None:
                row("Backups", False, "No backup found yet.", "<a class='btn secondary' href='/backup'>Back up now</a>")
            else:
                ok = age < 24
                row("Backups", ok,
                    f"Last verified backup {age:.1f} hours ago." if ok else f"Last backup was {age:.1f} hours ago — overdue.",
                    "" if ok else "<a class='btn secondary' href='/backup'>Back up now</a>")
            # 5. Writability
            ok = bool(snap.get("data_dir_writable"))
            row("Data folder", ok,
                "The app can save to its data folder." if ok else "The data folder isn't writable — the app can't save. Check folder permissions.")
            # 6. Sizes
            db_mb = snap.get("db_size_mb") or 0
            wal_mb = snap.get("wal_size_mb") or 0
            row("Data size", True, f"Business file {db_mb:.1f} MB" + (f", {wal_mb:.1f} MB waiting to be filed away." if wal_mb > 1 else "."))
            diag_text = "\n".join(f"{k}: {v}" for k, v in sorted(snap.items()) if k != "last_errors")
            body = f"""
            <div class=card><h2>System Health</h2>
            <table class="capped_table"><tbody>{''.join(rows)}</tbody></table>
            <p style='margin-top:12px'><button class='btn secondary' onclick="navigator.clipboard.writeText(document.getElementById('diagtext').textContent).then(()=>this.textContent='Copied ✓')">Copy diagnostics</button></p>
            <pre id=diagtext style='display:none'>{html.escape(diag_text)}</pre></div>"""
        return tabs_setup("/health") + body

    def view_backups(self, con):
        # MANUAL-SOURCE (removed from screen 2026-10-08, belongs in manual):
        # - "Each backup is one complete archive: the book plus every ticket
        #   photo and every data-book document, with integrity hashes. Only the
        #   newest N dated copies are kept; older ones are pruned automatically.
        #   Downloads and restores need the desk PIN."
        # - "When FleetSheet starts, it makes a backup automatically if the last
        #   one is older than the schedule below."
        # - "Replaces the live book and the ticket photos with the uploaded copy.
        #   A safety snapshot of the current book is taken first, so a bad restore
        #   can itself be undone. The file is fully checked before anything is
        #   touched: it must be a healthy FleetSheet backup archive (.zip)."
        b = engine.backup_status(con)
        last = html.escape(b.get("last") or "never")
        folder = html.escape(b.get("folder") or "")
        sched, every_days = engine.get_backup_schedule(con)
        stale = "backup overdue" if b.get("stale") else "up to date"
        rows = engine.list_backups(con)
        if rows:
            trs = "".join(
                f"<tr><td>{html.escape(r['name'])}</td>"
                f"<td>{'Archive' if r['kind'] == 'archive' else 'Legacy (book only)'}</td>"
                f"<td>{r['mtime'].strftime('%Y-%m-%d %H:%M')}</td>"
                f"<td>{r['size'] / 1024:.0f} KB</td>"
                f"<td>{r['photos'] if r['photos'] is not None else '—'}</td>"
                f"<td>{r['docs'] if r.get('docs') is not None else '—'}</td>"
                f"<td><a class='btn secondary' style='padding:4px 10px' "
                f"href='/backup/download?f={quote_plus(r['name'])}'>Download</a></td></tr>"
                for r in rows)
            table = (f"<table><tr><th>File</th><th>Kind</th><th>Made</th><th>Size</th>"
                     f"<th>Photos</th><th>Docs</th><th></th></tr>"
                     f"{trs}</table>")
        else:
            table = "<p class=hint>No backups in this folder yet.</p>"
        desk = html.escape(self.desk(con))
        opts = "".join(f'<option value="{html.escape(n)}"></option>'
                       for n in engine.list_crew(con))
        def _radio(val, label):
            chk = " checked" if sched == val else ""
            return (f'<label><input type=radio name=schedule value="{val}"{chk}> '
                    f'{label}</label><br>')
        sched_radios = (
            _radio("nightly", "Every night") +
            _radio("weekly", "Every weekend") +
            _radio("monthly", "Monthly") +
            _radio("custom",
                   f'Custom — every <input type=number name=every_days '
                   f'min=1 max=365 value="{every_days}" '
                   f'style="width:4em" aria-label="Days between backups"> days') +
            _radio("never", "Never (back up manually only)")
        )
        return f"""
        <h1>Book Backups</h1>
        <h2>Backup Folder</h2>
        <form method=post action="/setup/admin">
          <div class="frow">
            <div style="flex:1"><input name=backup_dir value="{folder}" placeholder="Leave blank for the default folder" aria-label="Backup folder"></div>
            <div style="align-self:end"><button class="secondary">Save backup settings</button></div>
          </div>
        </form>
        <p class=hint>Last backup: <b>{last}</b> ({stale}). Folder: {folder}.</p>
        <form method=post action="/backup" class="backup-bar">
          <span class="backup-msg">Copy the book, photos, and documents to a new dated archive now.</span>
          <input name=clerk list=crew value="{desk}" required maxlength=40 aria-label="Your name" placeholder="Name">
          <datalist id=crew>{opts}</datalist>
          <button class="secondary">Backup now</button>
        </form>
        <h2>Automatic Backup Schedule</h2>
        <form method=post action="/backup/schedule" class="schedule-form">
          {sched_radios}
          <button class="secondary">Save schedule</button>
        </form>
        <h2>Saved Copies</h2>
        {table}
        <h2>Restore from a File</h2>
        <form method=post action="/backup/restore" enctype="multipart/form-data">
          <label>Backup file (.zip, or a legacy .db)</label>
          <input type=file name=backup_file accept=".zip,.db" required>
          <label>Your Name</label>
          <input name=clerk list=crew value="{desk}" required maxlength=40>
          <datalist id=crew>{opts}</datalist>
          <label><input type=checkbox name=confirm value="yes" required>
          I understand this replaces the live book, photos, and documents</label>
          <button class="danger">Restore this file</button>
        </form>
        """

    def _sticky_notes(self, con, q):
        """Sticky notes with priority, color, snooze, hide-until, pin, sleep.
        Done sends the note to the done list. Still never taps, never blocks."""
        try:
            edit_id = int((q or {}).get("sticky_edit") or 0)
        except (TypeError, ValueError):
            edit_id = 0
        colors = {"yellow": "#fff3b0", "pink": "#ffd6e0", "green": "#d3f2d3", "blue": "#d6e8ff"}
        rows = ""
        for s in engine.list_stickies(con):
            sid = s["sticky_id"]
            bg = colors.get(s["color"], colors["yellow"])
            pri = s["priority"]
            pri_sel = "".join(
                f"<option value='{p}'{' selected' if p == pri else ''}>"
                f"{('Low', 'Med', 'High')[p]}</option>" for p in (2, 1, 0))
            col_sel = "".join(
                f"<option value='{c}'{' selected' if c == s['color'] else ''}>{c.title()}</option>"
                for c in colors)
            if sid == edit_id:
                body = (f"<form method='post' action='/today/sticky/edit' class='tform'>"
                    f"<input type='hidden' name='sticky_id' value='{sid}'>"
                    f"<input name='text' value='{html.escape(s['text'], quote=True)}' "
                    f"size='40' maxlength='500'>"
                    f"<button>Save</button> <a class='tiny' href='/'>cancel</a></form>")
            else:
                body = html.escape(s['text'])
            rows += (
                f"<div class='sticky' style='background:{bg}'>"
                f"<div>{body}</div>"
                f"<div class='sticky-ctl'>"
                f"<form method='post' action='/today/sticky/update' class='tform'>"
                f"<input type='hidden' name='sticky_id' value='{sid}'>"
                f"<select name='priority' title='Priority'>{pri_sel}</select>"
                f"<select name='color' title='Color'>{col_sel}</select>"
                f"<button title='Apply priority/color'>Set</button></form> "
                f"<form method='post' action='/today/sticky/update' class='tform'>"
                f"<input type='hidden' name='sticky_id' value='{sid}'>"
                f"<input type='number' name='snooze_hours' value='3' min='1' max='72' "
                f"title='Snooze hours' style='width:2.2em'>"
                f"<button title='Snooze this note'>Snooze</button></form> "
                f"<form method='post' action='/today/sticky/update' class='tform'>"
                f"<input type='hidden' name='sticky_id' value='{sid}'>"
                f"<input type='datetime-local' name='hide_until' title='Hide until'>"
                f"<button title='Hide until date/time'>Hide</button></form> "
                f"<form method='post' action='/today/sticky/update' class='tform'>"
                f"<input type='hidden' name='sticky_id' value='{sid}'>"
                f"<input type='hidden' name='pinned' value='{'0' if s['pinned'] else '1'}'>"
                f"<button title='Pin to top'>{'Unpin' if s['pinned'] else 'Pin'}</button></form> "
                f"<form method='post' action='/today/sticky/update' class='tform'>"
                f"<input type='hidden' name='sticky_id' value='{sid}'>"
                f"<input type='hidden' name='dismissed' value='1'>"
                f"<button title='Sleep'>Sleep</button></form> "
                f"<form method='post' action='/today/sticky/done' class='tform'>"
                f"<input type='hidden' name='sticky_id' value='{sid}'>"
                f"<button title='Mark done — goes to the done list'>Done</button></form> "
                f"<a class='tiny' href='/?sticky_edit={sid}'>edit</a>"
                f"</div></div>")
        return f"""
        <h3>Sticky notes</h3>
        {rows}
        <form method="post" action="/today/sticky/add" class="tform">
        <input name="text" placeholder="Stick a reminder on the desk&hellip;" size="40" maxlength="500">
        <button>Add</button></form>
        """

    def _setup_progress(self, con):
        """Return first-install/setup progress without exposing implementation details.
        Demo-seeded rows don't count: if the company isn't set up, the user
        hasn't started, so sites/equipment/customers/rentals are 0. (Jason 2026-10-07)"""
        c = self.company(con)
        company_done = bool((c["name"] or "").strip()) and (c["name"] or "").strip().upper() not in ("YOUR COMPANY LLC", "FLEETSHEET")
        counts = {
            "company": company_done,
            # Demo data doesn't count — only real setup after company is done.
            "site": company_done and con.execute("SELECT 1 FROM sites LIMIT 1").fetchone() is not None,
            "equipment": company_done and con.execute("SELECT 1 FROM assets LIMIT 1").fetchone() is not None,
            "customer": company_done and con.execute("SELECT 1 FROM customers LIMIT 1").fetchone() is not None,
            # The desk PIN is collected during first-run onboarding (after the
            # EULA), so it no longer belongs on the dashboard checklist.
            # The capstone step is the aha moment: the first rental ticket.
            # (2026-10-06)
            "rental": company_done and con.execute("SELECT 1 FROM tickets LIMIT 1").fetchone() is not None,
        }
        return counts

    def _empty_action(self, title, detail, href, label):
        return (f"<div class='empty-action'><strong>{html.escape(title)}</strong>"
                f"<p>{html.escape(detail)}</p><a class='btn' href='{html.escape(href, quote=True)}'>{html.escape(label)} →</a></div>")

    def _onboarding_card(self, con):
        p = self._setup_progress(con)
        if all(p.values()):
            return ""
        steps = [
            ("company", "Set up your company", "/setup"),
            ("site", "Add your first site", "/site/new"),
            ("equipment", "Add your first equipment", "/unit/new"),
            ("customer", "Add a customer", "/customer/new"),
            ("rental", "Create your first rental", "/ticket/new"),
        ]
        rows = []
        for key, label, href in steps:
            if p[key]:
                rows.append(f"<div class='setupstep done'><span>✓</span><span>{html.escape(label)}</span></div>")
            else:
                rows.append(f"<div class='setupstep'><span>○</span><a href='{href}'>{html.escape(label)} →</a></div>")
        first = next((x for x in steps if not p[x[0]]), None)
        return f"""<section class='onboarding card'>
          <div><span class='eyebrow'>SETUP STATUS</span><h2 style='margin:0'>Complete FleetSheet setup</h2></div>
          <div class='setupsteps'>{''.join(rows)}</div>
          <p class='actions'><a class='btn' href='{first[2]}'>Continue setup →</a></p>
        </section>"""

    def view_dash(self, con, q=None):
        """The dashboard: Today (the full working list) plus Money, Assets, and
        Reports summary cards.

        Desktop shows all four cards. On phone widths only the Today card shows —
        the other three are one tap away in the nav. Every list is capped at
        DASH_CAP rows with a quiet '+ N more' that opens the full audit in a
        popup window (desktop) or sheet (phone)."""
        desk = self.desk(con)
        must = engine.today_must_do(con)
        can = engine.today_can_do(con)
        later = engine.today_later(con)

        def stack(items, tier, empty_note=""):
            if not items:
                return f"<p class='mute'>{empty_note}</p>" if empty_note else ""
            rows = ""
            for it in items[:DASH_CAP]:
                href = it.get("href") or it.get("link") or ""
                link = (f"<a href='{html.escape(href, quote=True)}'>{html.escape(it['text'])}</a>"
                        if href else html.escape(it["text"]))
                done_btn = ""
                if it.get("task_id"):
                    done_btn = (
                        f" <form method='post' action='/today/task/done' style='display:inline'>"
                        f"<input type='hidden' name='task_id' value='{it['task_id']}'>"
                        f"<input type='hidden' name='clerk' value='{html.escape(desk, quote=True)}'>"
                        f"<button class='mini'>Done</button></form>")
                rows += f"<div class='todo tier-{tier}'>{link}{done_btn}</div>"
            rows += more_link(len(items), min(len(items), DASH_CAP), "/today/all", "Everything — Today")
            return rows

        # Calm state: nothing must-do today — offer tomorrow's work, no red flashing.
        if not must:
            tomorrow = engine.today_tomorrow(con)
            calm = ("<div class='calm'><b>Nothing on fire today.</b> "
                    "Get a head start on tomorrow:</div>" + stack(tomorrow, "must"))
        else:
            calm = ""

        today_card = f"""
        <section class="dcard today">
        <h2 class="cardtitle">Today</h2>
        {stack(must, "must")}
        {calm}
        {stack(can, "can")}
        {stack(later, "later")}
        </section>"""
        task_card = f"""
        <section class="dcard">
        <h3>Add a task</h3>
        <form method="post" action="/today/task/add" class="tform">
        <input name="text" placeholder="What needs doing?" size="40">
        <select name="tier">
        <option value="must">Must do</option>
        <option value="can" selected>Can do</option>
        <option value="later">Do it later</option>
        </select>
        <button>Add</button></form>
        {self._sticky_notes(con, q or {})}
        </section>"""

        return f"""
        
        {self._onboarding_card(con)}
        {self._pin_nag(con)}
        <div class="dashgrid">
        <div class="pbox" data-title="Today" data-pkey="dashgrid">{today_card}</div>
        <div class="pbox" data-title="Billing" data-pkey="dashgrid"><div style="display:flex;flex-direction:column;gap:8px">{self._dash_money_card(con)}{task_card}</div></div>
        <div class="pbox" data-title="Assets" data-pkey="dashgrid"><div style="display:flex;flex-direction:column;gap:8px">{self._dash_assets_card(con)}{self._dash_reports_card(con)}</div></div>
        </div>
        {self._done_box(con, "/")}
        """

    def _dash_money_card(self, con):
        """Dashboard summary: biggest open balances + the four money groups."""
        d = engine.dashboard(con)
        open_inv = sorted(engine.list_open_invoices(con),
                          key=lambda r: r["balance"], reverse=True)
        rows = ""
        for r in open_inv[:DASH_CAP]:
            rows += (f"<div class='todo'><a href='/invoice/{html.escape(r['invoice_no'], quote=True)}'>"
                     f"{html.escape(r['invoice_no'])} — {html.escape(r['account_name'])}</a> "
                     f"<span class='mute'>${r['balance']:,.2f}</span></div>")
        rows += more_link(len(open_inv), min(len(open_inv), DASH_CAP), "/money/audit", "All money — audit")
        return f"""
        <section class="dcard hidephone">
        <h2 class="cardtitle">Billing <a class="full" href="/money">view →</a></h2>
        <div class="mstat"><span>Open AR</span><b>${d['open_ar']:,.2f}</b></div>
        <p class="hint">ready to bill ${d['ready_amt']:,.2f} · petty cash ${d['pc_balance']:,.2f}</p>
        {rows or "<p class='mute'>Nothing outstanding.</p>"}
        </section>"""

    def _dash_assets_card(self, con):
        """Dashboard summary: what needs paper. (Idle iron lives on the Assets tab.)"""
        paper, _idle, _idle_day, _idle_other = self._asset_lists(con)
        paper_html = "".join(
            f"<div class='todo'><a href='{html.escape(p['h'], quote=True)}'>"
            f"{html.escape(p['t'])}</a></div>" for p in paper[:DASH_CAP])
        paper_html += more_link(len(paper), min(len(paper), DASH_CAP), "/assets/all", "All assets")
        return f"""
        <section class="dcard hidephone">
        <h2 class="cardtitle">Assets <a class="full" href="/assets">view →</a></h2>
        <h3>Needs paperwork ({len(paper)})</h3>
        {paper_html or "<p class='mute'>Paper's clean.</p>"}
        </section>"""

    def _dash_reports_card(self, con):
        """Dashboard summary: the compliance watch (walkthrough #3: titled Compliance)."""
        watch = engine.fleet_compliance_watch(con)
        rows = ""
        for w in watch[:DASH_CAP]:
            rows += (f"<div class='todo'><a href='/ucompliance/{html.escape(w['asset_id'], quote=True)}'>"
                     f"{html.escape(w['unit_no'])} — {html.escape(w['item'])}</a> "
                     f"<span class='mute'>{html.escape(w['status'].title())}</span></div>")
        rows += more_link(len(watch), min(len(watch), DASH_CAP),
                          "/reports?b=avail&all=1", "Compliance watch — everything")
        return f"""
        <section class="dcard hidephone">
        <h2 class="cardtitle">Compliance <a class="full" href="/compliance">view →</a></h2>
        <h3>Compliance watch ({len(watch)})</h3>
        {rows or "<p class='mute'>Nothing due.</p>"}
        </section>"""

    def view_today_all(self, con):
        """Everything the Today ranking considered — the audit view."""
        sections = engine.today_everything(con)
        body = ""
        for title, items in sections:
            rows = ""
            for it in items:
                label = (f"<a href='{html.escape(it['href'], quote=True)}'>"
                         f"{html.escape(it['text'])}</a>" if it.get("href")
                         else html.escape(it['text']))
                # Tasks are already tasks; everything else can become one.
                task_btn = (_task_from_row(it['text'], it['href'], '/today/all')
                            if it.get("href") and title != "Tasks" else "")
                rows += f"<div class='todo'>{label} {task_btn}</div>"
            body += f"<h2>{html.escape(title)} ({len(items)})</h2>{rows}"
        return f"""
        <h1>Everything</h1>
        <p class="hint">Billing candidates live on <a href="/money">Billing</a>.
        <a href="/">Back to Today</a>.</p>
        <p class="hint"><input id="auditq" placeholder="Filter this list…" size="30"
        oninput="var q=this.value.toLowerCase();document.querySelectorAll('div.todo').forEach(function(d){{d.style.display=d.textContent.toLowerCase().indexOf(q)>=0?'':'none';}})"></p>
        {body or "<p class='mute'>Nothing open. Quiet yard.</p>"}
        """


    def _btn_row(self, save_label="Save", jobpop=None, add_item=False, extra=""):
        """Standard 4-button row (Jason 2026-10-07): right-justified, order always
        Add Item, Job Info, Print, Save. Skip buttons that are useless, never reorder."""
        btns = []
        if add_item:
            btns.append('<button type=button>Add Item</button>')
        if jobpop:
            btns.append(f'<button type=button onclick="document.getElementById(\'{jobpop}\').style.display=\'block\'">Job Info</button>')
        btns.append('<button type=button onclick="window.print()">Print</button>')
        btns.append(f'<button type=submit>{save_label}</button>')
        return f'<p style="text-align:right">{" ".join(btns)}{extra}</p>'

    def _job_info_popup(self, pid, vals=None):
        """Universal job info popup with all 9 fields (Jason 2026-10-07).
        Identical on Sale, Rental, Quote, Invoice, Credit Memo."""
        v = vals or {}
        def g(k): return html.escape(str(v.get(k) or ''), quote=True)
        return f"""
          <div id="{pid}" style="display:none;position:fixed;top:8%;left:8%;right:8%;background:white;border:2px solid #333;padding:18px;z-index:1000;max-height:84%;overflow:auto">
            <h3 style="margin-top:0">Job info <button type=button onclick="document.getElementById('{pid}').style.display='none'" style="float:right">Close</button></h3>
            <div class="row"><div><label>Job Name</label><input name=job_name value="{g('job_name')}"></div><div><label>Job Location</label><input name=job_location value="{g('job_location')}"></div></div>
            <div class="row3"><div><label>PO #</label><input name=po value="{g('po')}" class=w-sm></div><div><label>Well #</label><input name=well_no value="{g('well_no')}" class=w-sm></div><div><label>AFE #</label><input name=afe value="{g('afe')}" class=w-sm></div></div>
            <div class="row3"><div><label>Contact Name</label><input name=contact_name value="{g('contact_name')}"></div><div><label>Phone</label><input name=contact_phone value="{g('contact_phone')}" class=w-sm></div><div><label>Email</label><input name=contact_email value="{g('contact_email')}"></div></div>
            <div class="row"><div><label>Cost Code</label><input name=cost_code value="{g('cost_code')}" class=w-sm></div><div><label>Ticket # ref</label><input name=ticket_ref value="{g('ticket_ref')}" class=w-sm></div></div>
            <div><label>Notes</label><input name=job_notes value="{g('job_notes')}"></div>
            <div><label>Attach File</label><input type=file name=job_attach></div>
          </div>"""

    def _g(self, row, key, default=""):
        try:
            if key not in row.keys():
                return default
            v = row[key]
            return default if v is None else v
        except Exception:
            return default

    def _sel(self, values, selected=""):
        out = ['<option value="">— pick —</option>']
        for v in values:
            sel = " selected" if str(v) == str(selected) else ""
            out.append(f'<option{sel}>{html.escape(str(v))}</option>')
        return "\n".join(out)

    def view_setup(self, con, q):
        c = self.company(con)
        if (q.get("edit") or "") == "1":
            return self._setup_form(con, c)
        return self._setup_summary(con, c)

    def view_setup_vendors(self, con, q=None):
        q = q or {}
        msg = (q.get("msg") or "").strip()
        banner = f"<p class='ok'>{html.escape(msg)}</p>" if msg else ""
        return tabs_setup("/setup/vendors", "Vendors") + banner + self._vendor_block(con)

    def view_setup_billing(self, con, q=None):
        # MANUAL-SOURCE (removed from screen 2026-10-08, belongs in manual):
        # - "Defaults used when FleetSheet creates invoices and rental charges.
        #   Each transaction can override an applicable default."
        # - "Used as the starting terms for new customers and invoices."
        # - "Minimum days billed when a rental leaves the yard. A contract can
        #   override this."
        # - "New quotes use this expiration unless you choose a different date."
        c = self.company(con)
        def g(k, default=""):
            try:
                v = c[k]
                return default if v is None else str(v)
            except Exception:
                return default
        return tabs_setup("/setup/billing") + f"""
        <form method=post action="/setup/billing">
          <div class="row">
            <div><label>Invoice Number Prefix</label><input name=invoice_prefix class=w-xs maxlength=6 value="{html.escape(g('invoice_prefix'))}"></div>
            <div><label>Billing Email</label><input name=billing_email type=email class=w-md value="{html.escape(g('billing_email'))}"></div>
          </div>
          <div class="row">
            <div><label>Default Payment Terms</label><input name=default_terms class=w-sm value="{html.escape(g('default_terms','Net 30'))}"></div>
            <div><label>Minimum Rental Billing Days</label><input name=min_days type=number min=1 class=w-xs value="{html.escape(g('min_days','1'))}"></div>
          </div>
          <div class="row"><div><label>Default quote validity (days)</label><input name=quote_valid_days type=number min=1 class=w-xs value="{html.escape(engine.get_option(con, 'quote_valid_days', '30'))}"></div><div></div></div>
          <label><input type=checkbox name=bill_both_dates value=1 {"checked" if g('bill_both_dates','0') in ('1','True') else ""}> Bill both the on-rent and off-rent dates</label>
          <p class=actions><button>Save billing settings</button></p>
        </form>
        """

    def view_setup_admin(self, con, q=None):
        # MANUAL-SOURCE (removed from screen 2026-10-08, belongs in manual):
        # - "(USB drive, other disk, network path, or a Drive/OneDrive folder
        #   already mapped on this computer)"
        b = engine.backup_status(con)
        last = html.escape(b.get("last") or "never")
        status = "Overdue — older than 7 days" if b.get("stale") else "Up to date"
        try:
            _ver = (Path(__file__).resolve().parent / "VERSION").read_text(
                encoding="ascii").strip() or "dev"
        except OSError:
            _ver = "dev"
        return tabs_setup("/setup/admin") + f"""
        <section class=card>
          <h2>Backup Settings</h2>
          <p>Current backup status: <b>{status}</b>. Last backup: <b>{last}</b>.</p>
          <p class=actions><a class="btn secondary" href="/backup">Manage backups →</a></p>
        </section>
        <section class=card>
          <h2>Updates</h2>
          <p>FleetSheet version <b>{html.escape(_ver)}</b>. Installed copies check for updates automatically once a week.</p>
          <form method=post action="/update-check"><p class=actions><button class="btn secondary" type=submit>Check for updates now</button></p></form>
        </section>
        <section class=card>
          <h2>System Administration</h2>
          <p class=actions><a class="btn secondary" href="/setup/devices">Manage devices</a> <a class="btn secondary" href="/setup/health">Data Health</a> <a class="btn secondary" href="/manual" target="_blank">Operation Manual (PDF)</a></p>
        </section>
        """ + self._done_box(con, "/setup/admin")

    def _setup_summary(self, con, c):
        main = engine.main_company_phone(con)
        main_txt = format_phone(main['number']) if main else "—"
        city = ", ".join(
            x for x in (self._g(c, "addr_city"), self._g(c, "addr_state")) if x
        )
        p = self._setup_progress(con)
        done = sum(1 for v in p.values() if v)
        status = f"<div class='hint'>Setup progress: <b>{done}/5 complete</b>.</div>"
        return tabs_setup("/setup", "Company setup") + f"""
        <div class="card" style="max-width:560px">
          <span>Company setup — saved</span>
          <b style="font-size:20px">{html.escape(c["name"] or "—")}</b>
          <p class="hint">{html.escape(self._g(c, "dba") or "")}</p>
          <p>{html.escape(main_txt)}<br>{html.escape(city)}</p>
          {status}
          <p class="actions"><a class="btn" href="/setup?edit=1">Edit company setup</a></p>
        </div>
        """ + self._done_box(con, "/setup")

    def _setup_form(self, con, c):
        # Example company name clears on focus (Jason 2026-10-08): if the name
        # is still the seeded example, mark it so the footer JS wipes it.
        _cname = html.escape(c['name'])
        _cex = ' data-example="YOUR COMPANY LLC"' if (c['name'] or '').strip().upper() == "YOUR COMPANY LLC" else ""
        return tabs_setup("/setup", "Company setup") + f"""
        <form method=post action="/setup" id="setup-form" enctype="multipart/form-data">
        <div class="fgrid">
          <div>
            <div><label>Legal Company Name</label><input name=name value="{_cname}" required{_cex}></div>
            <div><label>Billing Address</label><input name=addr_street id="bill_street" value="{html.escape(self._g(c, 'addr_street'))}"></div>
            <div><label>Address line 2 <span class="hint">(optional)</span></label>
            <input name=addr_street2 value="{html.escape(self._g(c, 'addr_street2'))}" placeholder="Apt, suite, c/o Accounts Payable&hellip;"></div>
            <div class="row3">
              <div><label>City</label><input name=addr_city id="bill_city" value="{html.escape(self._g(c, 'addr_city'))}"></div>
              <div><label>State</label><input name=addr_state id="bill_state" class=w-xs value="{html.escape(self._g(c, 'addr_state'))}" maxlength=20></div>
              <div><label>ZIP</label><input name=addr_zip id="bill_zip" class=w-xs value="{html.escape(self._g(c, 'addr_zip'))}" maxlength=12></div>
            </div>
          </div>
          <div>
            <div><label>DBA / trade name <span class="hint">(optional)</span></label><input name=dba value="{html.escape(self._g(c, 'dba'))}"></div>
            <div><label>Physical address <span class="hint"><label style="display:inline;margin:0"><input type=checkbox id="phys_same" style="width:auto"> same as billing</label></span></label><input name=phys_street id="phys_street" value="{html.escape(self._g(c, 'phys_street'))}"></div>
            <div class="row3">
              <div><label>City</label><input name=phys_city id="phys_city" value="{html.escape(self._g(c, 'phys_city'))}"></div>
              <div><label>State</label><input name=phys_state id="phys_state" class=w-xs value="{html.escape(self._g(c, 'phys_state'))}" maxlength=20></div>
              <div><label>ZIP</label><input name=phys_zip id="phys_zip" class=w-xs value="{html.escape(self._g(c, 'phys_zip'))}" maxlength=12></div>
            </div>
            <div class="frow">
              <div style="flex:1"><label>County <span class="hint">(tax)</span></label><input name=phys_county value="{html.escape(self._g(c, 'phys_county'))}" maxlength=40></div>
              <div style="flex:1"><label>Company logo <span class="hint">(optional)</span></label>
              {('<img src="/company-logo" alt="Current logo" style="height:40px;background:var(--surface);border:1px solid #d0d5dd;border-radius:4px;padding:2px"><br>' + '<label><input type=checkbox name=remove_logo value=1> Remove current logo</label><br>' if engine.get_option(con, "company_logo", "") else "")}
              <input type=file name=company_logo accept="image/*"></div>
            </div>
          </div>
        </div>
        </form>
        <script>
        /* Physical "same as billing": copy billing fields over, lock them. */
        (function(){{
          var cb = document.getElementById("phys_same");
          if (!cb) return;
          var pairs = [["bill_street","phys_street"],["bill_city","phys_city"],
                       ["bill_state","phys_state"],["bill_zip","phys_zip"]];
          function sync(){{
            var on = cb.checked;
            pairs.forEach(function(pr){{
              var src = document.getElementById(pr[0]);
              var dst = document.getElementById(pr[1]);
              if (!src || !dst) return;
              if (on) dst.value = src.value;
              dst.readOnly = on;
            }});
          }}
          cb.addEventListener("change", sync);
          pairs.forEach(function(pr){{
            var src = document.getElementById(pr[0]);
            if (src) src.addEventListener("input", function(){{ if (cb.checked) sync(); }});
          }});
          sync();
        }})();
        </script>
        <script>
        /* Company setup draft: navigating away mid-form no longer loses
           typing. The draft restores on return and clears on save. */
        (function(){{
          var KEY = "fleetsheet-setup-draft-v1";
          var form = document.getElementById("setup-form");
          if (!form) return;
          function own(el){{ return el.closest("form") === form; }}
          function readDraft(){{
            try {{
              var d = JSON.parse(localStorage.getItem(KEY) || "null");
              if (!d || !d.ts || Date.now() - d.ts > 7*864e5) return null;
              return d.fields || {{}};
            }} catch(e){{ return null; }}
          }}
          function writeDraft(){{
            var fields = {{}};
            form.querySelectorAll("[name]").forEach(function(el){{
              if (!own(el)) return;
              if (el.type === "checkbox") fields[el.name] = el.checked ? "1" : "";
              else if (el.type !== "submit" && el.type !== "button") fields[el.name] = el.value;
            }});
            try {{ localStorage.setItem(KEY, JSON.stringify({{ts: Date.now(), fields: fields}})); }} catch(e){{}}
          }}
          var draft = readDraft();
          if (draft) {{
            form.querySelectorAll("[name]").forEach(function(el){{
              if (!own(el) || !(el.name in draft)) return;
              if (el.type === "checkbox") el.checked = draft[el.name] === "1";
              else el.value = draft[el.name];
            }});
          }}
          form.addEventListener("input", writeDraft);
          form.addEventListener("change", writeDraft);
          form.addEventListener("submit", function(){{ try{{ localStorage.removeItem(KEY); }}catch(e){{}} }});
        }})();
        </script>
        {self._phone_block(con)}
        {self._crew_block(con)}
        <p style="margin-top:8px"><button form="setup-form" class="big">Save setup</button></p>
        """

    def _phone_block(self, con):
        phones = engine.list_company_phones(con)
        if phones:
            items = "".join(
                f"<div style='display:flex;justify-content:space-between;align-items:center;padding:2px 0;border-bottom:1px solid #eef0f3'>"
                f"<span><b>{html.escape(p['label'])}</b>{' <b>(main)</b>' if p['is_main'] else ''} &mdash; "
                f"{html.escape(format_phone(p['number']))}</span>"
                f"<form method=post action='/setup/phones/del' style='display:inline;margin:0'>"
                f"<input type=hidden name=phone_id value='{p['phone_id']}'>"
                f"<button class='secondary' type=submit style='padding:2px 8px;font-size:12px'>Remove</button></form></div>"
                for p in phones)
            scroll_list = (f"<div style='max-height:110px;overflow-y:auto;border:1px solid #e0e4ea;border-radius:4px;padding:4px 8px'>"
                           f"{items}</div>")
        else:
            scroll_list = "<p class='hint' style='margin:4px 0'>No phone numbers yet.</p>"
        return f"""
        <h2 style="font-size:16px;color:var(--frame)">Phone Numbers</h2>
        <div class="frow" style="align-items:flex-start">
          <div style="flex:1">
            <form method=post action="/setup/phones/add" style="margin:0">
              <div class="frow">
                <div><label>Number</label><input name=number maxlength=40 required placeholder="+1 (337) 555-0100" style="max-width:26ch"></div>
                <div><label>Label</label><input name=label class=w-sm maxlength=40 placeholder="Main, Service&hellip;"></div>
                <div style="padding-bottom:1px"><button class="secondary">Add phone</button></div>
              </div>
            </form>
          </div>
          <div style="flex:1">{scroll_list}</div>
        </div>
        """

    def _vendor_block(self, con):
        rows = engine.list_vendors(con)
        body = [
            f"<tr><td><b>{html.escape(v['name'])}</b></td>"
            f"<td>{html.escape(v['kind'])}</td>"
            f"<td>{html.escape(v['phone'] or '')}</td>"
            f"<td>{html.escape(v['email'] or '')}</td>"
            f"<td>{html.escape(v['specialties'] or '')}</td>"
            f"<td style='text-align:right;white-space:nowrap'>"
            f"<form method=post action='/setup/vendors/del' style='display:inline;margin:0'>"
            f"<input type=hidden name=vendor_id value='{v['vendor_id']}'>"
            f"<button type=submit class='secondary'>Remove</button></form></td></tr>"
            for v in rows]
        table = capped_table(["Name", "Kind", "Phone", "Email", "What for", ""], body)
        return f"""<p style="margin:0 0 8px"><a class="btn" href="#" onclick="document.getElementById('vendform').style.display=document.getElementById('vendform').style.display=='none'?'block':'none';return false">+ New vendor</a>
        <button type="button" class="vbtn" data-audit="/setup/vendors/all" data-title="Vendors — all">View all vendors</button></p>
        {table}
        <div id="vendform" style="display:none">
        <form method=post action="/setup/vendors" style="margin-top:8px" class="card">
          <div class="frow">
            <div style="flex:1 1 160px"><label>Name</label><input name=name maxlength=80 required placeholder="Acme Load Testing"></div>
            <div><label>Kind</label><select name=kind style="max-width:110px"><option value="vendor">vendor</option><option value="crew">crew</option></select></div>
            <div><label>Phone</label><input name=phone maxlength=40 placeholder="+1 (337) 555-0100" style="max-width:26ch"></div>
          </div>
          <div class="frow">
            <div style="flex:1 1 160px"><label>Email</label><input name=email maxlength=80></div>
            <div style="flex:2 1 200px"><label>What For</label><input name=specialties maxlength=120 placeholder="load tests, sling inspections"></div>
            <div style="align-self:end"><button class="secondary">Add vendor</button></div>
          </div>
        </form>
        </div>
        """ + self._done_box(con, "/setup/vendors")

    def view_vendors_all(self, con):
        """Every vendor — filterable, sortable audit popup."""
        rows = engine.list_vendors(con)
        body = "".join(
            f"<tr><td><b>{html.escape(v['name'])}</b></td>"
            f"<td>{html.escape(v['kind'])}</td>"
            f"<td>{html.escape(v['phone'] or '')}</td>"
            f"<td>{html.escape(v['email'] or '')}</td>"
            f"<td>{html.escape(v['specialties'] or '')}</td></tr>"
            for v in rows)
        return f"""
        <p class="hint"><input id="auditq" placeholder="Filter this list…" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        <span class="mute">Click a column header to sort.</span></p>
        <table class="audit"><tr><th>Name</th><th>Kind</th><th>Phone</th><th>Email</th><th>What for</th></tr>
        {body or '<tr><td colspan=5>No vendors.</td></tr>'}</table>
        """ + AUDIT_TABLE_JS

    # --- Compliance packs ---------------------------------------------------

    def _send_print(self, html_doc):
        # Print pages are full HTML docs rendered outside page(): give them
        # the heartbeat too — an open print tab counts as "FleetSheet is open".
        if "</body>" in html_doc:
            html_doc = html_doc.replace("</body>", HEARTBEAT_JS + "</body>", 1)
        self._send(html_doc)

    def _log_print(self, con, raw, as_pdf):
        """A print job is an explicit completion: log it to the done list
        with the destination (printer vs PDF) — timestamp is automatic."""
        dest = "PDF" if as_pdf else "printer"
        try:
            engine.add_done_manual(con, f"Printed {raw} to {dest}", "/print/" + raw)
        except Exception:
            pass
    def _handle_print(self, con, path, q):
        raw = path[len("/print/"):]
        as_pdf = raw.endswith(".pdf")
        if as_pdf:
            raw = raw[:-4]
        if raw == "done":
            # Done log has no document id — the period comes from the query string.
            self._send_print(printpack.html_done(con, (q.get("period") or "week")))
            return
        parts = raw.split("/", 1)
        if len(parts) != 2:
            self._send(page("Print", "<p>Need a document id.</p>"), 404)
            return
        kind, doc = parts[0], parts[1]
        if kind == "done":
            self._log_print(con, raw, as_pdf)
            self._send_print(printpack.html_done(con, (q.get("period") or "week")))
            return
        if kind == "invoice":
            pack = printpack.invoice_pack(con, doc)
            if not pack:
                self._send(page("Print", "<p>Unknown invoice.</p>"), 404)
                return
            if as_pdf:
                self._log_print(con, raw, as_pdf)
                self._send_bytes(printpack.pdf_invoice(pack), "application/pdf", f"{doc}.pdf")
            else:
                self._log_print(con, raw, as_pdf)
                self._send_print(printpack.html_invoice(pack))
            return
        if kind == "credit":
            pack = printpack.credit_pack(con, doc)
            if not pack:
                self._send(page("Print", "<p>Unknown credit memo.</p>"), 404)
                return
            self._log_print(con, raw, as_pdf)
            self._send_print(printpack.html_credit(pack))
            return
        if kind == "report":
            # Weekly push-button reports: /print/report/<aging|fleet|flow>[.pdf]
            # (?days= for fleet, ?span= for flow).
            try:
                if doc == "aging":
                    if as_pdf:
                        self._log_print(con, raw, as_pdf)
                        self._send_bytes(printpack.pdf_aging(con), "application/pdf", "ar-aging.pdf")
                    else:
                        self._log_print(con, raw, as_pdf)
                        self._send_print(printpack.html_aging(con))
                    return
                if doc == "fleet":
                    try:
                        days = max(1, min(365, int(q.get("days") or 30)))
                    except (TypeError, ValueError):
                        days = 30
                    if as_pdf:
                        self._log_print(con, raw, as_pdf)
                        self._send_bytes(printpack.pdf_fleet(con, days), "application/pdf",
                                         "fleet-utilization.pdf")
                    else:
                        self._log_print(con, raw, as_pdf)
                        self._send_print(printpack.html_fleet(con, days))
                    return
                if doc == "flow":
                    span = "month" if q.get("span") == "month" else "week"
                    if as_pdf:
                        self._log_print(con, raw, as_pdf)
                        self._send_bytes(printpack.pdf_flow(con, span), "application/pdf",
                                         "weeks-flow.pdf")
                    else:
                        self._log_print(con, raw, as_pdf)
                        self._send_print(printpack.html_flow(con, span))
                    return
            except Exception as e:
                self._send(page("Print", f'<div class="err">{html.escape(str(e))}</div>'), 500)
                return
            self._send(page("Print", "<p>Unknown report.</p>"), 404)
            return
        if kind == "petty":
            self._log_print(con, raw, as_pdf)
            self._send_print(printpack.html_petty(con))
            return
        if kind == "quote":
            htmlq = printpack.html_quote(con, doc)
            if not htmlq:
                self._send(page("Print", "<p>Unknown quote.</p>"), 404)
                return
            self._send(htmlq)
            return
        if kind == "change":
            htmlc = printpack.html_change(con, doc)
            if not htmlc:
                self._send(page("Print", "<p>Unknown change order.</p>"), 404)
                return
            self._send(htmlc)
            return
        if kind in ("work", "delivery"):
            pack = printpack.ticket_pack(con, doc)
            if not pack:
                self._send(page("Print", "<p>Unknown ticket.</p>"), 404)
                return
            if as_pdf:
                self._log_print(con, raw, as_pdf)
                self._send_bytes(printpack.pdf_ticket(pack, kind), "application/pdf", f"{kind}-{doc}.pdf")
            else:
                self._log_print(con, raw, as_pdf)
                self._send_print(printpack.html_ticket(pack, kind))
            return
        if kind == "compliance":
            if doc == "fleet":
                pack = printpack.fleet_compliance_pack(con)
                if as_pdf:
                    self._log_print(con, raw, as_pdf)
                    self._send_bytes(printpack.pdf_fleet_compliance_pack(pack),
                                    "application/pdf", "fleet-compliance-pack.pdf")
                else:
                    self._log_print(con, raw, as_pdf)
                    self._send_print(printpack.html_fleet_compliance_pack(pack))
                return
            if doc.endswith("/sel"):
                aid = doc[:-4]
                def _ids(v):
                    out = []
                    for p in (v or "").split(","):
                        p = p.strip()
                        if p.isdigit():
                            out.append(int(p))
                    return out
                pick_c, pick_d = _ids(q.get("c")), _ids(q.get("d"))
                if not pick_c and not pick_d:
                    self._send(page("Print", "<p>Select at least one check or document first.</p>"), 400)
                    return
                pack = printpack.compliance_pack(con, aid, pick_c, pick_d)
                nothing = (not pack or not (pack["items"] or pack["docs"])
                           or (pick_c and not pack["items"] and not pick_d)
                           or (pick_d and not pack["docs"] and not pick_c))
                if nothing:
                    self._send(page("Print", "<p>Select at least one check or document first.</p>"), 400)
                    return
                if as_pdf:
                    self._log_print(con, raw, as_pdf)
                    self._send_bytes(printpack.pdf_compliance_pack(pack),
                                    "application/pdf", f"compliance-{aid}-selected.pdf")
                else:
                    self._log_print(con, raw, as_pdf)
                    self._send_print(printpack.html_compliance_pack(pack))
                return
            pack = printpack.compliance_pack(con, doc)
            if not pack:
                self._send(page("Print", "<p>Unknown unit.</p>"), 404)
                return
            if as_pdf:
                self._log_print(con, raw, as_pdf)
                self._send_bytes(printpack.pdf_compliance_pack(pack),
                                "application/pdf", f"compliance-{doc}.pdf")
            else:
                self._log_print(con, raw, as_pdf)
                self._send_print(printpack.html_compliance_pack(pack))
            return
        self._send(page("Print", "<p>Unknown print type.</p>"), 404)

    def view_export(self, con, q=None):
        """Data out: the weekly push-button reports, a quick export, unlimited
        custom builds with real field/filter selection, and the legacy saved
        presets. Lives under Reports now — Export is no longer a Setup tab."""
        q = q or {}
        # ---- quick export (the original four questions) ----
        what_first_k, what_first_lab = exportpack.PACK_LABELS[0]
        what_combo = (
            combo_field("f_exp_what", "what_text",
                        [(k, lab, k) for k, lab in exportpack.PACK_LABELS],
                        value=what_first_lab, label="What",
                        placeholder="Type to search datasets…")
            + f'<input type=hidden id="f_exp_what_id" name=what value="{what_first_k}">'
        )
        when_choices = [
            ("all", "All time"),
            ("ytd", "Year to date"),
            ("month", "This month"),
            ("week", "Last 7 days"),
            ("custom", "Custom range"),
        ]
        when_opts = "".join(f'<option value="{k}">{html.escape(lab)}</option>' for k, lab in when_choices)
        how_choices = [
            ("csv", "CSV — Excel, Power BI, Tableau"),
            ("xlsx", "Excel workbook (.xlsx)"),
            ("json", "JSON — Power Query, scripts"),
        ]
        how_opts = "".join(f'<option value="{k}">{html.escape(lab)}</option>' for k, lab in how_choices)
        today = date.today().isoformat()

        what_label = dict(exportpack.PACK_LABELS)
        when_label = dict(when_choices)
        how_label = dict(how_choices)
        saved = engine.list_saved_exports(con)
        if saved:
            rows = []
            for s in saved:
                when_txt = when_label.get(s["when"], s["when"])
                if s["when"] == "custom" and s["from_date"] and s["to_date"]:
                    when_txt = f'{s["from_date"]} to {s["to_date"]}'
                desc = f'{what_label.get(s["what"], s["what"])} · {when_txt} · {how_label.get(s["how"], s["how"])}'
                rows.append(f"""
                <tr>
                  <td><strong>{html.escape(s['label'])}</strong><div class="hint">{html.escape(desc)}</div></td>
                  <td style="text-align:right">
                    <a class="btn" href="/export/saved/{s['export_id']}">Run</a>
                    <form method=post action="/export/saved/del" style="display:inline" onsubmit="return confirm('Remove this saved export?')">
                      <input type=hidden name=export_id value="{s['export_id']}">
                      <button class="secondary">Remove</button>
                    </form>
                  </td>
                </tr>""")
            saved_html = f"""
            <h2 style="font-size:16px;color:var(--frame)">Saved Exports</h2>
            <table class="tbl"><tbody>{''.join(rows)}</tbody></table>
            """
        else:
            saved_html = ""

        # ---- custom builds: real field + filter selection over every dataset ----
        ds = q.get("ds") or "tickets"
        if ds not in exportpack.PACKS:
            ds = "tickets"
        ds_label = dict(exportpack.PACK_LABELS).get(ds, ds)
        cols = exportpack.cols_named(ds)
        ds_opts = "".join(
            f'<option value="{k}"{" selected" if k == ds else ""}>{html.escape(lab)}</option>'
            for k, lab in exportpack.PACK_LABELS if k != "all")
        field_checks = "".join(
            f'<label style="display:inline-block;margin:2px 10px 2px 0;font-size:12.5px">'
            f'<input type=checkbox name="f_{c}" checked> {html.escape(c)}</label>'
            for c in cols)
        field_combo_opts = [(c, c, c) for c in cols]
        cfield_combo = (
            combo_field("f_cfield", "cfield_text", field_combo_opts,
                        placeholder="(none) — or type a field…")
            + '<input type=hidden id="f_cfield_id" name=cfield value="">'
        )
        csort_combo = (
            combo_field("f_csort", "csort_text", field_combo_opts,
                        placeholder="(record order) — or type a field…")
            + '<input type=hidden id="f_csort_id" name=csort value="">'
        )
        custom_html = f"""
        <h2 style="font-size:16px;color:var(--frame)">Custom Builds</h2>
        <form action="/export" method=get>
          <div class="row">
            <div><label>Dataset</label>
              <select name=ds onchange="this.form.submit()">{ds_opts}</select></div>
            <div><label>Format</label>
              <select name=how><option value=csv>CSV</option><option value=xlsx>Excel (.xlsx)</option><option value=json>JSON (raw)</option><option value=zip>ZIP (csv + xlsx + json)</option></select></div>
          </div>
          <label>Fields <span class="hint">({ds_label} — {len(cols)} available, all ticked)</span></label>
          <div style="border:1px solid #dfe3e8;border-radius:6px;padding:8px 10px;margin-bottom:10px">{field_checks}</div>
          <div class="row">
            <div><label>From <span class="hint">(blank = no floor)</span></label><input type=date name=cfrom></div>
            <div><label>To <span class="hint">(blank = no ceiling)</span></label><input type=date name=cto></div>
          </div>
          <div class="row">
            <div><label>Contains — field <span class="hint">(optional)</span></label>
              {cfield_combo}</div>
            <div><label>Contains — text</label><input name=ctext placeholder="e.g. gulf"></div>
          </div>
          <div class="row">
            <div><label>Sort by <span class="hint">(optional)</span></label>
              {csort_combo}</div>
            <div><label>Direction</label>
              <select name=cdir><option value=asc>Ascending</option><option value=desc>Descending</option></select></div>
          </div>
          <p class="actions">
            <button type=submit formmethod=get formaction="/export/custom/run"
              data-tip="Runs the build right now and streams the file through your browser's Save dialog.">Download</button>
          </p>
          <div class="row" style="align-items:end">
            <div><label>Save this build <span class="hint">(name it to reuse later)</span></label>
              <input name=label maxlength=60 placeholder="e.g. Open tickets for the Monday meeting"></div>
            <div><button type=submit formmethod=post formaction="/export/custom/save" class="secondary">Save build</button></div>
          </div>
        </form>
        """
        customs = engine.list_custom_reports(con)
        if customs:
            crows = []
            for c in customs:
                import json as _json
                fields = _json.loads(c.get("fields") or "[]")
                bits = [what_label.get(c["dataset"], c["dataset"])]
                bits.append(f"{c['field_count']} fields" if c["field_count"] else "all fields")
                if c["from_date"] or c["to_date"]:
                    bits.append(f"{c['from_date'] or '…'} to {c['to_date'] or '…'}")
                if c["contains_field"] and c["contains_text"]:
                    bits.append(f"contains {c['contains_field']} ~ {c['contains_text']!r}")
                if c["sort_field"]:
                    bits.append(f"sort {c['sort_field']} {c['sort_dir']}")
                bits.append(how_label.get(c["how"], c["how"]))
                crows.append(f"""
                <tr>
                  <td><strong>{html.escape(c['label'])}</strong><div class="hint">{html.escape(' · '.join(bits))}</div></td>
                  <td style="text-align:right;white-space:nowrap">
                    <a class="btn" href="/export/custom/{c['report_id']}">Run</a>
                    <a class="btn secondary" href="/export/custom/{c['report_id']}?how=csv">CSV</a>
                    <a class="btn secondary" href="/export/custom/{c['report_id']}?how=xlsx">XLSX</a>
                    <a class="btn secondary" href="/export/custom/{c['report_id']}?how=json">JSON</a>
                    <a class="btn secondary" href="/export/custom/{c['report_id']}?how=zip">ZIP</a>
                    <form method=post action="/export/custom/del" style="display:inline" onsubmit="return confirm('Remove this build?')">
                      <input type=hidden name=report_id value="{c['report_id']}">
                      <button class="secondary">Remove</button>
                    </form>
                  </td>
                </tr>""")
            custom_saved_html = f"""
            <h2 style="font-size:16px;color:var(--frame)">Saved Custom Builds</h2>
            <table class="tbl"><tbody>{''.join(crows)}</tbody></table>
            """
        else:
            custom_saved_html = ""

        return tabs_reports("/export") + weekly_tabs("") + f"""
        <h2 style="font-size:16px;color:var(--frame)">New Export</h2>
        <form>
          <div class="row">
            <div>{what_combo}</div>
            <div><label>When</label><select name=when>{when_opts}</select></div>
          </div>
          <div class="row">
            <div><label>From <span class="hint">(Custom range only)</span></label><input type=date name=from value="{today}"></div>
            <div><label>To <span class="hint">(Custom range only)</span></label><input type=date name=to value="{today}"></div>
          </div>
          <div class="row">
            <div><label>How</label><select name=how>{how_opts}</select></div>
            <div></div>
          </div>
          <p class="hint">Where — pick one:</p>
          <p class="actions">
            <button type=submit formmethod=get formaction="/export/run"
              data-tip="Streams the file through your browser's own Save dialog — internal drive, external drive, wherever you point it.">Download</button>
            <button type=submit formmethod=post formaction="/export/run" class="secondary"
              data-tip="Writes the file straight into the backup folder set in Setup — a USB drive, network path, or a synced Drive/OneDrive folder all work.">Save to backup folder</button>
          </p>
          <div class="row" style="align-items:end">
            <div><label>Save these four choices as a preset <span class="hint">(optional — name it to reuse later)</span></label>
              <input name=label maxlength=60 placeholder="e.g. Monthly AR for bookkeeper"></div>
            <div><button type=submit formmethod=post formaction="/export/save" class="secondary">Save preset</button></div>
          </div>
        </form>
        {custom_html}
        {custom_saved_html}
        {saved_html}
        <p class="hint">Availability and Units are a snapshot of right now, so When is ignored for them.
        A saved preset re-runs its When fresh each time — "This month" always means the month you click Run in, except Custom range, which keeps the exact dates you saved.
        Power BI / Tableau: Get Data → Text/CSV or JSON. Excel: just open the .xlsx. Month columns read YYYY-MM.</p>
        """

    def _handle_export_saved_run(self, con, export_id):
        row = con.execute(
            'SELECT * FROM saved_exports WHERE export_id=?', (export_id,)
        ).fetchone()
        if not row:
            self._send(page("Export", "<p>Saved export not found.</p>"), 404)
            return
        if row["when"] == "custom":
            start, end = row["from_date"] or "", row["to_date"] or ""
        else:
            start, end = self._export_range({"when": row["when"]})
        try:
            data, fname = self._export_build(con, row["what"], row["how"], start, end)
        except Exception as e:
            self._send(page("Export", f'<div class="err">{html.escape(str(e))}</div>'), 500)
            return
        ctype = self._EXPORT_CTYPE.get(fname.rsplit(".", 1)[-1], "application/octet-stream")
        self._send_bytes(data, ctype, fname)

    def _export_range(self, data):
        when = data.get("when") or "all"
        if when == "custom":
            return data.get("from") or "", data.get("to") or ""
        if when == "all":
            return "", ""
        kind = {"week": "7d", "month": "mtd", "ytd": "ytd"}.get(when, "all")
        s, e, _ = engine.period_bounds(kind)
        return s.isoformat(), e.isoformat()

    def _export_build(self, con, what, how, start, end):
        """Returns (bytes, filename)."""
        stamp = f"{start}_to_{end}" if start else "all-time"
        if what == "all":
            if how == "xlsx":
                return exportpack.xlsx_all(con, start, end), f"fleetsheet_{stamp}.xlsx"
            if how == "json":
                return exportpack.json_bundle(con, start, end), f"fleetsheet_{stamp}.json"
            return exportpack.zip_all(con, start, end), f"fleetsheet_{stamp}.zip"
        if what not in exportpack.ALL_PACKS:
            raise ValueError("Unknown export")
        if how == "xlsx":
            return exportpack.xlsx_named(con, what, start, end), f"{what}_{stamp}.xlsx"
        if how == "json":
            return exportpack.json_named(con, what, start, end), f"{what}_{stamp}.json"
        return exportpack.csv_named(con, what, start, end), f"{what}_{stamp}.csv"

    _EXPORT_CTYPE = {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "json": "application/json",
        "csv": "text/csv; charset=utf-8",
        "zip": "application/zip",
    }

    def _handle_done_dump(self, con, q):
        """Dump the done log to CSV — explicit completions + payments collected."""
        import csv
        import io
        period = q.get("period") or "week"
        if period not in ("today", "week", "year"):
            period = "week"
        start, end, label = engine.done_period(con, period)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["type", "date", "time", "description", "amount", "by", "link"])
        for t in engine.done_tasks(con, start, end):
            w.writerow([t["kind"], (t["done_at"] or "")[:10], (t["done_at"] or "")[11:16],
                        t["text"], "", t["done_by"], t["link"]])
        for p in engine.done_payments(con, start, end):
            w.writerow(["payment", (p["pay_date"] or "")[:10], (p["pay_date"] or "")[11:16],
                        f"{p['invoice_no']} — {p['account_name']}", f"{p['amount']:.2f}",
                        p["clerk"], f"/invoice/{p['invoice_no']}"])
        self._send_bytes(buf.getvalue().encode("utf-8"), "text/csv",
                         f"done-log-{period}-{start}-to-{end}.csv")

    def _handle_export_run(self, con, q):
        what = q.get("what") or "all"
        how = q.get("how") or "csv"
        start, end = self._export_range(q)
        try:
            data, fname = self._export_build(con, what, how, start, end)
        except Exception as e:
            self._send(page("Export", f'<div class="err">{html.escape(str(e))}</div>'), 500)
            return
        ctype = self._EXPORT_CTYPE.get(fname.rsplit(".", 1)[-1], "application/octet-stream")
        self._send_bytes(data, ctype, fname)

    def _handle_custom_run(self, con, report_id, q):
        """Run a custom build: saved (report_id) or ad-hoc from the builder
        form (?ds= + f_<field> + cfrom/cto/cfield/ctext/csort/cdir)."""
        import json as _json
        label = "custom"
        if report_id:
            try:
                rid = int(report_id)
            except (TypeError, ValueError):
                self._send(page("Export", "<p>Unknown build.</p>"), 404)
                return
            rep = engine.get_custom_report(con, rid)
            if not rep:
                self._send(page("Export", "<p>Saved build not found.</p>"), 404)
                return
            dataset = rep["dataset"]
            fields = _json.loads(rep.get("fields") or "[]")
            params = dict(from_date=rep.get("from_date") or "", to_date=rep.get("to_date") or "",
                          contains_field=rep.get("contains_field") or "",
                          contains_text=rep.get("contains_text") or "",
                          sort_field=rep.get("sort_field") or "",
                          sort_dir=rep.get("sort_dir") or "asc")
            how = q.get("how") or rep.get("how") or "csv"
            label = rep["label"]
        else:
            dataset = q.get("ds") or "tickets"
            fields = [k[2:] for k in q if k.startswith("f_")]
            params = dict(from_date=q.get("cfrom") or "", to_date=q.get("cto") or "",
                          contains_field=q.get("cfield") or "",
                          contains_text=q.get("ctext") or "",
                          sort_field=q.get("csort") or "",
                          sort_dir=q.get("cdir") or "asc")
            how = q.get("how") or "csv"
        try:
            headers, rows = engine.run_custom(con, dataset, fields, **params)
        except Exception as e:
            self._send(page("Export", f'<div class="err">{html.escape(str(e))}</div>'), 500)
            return
        dicts = [dict(zip(headers, r)) for r in rows]
        stamp = f"{params['from_date']}_to_{params['to_date']}" if params["from_date"] or params["to_date"] else "all-time"
        if how == "xlsx":
            data = exportpack._xlsx([(dataset, headers, dicts)])
            fname = f"custom_{dataset}_{stamp}.xlsx"
        elif how == "json":
            data = _json.dumps({"report": label, "dataset": dataset,
                                "exported": date.today().isoformat(), "rows": dicts},
                               default=str, indent=2).encode("utf-8")
            fname = f"custom_{dataset}_{stamp}.json"
        elif how == "zip":
            data = exportpack.zip_sheets([(dataset, headers, dicts)])
            fname = f"custom_{dataset}_{stamp}.zip"
        else:
            how = "csv"
            data = exportpack._csv(headers, dicts)
            fname = f"custom_{dataset}_{stamp}.csv"
        ctype = self._EXPORT_CTYPE.get(how, "application/octet-stream")
        self._send_bytes(data, ctype, fname)

    def _handle_report_file(self, con, name, q):
        """CSV/XLSX/JSON/ZIP of a prebuilt weekly report (e.g. /export/report/aging.csv)."""
        import json as _json
        base = name.rsplit(".", 1)[0] if "." in name else name
        ext = name.rsplit(".", 1)[-1] if "." in name else ""
        if ext not in ("csv", "xlsx", "json", "zip"):
            self._send(page("Export", "<p>Unknown report file.</p>"), 404)
            return
        try:
            if base == "aging":
                rep = engine.ar_aging(con)
                headers = ["Customer"] + [engine.BUCKET_LABELS[b] for b in engine.BUCKETS] + ["Total"]
                dicts = []
                for r in rep["rows"]:
                    d = {"Customer": r["customer"]}
                    d.update({engine.BUCKET_LABELS[b]: round(r[b], 2) for b in engine.BUCKETS})
                    d["Total"] = round(r["total"], 2)
                    dicts.append(d)
                d = {"Customer": "TOTAL"}
                d.update({engine.BUCKET_LABELS[b]: round(rep["total"][b], 2) for b in engine.BUCKETS})
                d["Total"] = round(rep["grand"], 2)
                dicts.append(d)
                fname = "ar-aging"
            elif base == "fleet":
                try:
                    days = max(1, min(365, int(q.get("days") or 30)))
                except (TypeError, ValueError):
                    days = 30
                rep = engine.fleet_utilization(con, days)
                headers = ["Unit", "Category", "Days on rent", "Idle days", "Down (shop)", "Util %", "Revenue"]
                dicts = [{"Unit": r["unit_no"], "Category": r["category"],
                          "Days on rent": r["rent_days"], "Idle days": r["idle_days"],
                          "Down (shop)": r["down_days"], "Util %": r["util_pct"],
                          "Revenue": r["revenue"]} for r in rep["rows"]]
                fname = f"fleet-utilization-{days}d"
            elif base == "flow":
                span = "month" if q.get("span") == "month" else "week"
                rep = engine.weeks_flow(con, span)
                label = {k: lab for k, lab, _ in engine.FLOW_SECTIONS}
                headers = ["Section", "What", "Who", "When"] + (["Why"] if span == "month" else [])
                dicts = []
                for key, items in rep["sections"]:
                    for i in items:
                        d = {"Section": label.get(key, key), "What": i["what"],
                             "Who": i["who"], "When": i["when"] or ""}
                        if span == "month":
                            d["Why"] = i.get("why") or ""
                        dicts.append(d)
                fname = f"weeks-flow-{span}"
            else:
                self._send(page("Export", "<p>Unknown report.</p>"), 404)
                return
        except Exception as e:
            self._send(page("Export", f'<div class="err">{html.escape(str(e))}</div>'), 500)
            return
        if ext == "xlsx":
            data = exportpack._xlsx([(base, headers, dicts)])
        elif ext == "json":
            data = _json.dumps({"report": base, "exported": date.today().isoformat(),
                                "rows": dicts}, default=str, indent=2).encode("utf-8")
        elif ext == "zip":
            data = exportpack.zip_sheets([(base, headers, dicts)])
        else:
            data = exportpack._csv(headers, dicts)
        self._send_bytes(data, self._EXPORT_CTYPE[ext], f"{fname}.{ext}")

    def _handle_export(self, con, path):
        name = path.rsplit("/", 1)[-1]
        try:
            if name == "fleetsheet.json":
                self._send_bytes(exportpack.json_bundle(con), "application/json", name)
                return
            if name == "fleetsheet.zip":
                self._send_bytes(exportpack.zip_all(con), "application/zip", name)
                return
            if name.endswith(".csv"):
                key = name[:-4]
                if key in exportpack.PACKS:
                    self._send_bytes(exportpack.csv_named(con, key), "text/csv; charset=utf-8", name)
                    return
        except Exception as e:
            self._send(page("Export", f'<div class="err">{html.escape(str(e))}</div>'), 500)
            return
        self._send(page("Export", "<p>Unknown export.</p>"), 404)
