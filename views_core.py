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
import time
import hmac
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, quote_plus, unquote, urlparse

import engine
import printpack
import exportpack
try:
    import updater_winsparkle
except Exception:
    # Older/partial installs without the updater module: Setup renders
    # without the update-check card.
    updater_winsparkle = None

CSS = """
:root { --frame:#2B3542; --gold:#E8B923; --ink:#1a1a1a; --mute:#5C6B7A; --bg:#f8f9fa; --surface:#fdfdfc; --ok:#0f7a43; --bad:#b42318; }
/* [hidden] must win (2026-10-16): author rules like `button{display:inline-block}`
   override the UA `[hidden]{display:none}` rule, so every `hidden` button
   rendered visibly — the lookup Add / "↩ list" buttons showed on every row.
   The `!important` restores the attribute's meaning everywhere. Everything
   that un-hides does so by removing the attribute (lookup JS, audit popup,
   cap-extra toggle) or by CSS display rules on non-hidden elements
   (.todo.extra, .line-del) — none of those rely on `hidden` staying visible. */
[hidden]{display:none !important}
/* Inter: the mainstream business-software typeface, bundled for offline use. (2026-10-06) */
@font-face{font-family:'Inter';font-style:normal;font-weight:400;font-display:swap;src:url('/fonts/inter-400.ttf') format('truetype')}
@font-face{font-family:'Inter';font-style:normal;font-weight:500;font-display:swap;src:url('/fonts/inter-500.ttf') format('truetype')}
@font-face{font-family:'Inter';font-style:normal;font-weight:600;font-display:swap;src:url('/fonts/inter-600.ttf') format('truetype')}
@font-face{font-family:'Inter';font-style:normal;font-weight:700;font-display:swap;src:url('/fonts/inter-700.ttf') format('truetype')}
@font-face{font-family:'Inter';font-style:normal;font-weight:800;font-display:swap;src:url('/fonts/inter-800.ttf') format('truetype')}
*{box-sizing:border-box} body{margin:0;font:14px/1.45 Inter,Calibri,'Segoe UI',sans-serif;background:var(--bg);color:var(--ink)}
header{background:var(--frame);color:#fff;padding:8px 16px;display:flex;align-items:center;flex-wrap:nowrap;gap:10px 16px;position:sticky;top:0;z-index:50}
header .brand{font-size:26px;font-weight:700;margin-right:4px;letter-spacing:.02em;
  padding-right:16px;border-right:1px solid rgba(255,255,255,.25);display:flex;align-items:center;min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
header .brand img{height:34px;max-width:120px;object-fit:contain;margin-right:10px;background:var(--frame);border-radius:4px;padding:2px;flex:none}
header nav.main{display:flex;flex-wrap:nowrap;overflow-x:auto;min-width:0;gap:4px 14px;align-items:center;flex:1} /* flex:1 lets the lock justify far right (Jason 2026-10-06) */
header nav.main a{padding:8px 14px;border-radius:6px}
header nav.main a:hover{background:rgba(255,255,255,.14)}
header nav.main a:focus-visible{outline:3px solid var(--gold);outline-offset:2px}
header nav.main a.on{background:var(--gold);color:var(--frame);font-weight:700}
header nav.aside{margin-left:8px;display:flex;gap:6px;align-items:center;flex:none}
header nav.main .tabright{margin-left:auto;display:inline-flex;gap:4px 14px;align-items:center}
header a{color:#fff;text-decoration:none;font-size:13px;white-space:nowrap;position:relative}
header .yardnote{font-size:11px;color:#c9d2dc;border:1px solid #3d4f68;border-radius:10px;padding:2px 9px;white-space:nowrap}
header a[data-tip]::after,.tabs a[data-tip]::after{content:attr(data-tip);position:absolute;left:0;top:calc(100% + 8px);background:#1a1a1a;color:#fff;font-size:11px;line-height:1.35;font-weight:400;letter-spacing:0;padding:8px 10px;border-radius:4px;width:220px;white-space:normal;opacity:0;pointer-events:none;z-index:40;box-shadow:0 4px 12px rgba(0,0,0,.25);transition:opacity .12s linear}
.news{background:#FFF8E1;border-bottom:2px solid var(--gold);padding:0 16px;display:flex;flex-direction:column;gap:0;position:relative}
/* Ticker squeeze (Jason 2026-10-25, build 'r'): single spacing — the
   strip reads double-spaced with per-row margins and 1.5 line-height.
   Rows carry no vertical margin, minimal padding, tight leading, on
   every page the strip renders (the strip is one component). */
.news-wrap>summary{padding:0 16px;font-size:11px;line-height:1.3}
.news>.tap{margin:0 !important;padding-top:1px !important;padding-bottom:1px !important;line-height:1.3 !important}
.news>.tapbox{margin:0 !important;padding-top:1px !important;padding-bottom:1px !important;line-height:1.3}
/* Ticker category filter popover: quiet, compact, desk-sized. (2026-10-06) */
.news .filterbox{align-self:flex-end;position:relative}
.tickfilter{position:absolute;right:0;top:calc(100% + 4px);background:var(--surface);border:2px solid #c9a227;border-radius:6px;box-shadow:0 6px 16px rgba(0,0,0,.2);padding:10px 12px;z-index:60;min-width:170px;max-width:calc(100vw - 24px)}
.tickfilter form{display:flex;flex-direction:column;gap:6px}
.tickfilter label{display:flex;align-items:center;gap:7px;font-size:13px;cursor:pointer;white-space:nowrap;font-weight:400}
.tickfilter .vbtn{align-self:flex-start;margin-top:2px}
.news .tap{font-size:12.5px;line-height:1.3;display:flex;align-items:center;flex-wrap:nowrap;gap:2px 8px;
  background:var(--surface);border:1px solid #e8dcc0;border-radius:6px;padding:1px 10px;margin:0}
.news .tap .vbtn{margin-left:0;flex:none}
.news .tap .msg{font-weight:600;color:#5d4a00;margin-right:6px;flex:1 1 auto;min-width:0}
.news .tap>a{flex:1 1 auto;min-width:0}
.news .tap.calm .msg{font-weight:400;color:var(--mute)}
.news .tap.top .msg{color:#7a5c00;text-transform:uppercase;font-size:11px;letter-spacing:.04em}
.news .tap.top{font-size:12px}
.news .tap.top .msg{color:var(--mute);font-size:10px}
.news .tapbox{border:1px solid var(--gold);border-radius:6px;background:var(--surface);
  padding:1px 10px;margin:0;display:flex;flex-wrap:nowrap;align-items:center;
  gap:2px 12px;font-size:12.5px;line-height:1.3}
.news .tapbox .msg{font-weight:600;color:#5d4a00;flex:1 1 auto;min-width:0}
.news .tapbox .go{font-weight:600;flex:none}
/* Billing-tab ticker: squeezed — same information, less vertical space. */
.news.squeeze{padding:2px 16px}
.news.squeeze .tapbox{padding:2px 8px;margin:2px 0;font-size:12px;gap:2px 10px}
/* Escalation ladder: tap / slap / punch — the box grows as the consequence
   approaches. Gold stays the cue; red is for real bad states. */
.news .tapbox.lv1{border-width:2px}
.news .tapbox.lv2{border-width:3px;background:#fffdf2}
.news .tapbox.lv2 .msg{color:#7a5c00}
.ackf{display:inline;background:none;border:none;padding:0;width:auto;margin:0}
.ackf input[type=number]{font-size:12px;padding:1px 3px}
/* Walkthrough #3: Snooze rides right-justified; the thin box
   outline on .tapbox above already ties each item's buttons to that item. */
.news .tapbox .ack-right{margin-left:auto;display:inline-flex;gap:22px;align-items:center;flex:none;white-space:nowrap}
.news .tap .ack-right{margin-left:auto;display:inline-flex;gap:22px;align-items:center;flex:none;white-space:nowrap}
.news .tap.top a{font-weight:700;color:var(--frame);margin-right:14px}
.news .tap form,.news .tapbox form{display:inline;background:none;border:none;padding:0;width:auto;margin:0 0 0 6px}
.news .tap button,.news .tapbox button{font-size:11px !important;padding:2px 8px !important;border-radius:3px;border:1px solid var(--frame);background:var(--frame);color:#fff;cursor:pointer;width:auto;min-width:0;line-height:1.4}
.news .tap button.go,.news .tapbox button.go{background:var(--frame);color:#fff;border-color:var(--frame);text-decoration:none;display:inline-block}
.news .tap a.go,.news .tapbox a.go{font-size:11px;padding:2px 8px;border-radius:3px;background:var(--frame);color:#fff;text-decoration:none}
.todo{padding:2px 0;border-bottom:1px solid #e8e8e8;font-size:14px}
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
.sticky-face{display:flex;gap:6px;align-items:center;margin-top:4px}
.sticky-face form{display:inline;background:none;border:none;padding:0;width:auto;margin:0}
.sticky-face .tiny{font-size:11px;color:var(--mute);text-decoration:none;margin-left:2px}
.sticky-face button.tiny{font-size:11px;color:var(--mute);background:none;border:0;padding:0;cursor:pointer;text-decoration:underline}
.tap.mention{background:none;border:none;border-bottom:1px dashed #e0e4ea;font-size:13px;color:#444;padding:3px 2px}
/* Ticker 1+2 (tweak round 2): items 2-3 are whole-row links — the row
   itself is the <a>, so it must not render as underlined link text. */
a.tap.mention{text-decoration:none;display:flex}
.tap.mention a{color:var(--frame);font-weight:600}
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
.pbox-lock{float:right;width:auto;font-size:12px;padding:3px 10px;margin:2px 0 8px 8px;background:var(--frame);border:1px solid var(--frame);border-radius:4px;cursor:pointer;color:#fff}
.pbox-width{width:auto;font-size:11px;padding:1px 8px;margin-left:6px;background:var(--frame);color:#fff;border:1px solid var(--frame);border-radius:3px;cursor:pointer}
.pbox-grip{cursor:grab;margin-right:10px;color:#3d4f68;letter-spacing:1px;font-size:16px;font-weight:700;user-select:none}
.pbox-grip:active{cursor:grabbing}
.pbox-move{font-size:12px;font-weight:400;width:22px;height:22px;line-height:1;padding:0;margin-right:4px;cursor:pointer;background:var(--frame);border:1px solid var(--frame);border-radius:4px;color:#fff}
.pbox-move:hover{background:#0f2a52;border-color:#0f2a52}
#morebelow{position:fixed;left:50%;bottom:14px;transform:translateX(-50%);background:var(--frame);
  border:1px solid var(--frame);color:#fff;border-radius:20px;padding:4px 14px;font-size:12px;
  cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.12);z-index:60;white-space:nowrap}
.stepper{display:inline-flex;align-items:center;justify-content:center;gap:3px;margin:0 4px;vertical-align:middle}
.stepper button{width:24px;height:24px;line-height:1;padding:0;font-size:14px;background:#4F6D8C;color:#fff;border:1px solid #4F6D8C;border-radius:4px;cursor:pointer;display:inline-flex;align-items:center;justify-content:center}
.stepper input[type=number]{width:4em;text-align:center;-moz-appearance:textfield;appearance:textfield;border:1px solid #4F6D8C}
.stepper input[type=number]::-webkit-outer-spin-button,.stepper input[type=number]::-webkit-inner-spin-button{-webkit-appearance:none;margin:0}
/* Snooze stepper −/+ (the only stepper left): smaller and quieter than
   action buttons — present but not prominent (2026-10-15). Tweak round 2:
   the −/+ pair takes a lighter blue than the global button blue
   (--frame #2B3542): #4F6D8C, same slate family, white text stays
   readable; the number input carries a thin border in the same blue. */
.ackf .stepper button{width:18px;height:18px;font-size:11px;background:#4F6D8C;border-color:#4F6D8C;color:#fff}
/* Tweak round 2 (Item 6): the stepper group sits CENTERED in its area,
   not pushed to the row's bottom-right. The ticker message yields its
   flex-grow so the ack cluster's auto margins can center it in the
   row's remaining space; the ack form itself becomes a centered flex
   row so the stepper and its Snooze button sit together, centered.
   The sticky-note snooze form takes its own full-width row inside
   .sticky-ctl and centers its contents the same way. */
.news .tapbox .msg,.news .tap .msg{flex:0 1 auto}
/* Laptop-pass fix round (2026-10-20): Jason reversed the tweak-round
   centering — snooze/steppers sit RIGHT-justified in ticker rows. */
.news .tapbox .ack-right,.news .tap .ack-right{margin-left:auto;margin-right:0;justify-content:flex-end}
/* Ticker mention rows (laptop-pass fix round): rows 2-3 carry their own
   snooze now, so the row is a flex line — the link takes the space, the
   snooze cluster rides right. The link is still the way to the item. */
.news .tap.mentionrow{display:flex;align-items:center;gap:2px 8px}
.news .tap.mentionrow>a{flex:1 1 auto;min-width:0;color:var(--frame);font-weight:600;text-decoration:none}
.ackf:has(.stepper){display:inline-flex;align-items:center;justify-content:center;gap:6px}
.sticky-ctl>form:has(.stepper){flex:1 1 100%;justify-content:center}
/* Per-page header zoom control removed (tweak round 2026-10-20):
   one general zoom lives on the Administration page. */
button.mini{font-size:11px;padding:2px 8px;background:var(--frame);color:#fff;border:1px solid var(--frame)}
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
main{max-width:1200px;margin:8px auto;padding:0 12px 12px;overflow-x:clip}
/* overflow-x:clip (not hidden): a hidden tooltip's 220px box can never widen
   the page, yet no scroll container is created so sticky tabs keep working
   and hovered tips (flipped inward by JS at the viewport edge) still show. */
.actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0}
.mark{position:fixed;bottom:8px;right:12px;font-size:11px;letter-spacing:.08em;color:#1B2A4A;opacity:.28;pointer-events:none;z-index:1}
.tabs{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 8px;padding-bottom:6px;border-bottom:1px solid #d0d5dd;position:sticky;top:58px;z-index:40;background:var(--bg);padding-top:6px}
.tabs.grouped{gap:6px 18px}.tabgroup{display:inline-flex;align-items:center;gap:8px}
.tabgrouplab{font-size:11px;color:var(--mute);text-transform:uppercase;letter-spacing:.5px}
.tabs a{display:inline-block;padding:6px 10px;border-radius:4px;background:var(--frame);border:1px solid var(--frame);color:#fff;text-decoration:none;font-size:13px;position:relative}
.tabs a.on{background:var(--gold);color:var(--frame);border-color:var(--gold);font-weight:700}
.tabs button.tabdoor{padding:6px 10px;border-radius:4px;background:var(--frame);border:1px solid var(--frame);color:#fff;font-size:13px;cursor:pointer;font-family:inherit}
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
label{display:block;font-size:12px;color:var(--mute);margin:4px 0 2px;font-weight:700}
label:has(input[type=checkbox]),label:has(input[type=radio]){display:flex;align-items:center;gap:6px;font-size:14px;color:var(--ink,#222);font-weight:400}
input,select{width:100%;padding:5px 8px;border:1px solid #c5cdd6;border-radius:4px;font:inherit;background:var(--surface)}
/* Input widths, sized to the expected content: a street address doesn't
   need the whole screen. */
input.w-xs,select.w-xs{max-width:96px}
input.w-sm,select.w-sm{max-width:180px}
input.w-md,select.w-md{max-width:320px}
select{padding-right:26px;appearance:none;-webkit-appearance:none;cursor:pointer;
 background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='8'><path d='M1 1l5 5 5-5' fill='none' stroke='%231B2A4A' stroke-width='2.4'/></svg>");
 background-repeat:no-repeat;background-position:right 8px center}
.dollar{position:relative;display:block}
.dollar::before{content:'$';position:absolute;left:10px;top:50%;transform:translateY(-50%);color:var(--mute);font-size:14px;pointer-events:none}
.dollar>input{padding-left:24px}
/* Invoice totals (Issue 3, 2026-10-15): the Tax/Adjustment inputs sit
   mid-sentence, so the block .dollar span detached the $ to the far left
   edge ("lone $" on its own line). Scoped here only — other money inputs
   are width:100% in grid cells, where the block span is correct. */
#inv-totals .dollar{display:inline-block;vertical-align:middle}
#inv-totals>div{white-space:nowrap}
/* Lookup selects (Issue 4): the Other/-Add- text input + buttons live in
   a block wrapper so they sit under the select in its grid cell. */
.lookup-wrap{display:block}
.lookup-wrap [data-lookup-add],.lookup-wrap [data-lookup-list]{margin-top:4px;padding:4px 10px}
.field-err{border:2px solid #8a5a00 !important;background:#fffaeb !important} /* validation: amber, not red (2026-10-06) */
#formerr{display:none;background:#fffaeb;color:#8a5a00;padding:8px;border-radius:6px;margin:8px 0;font-weight:600}
input[type=checkbox]{width:auto;flex:0 0 auto}
.row{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.row3{display:grid;grid-template-columns:2fr 1fr 1fr;gap:8px} /* city/state/zip on one row (Jason 2026-10-06) */
.row4{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px}
/* Stretched-header grids (Jason 2026-10-15): equal 1fr columns give a
   w-xs number field a full quarter width and strand the Customer field
   far right. These put the # field on an auto track and let the
   Customer (or Unit) combo take the leftover space. They collapse to
   one column at narrow widths / large text, like .row4. */
.row4s{display:grid;grid-template-columns:auto 1fr auto auto;gap:8px}
.row4s2{display:grid;grid-template-columns:auto 2fr 1fr auto;gap:8px}
.row5s{display:grid;grid-template-columns:auto 1fr auto auto auto;gap:8px}
.row4w{display:grid;grid-template-columns:auto auto 1fr auto;gap:8px}
/* Pay form (2026-10-15): RP # | Customer | Invoice | Total | Date — the
   Customer and Invoice combos both stretch; # / Total / Date stay auto. */
.row5s2{display:grid;grid-template-columns:auto 1fr 1fr auto auto;gap:8px}
.row4s>*,.row4s2>*,.row5s>*,.row4w>*,.row5s2>*{min-width:0}
.row>*{min-width:0} /* let tracks shrink: wrap inside the column, never widen the page */
.row3>*{min-width:0}
/* Compact form grid (Jason 2026-10-06): two-column dense layout for setup-style
   forms. Opt-in per form — not a global change. */
.fgrid{display:grid;grid-template-columns:1fr 1fr;gap:4px 14px}
.fgrid>.span2{grid-column:span 2}
.fgrid>*{min-width:0}
.fgrid label{margin:3px 0 1px}
.fgrid input,.fgrid select{padding:5px 7px}
/* Setup -> Billing Job Info toggles (Invoice Round Part B): the global
   `label{display:block}` rule (and the block-level flex from
   label:has(checkbox)) stacks every checkbox label on its own line, so
   the 12 toggles became one tall single column. A grid container puts
   them in compact columns that collapse at narrow widths instead of
   overflowing; each option label is a tight flex row inside its cell. */
.jb-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:2px 14px}
.jb-grid label{display:flex;align-items:center;gap:6px;margin:0;padding:2px 0;font-weight:400}
/* Setup -> Billing curation entries (laptop-pass fix round): the entry
   span top-aligns and the value text is a plain block, so a two-word
   name that wraps shows BOTH words — the old centered flex label let
   a wrapped first word clip, and 'Preventive Maintenance' read as a
   second 'Maintenance' entry. */
.jb-grid .en-item{display:flex;align-items:flex-start;gap:2px}
.jb-grid .en-item label{align-items:flex-start}
.jb-grid .en-item .en-txt{display:block;padding-top:1px}
.jb-grid .en-item>button{margin-top:1px}
/* Tight inline form row (Jason 2026-10-06): label+input pairs sit side by
   side, bottom-aligned, wrapping on narrow screens. */
.frow{display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap}
.frow>*{min-width:0}
/* PIN security-question commit (build 'ah', Jason 2026-10-28): on
   the PIN setup forms the Save button stays on the Answer 2 row,
   with the settings-card field-to-button gap — the .frow 12px the
   Desk idle lock card renders — between the entry box and the
   button, so the two never render as one connected piece. One
   class, every PIN form whose commit follows the questions. */
.sqsave{display:block;margin-top:8px}
button,.btn{background:var(--frame);color:#fff;border:0;padding:9px 14px;border-radius:6px;cursor:pointer;font:inherit;display:inline-block;text-decoration:none;transition:background .12s ease,box-shadow .12s ease,transform .05s ease}
button:hover,.btn:hover{background:#1a2431}
button:active,.btn:active{transform:translateY(1px)}
/* .btn-gold: kept as a class name for existing markup, but it renders
   as the standard button — blue with white wording (Jason's all-blue
   button rule, 2026-10-17; gold is for the header/tab active states
   and quiet cues, not for buttons). */
.btn-gold{background:var(--frame);color:#fff;font-weight:700;border:0;padding:9px 16px;border-radius:6px;cursor:pointer;font:inherit;display:inline-block;text-decoration:none}
.btn-gold:hover{background:#1a2431;color:#fff}
button:focus-visible,.btn:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid #1a1a1a;outline-offset:2px}
/* button.secondary: no separate look anymore — every button is the
   standard blue with white wording (all-blue rule, 2026-10-20). The
   class stays in markup as a hook; it carries no override. */
/* Line-item delete X (Jason 2026-10-14): one red X at the end of every
   line-item row. Empty row -> removed at once; populated row -> confirm. */
button.line-del,button.line-del-submit{color:var(--bad);background:none;border:none;font-weight:700;font-size:16px;line-height:1;padding:2px 6px;cursor:pointer;flex:none}
button.line-del:hover,button.line-del-submit:hover{background:rgba(180,35,24,.1);border-radius:4px}
/* Line-item Rate cell (2026-10-15): the Rate input is width:100%, so a
   bare X after it wrapped onto its own line below the input. Wrapping
   the pair in .rate-x keeps the X pinned to the input's right edge at
   every width — the input shrinks, the X never wraps. */
.rate-x{display:flex;gap:4px;align-items:center}
.rate-x input{flex:1 1 0;min-width:0;width:auto}
.rate-x button{flex:none}
input[type=date]{min-width:132px} /* date inputs must show mm/dd/yyyy whole */
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
tr.grouphd td{background:#e8eef4;color:var(--frame);font-size:13px;padding:4px 8px}
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
  .row,.row3,.row4,.fgrid,.row4s,.row4s2,.row5s,.row4w,.row5s2{grid-template-columns:1fr}
  /* Ticker: narrow screens wrap the controls below the message again —
     nowrap would overflow a phone. Desktop keeps them pinned right. */
  .news .tap,.news .tapbox{flex-wrap:wrap}
  .news .tapbox .ack-right,.news .tap .ack-right{margin-left:0;white-space:normal}
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
.yd label{display:block;font-size:13px;color:var(--mute);margin:8px 0 3px;font-weight:700}
.yd input,.yd select{font-size:17px;padding:10px;width:100%;border:1px solid #c5cdd6;border-radius:4px;background:var(--surface)}
.yd .stat{background:var(--surface);border:1px solid #d0d5dd;border-radius:8px;padding:10px 12px;margin:8px 0}
.yd .qrbox{background:var(--surface);border:1px solid #d0d5dd;border-radius:8px;padding:20px;
  text-align:center;margin:16px 0;word-break:break-all}
.yd .code{font-family:monospace;font-size:14px;background:#eef1f5;padding:10px;border-radius:6px}
.yd h2{font-size:19px;color:var(--frame);margin:8px 0 6px}
.yd h3{font-size:16px;color:var(--frame);margin:8px 0 4px}
.yd a{color:var(--frame)}
/* Dashboard cards: capped lists, quiet "+ N more", audit popup. */
.dashgrid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;align-items:stretch}
.dashgrid>.pbox{display:flex;flex-direction:column;grid-row:span 2}
.dashgrid>.pbox>div{flex:1}
/* Today card columns: the flex-column glue that keeps a lower card
   (e.g. Compliance) stuck tight under the card above it. Cards move
   within/between columns; the columns themselves never move. */
.dashgrid .card-col{display:flex;flex-direction:column;gap:8px}
/* Print menu (Jason 2026-10-18): every Print button offers Print to
   Screen, Print to Location, PRINT. A <details> dropdown — no JS needed
   to open it; PRINTMENU_JS wires the actions and closes it on
   outside clicks. */
.pmenu{position:relative;display:inline-block;vertical-align:middle}
.pmenu summary.pmenu-sum{list-style:none;cursor:pointer;background:var(--frame);color:#fff;border:0;padding:9px 14px;border-radius:6px;font:inherit;display:inline-block}
.pmenu summary.pmenu-sum::-webkit-details-marker{display:none}
.pmenu summary.pmenu-link{list-style:none;cursor:pointer;color:var(--frame);text-decoration:underline;display:inline}
.pmenu summary.pmenu-link::-webkit-details-marker{display:none}
.pmenu .popts{position:absolute;right:0;top:calc(100% + 4px);background:#fff;border:1px solid #c5cdd6;border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.18);padding:6px;z-index:1400;min-width:216px;text-align:left;max-height:calc(100vh - 24px);overflow-y:auto}
/* Print menu anchoring (Jason 2026-10-24, 'm' look-see item 2): a menu
   whose button sits low on the page opens UP instead of running below
   the crease — PRINTMENU_JS adds .up when the downward menu would
   overflow the viewport. The max-height cap + internal scroll is the
   backstop for very short viewports. */
.pmenu.up .popts{top:auto;bottom:calc(100% + 4px)}
.pmenu .popts a,.pmenu .popts button{display:block;width:100%;box-sizing:border-box;text-align:left;background:none;border:0;color:#1B2A4A;padding:7px 9px;border-radius:5px;font:inherit;text-decoration:none;cursor:pointer}
.pmenu .popts a:hover,.pmenu .popts button:hover{background:#eef2f7}
.pmenu .pstat{display:block;font-size:11px;color:#49606e;padding:2px 9px;max-width:300px;white-space:normal}

/* Line-item rows (Jason 2026-10-18): one row = one item. A faint but
   noticeable border delineates each row, and the row grows when its
   description wraps down its own column. The description is a
   textarea (class ldesc) confined to its column; LINEDEL_JS
   auto-grows it as the operator types, and grows it on load for
   saved text. */
.lineitem-row,.iline{border:1px solid #aebbcb;border-radius:6px;padding:6px 8px;margin:0 0 6px;background:#fff}
.iline{display:grid;grid-template-columns:104px 1fr 2fr 84px 104px 104px;gap:8px;align-items:start}
table.colines{border-collapse:separate;border-spacing:0 6px}
table.colines th{border-bottom:0}
table.colines td{border-top:1px solid #aebbcb;border-bottom:1px solid #aebbcb;background:#fff;vertical-align:top}
table.colines td:first-child{border-left:1px solid #aebbcb}
table.colines td:last-child{border-right:1px solid #aebbcb}
textarea.ldesc{width:100%;box-sizing:border-box;font:inherit;resize:none;overflow:hidden;line-height:1.35;min-height:2.1em;padding:6px 8px;border:1px solid #9fb0c1;border-radius:5px;background:#fff}
.iline>div,.lineitem-row>div{min-width:0}
.frow.lineitem-row{align-items:flex-start}
/* The global money script wraps step=0.01 inputs in a .dollar span at
   load; inside a .rate-x row that wrapper is the flex item, so it must
   flex too — otherwise the rate input keeps its w-sm width and spills
   out of the row (found in the 2026-10-18 screenshot pass). */
.rate-x .dollar{flex:1 1 auto;min-width:0}
.rate-x .dollar>input{width:100%}
/* Narrow windows (windows rule): the six fixed line columns need
   ~540px; below 720px the row wraps to two columns and the
   description (third cell in every line editor) takes its own
   full-width line, still inside its border. */
.linehead{display:grid;grid-template-columns:104px 1fr 2fr 84px 104px 104px;gap:8px;background:#e8eef4;color:var(--frame);font-weight:600;font-size:12.5px;padding:5px 8px;border:1px solid #aebbcb;border-bottom:0;border-radius:6px 6px 0 0}
.linehead.flex{display:flex;gap:6px}
.linehead + .iline,.linehead + .lineitem-row{border-top-left-radius:0;border-top-right-radius:0}
@media (max-width:720px){
  .linehead{display:none}
  .iline,.lineitem-row{grid-template-columns:1fr 1fr !important}
  .iline>div:nth-child(3),.lineitem-row>div:nth-child(3){grid-column:1/-1}
}

/* Per-card controls (DCARD_JS): one set per card, shown while unlocked. */
.dcard-ctl{display:inline-flex;align-items:center;gap:2px;margin-right:8px}
.dcard-grip{cursor:grab;color:#3d4f68;letter-spacing:1px;font-size:16px;font-weight:700;user-select:none}
.dcard-grip:active{cursor:grabbing}
.dcard-move{font-size:12px;font-weight:400;width:22px;height:22px;line-height:1;padding:0;margin-right:2px;cursor:pointer;background:var(--frame);border:1px solid var(--frame);border-radius:4px;color:#fff}
.dcard-move:hover{background:#0f2a52;border-color:#0f2a52;color:#fff}
.dcard.dragging{opacity:0.5}
.dcard.drop-target{outline:2px dashed var(--gold);outline-offset:2px}
.dashgrid .dcard{flex:1 1 auto}
.dcard .todo.extra{display:none}
.dcard.expanded .todo.extra{display:block}
.card-resize{position:absolute;left:4px;right:4px;bottom:0;height:10px;cursor:ns-resize;touch-action:none;margin:0;border-top:1px solid #e8e8e8}
.card-resize::after{content:'';position:absolute;left:50%;top:3px;width:36px;height:3px;border-radius:2px;background:#c5cdd6;transform:translateX(-50%)}
.dashgrid>.pbox[data-title="Today"]{grid-row:span 2;align-self:stretch;border:none;background:none;padding:0}
.dcard{position:relative;background:var(--surface);border:1px solid #d0d5dd;border-radius:10px;padding:8px 10px 12px;min-width:0}
.dcard.today{grid-row:span 4;align-self:stretch}
/* Today tiers: priority by styling, not labels. */
.todo.tier-must{font-size:16px;font-weight:600;border-left:4px solid var(--gold);padding-left:10px}
.todo.tier-can{font-size:14px}
.todo.tier-later{font-size:13px;color:var(--mute)}
.todo.tier-later a{color:var(--mute)}
.vbtn{background:var(--frame);color:#fff;border:1px solid var(--frame);border-radius:3px;
  font-size:11px;padding:2px 8px;cursor:pointer;margin-left:auto;white-space:nowrap}
/* Build 'ac' (Jason 2026-10-27, one size within a line): a summary
   door-row door renders at the one large standard — the global
   button metrics (14px, padding 9px 14px, no border), the same
   rendered height as the row's Edit and Print. The small .vbtn
   size stands where a whole zone is uniformly small (the View row
   below the door row, the ticker); the door row is one line and
   carries one size. */
.sumdoor{font-size:14px;padding:9px 14px;border:0;border-radius:6px}
/* Summary fact blocks (build 'af', Jason 2026-10-28): a summary's
   facts stand in grouped blocks in columns, mimicking the creation
   form — customer block up-left, Job Info block at right, the
   document's own facts in their own block — never one fact per row
   down the full width. */
.sumfacts{display:flex;flex-wrap:wrap;gap:6px 28px;align-items:flex-start;margin:2px 0 6px}
.sumblk{flex:1 1 280px;min-width:250px}
.sumblk h3{margin:0 0 3px;font-size:12px;font-weight:700;color:var(--frame);text-transform:uppercase;letter-spacing:.05em}
.sumblk table{width:100%}
.sumblk table th{width:128px}
/* Print-inclusion marker on a summary Job Info fact (build 'af'):
   a state marker only — a plain span, never a control. */
.jmark{color:var(--ok);font-weight:700;margin-left:6px}
.jmark.no{color:#98a2b3}
/* In-card section heading on a summary (build 'af'): styled like
   the page's section headings but NOT an h2 — the shell's section
   wrapper starts a new card at an h2, and a summary is one card. */
.sumsec{font-size:16px;font-weight:700;color:var(--frame);margin:14px 0 6px}
/* Facelift geometry (Jason 2026-10-25, build 'r'): ONE header zone for
   every document form — Company block (left), Customer/Address block
   (middle), form # + Date (right, the number larger and bold) — then
   the bar, then the form. Same margins, same spacing, same start on
   every tab and sub-tab, so hopping pages shows nothing jumping. */
.fhead{display:flex;flex-wrap:wrap;gap:8px 24px;align-items:flex-start;
  border-bottom:3px solid var(--frame);padding-bottom:8px;margin:0 0 8px}
.fhead .fh-cust{flex:1 1 240px;min-width:200px}
.fhead .fh-doc{margin-left:auto;text-align:right}
.fhead .fh-no{font-size:20px;font-weight:800;color:var(--frame);line-height:1.25;white-space:nowrap}
.fhead .fh-no input{font-size:18px;font-weight:800;color:var(--frame);text-align:right;width:150px;max-width:none}
.fhead .fh-no a{color:var(--frame);text-decoration:none}
.fhead .fh-date{margin-top:2px}
.fhead label{margin:0 0 1px}
/* Universal form law (Jason 2026-10-25, build 't'): the header zone
   is TWO rows on every document form — Row 1: Company (left), form #
   + Date (right); the bar (.fhead's bottom border); Row 2: Customer
   (left), Job Info box (right). The box carries the form's own Job
   Info popup values — the same fields the popup edits — a value or
   a dash, the printed box's convention. */
.fhead.fhead2{display:block}
.fhead .fh-row1{display:flex;flex-wrap:wrap;gap:8px 24px;align-items:flex-start}
.fhead .fh-row2{display:flex;flex-wrap:wrap;gap:8px 24px;align-items:flex-start;margin-top:10px}
.fhead .fh-cust2{flex:1 1 240px;min-width:200px}
.fhead .fh-job{border:1.5px solid var(--frame);padding:8px 10px;min-width:300px;flex:0 1 470px;margin-left:auto;height:122px;overflow:hidden}
.fhead .fh-job-h{font-weight:700;color:var(--frame);margin-bottom:3px}
.fhead .fh-job div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* Universal View row (Jason 2026-10-25, build 'r'): every form page
   ends with this row — one View button, bottom LEFT of the form,
   opening the page's own list popup. Nothing else renders below a
   form. */
.viewrow{display:flex;justify-content:flex-start;gap:8px;margin:8px 0 0}
.viewrow .vbtn{margin-left:0}
/* View popup footer (Jason 2026-10-25, build 'r'): when the popup is
   opened by a universal View button, its controls — Refresh, Print,
   Close — ride the BOTTOM RIGHT of the window; the title bar keeps
   the title and the Collapse control. Other popups keep the
   standing title-bar controls. (Build 'aa', 2026-10-26: the Full
   page link that rode the title bar is deleted — no popup carries
   it, for anyone.) */
.apop-foot{display:none}
.apop-win.viewpop .apop-foot{display:flex;justify-content:flex-end;gap:8px;
  background:var(--frame);padding:8px 12px;flex:0 0 auto}
.apop-foot button{background:#46586E;border:0;color:#fff;border-radius:4px;
  padding:3px 10px;font-size:12px;cursor:pointer;width:auto}
.apop-foot button:hover{background:#54687F}
.apop-win.viewpop .apop-bar [data-apop-reload],
.apop-win.viewpop .apop-bar [data-apop-print],
.apop-win.viewpop .apop-bar [data-apop-close]{display:none}
/* Billing settings (Jason 2026-10-25, build 'r'): five columns, one
   per option group, options straight down, each column scrollable —
   the settings box fits the screen instead of scrolling long. Panel
   checkbox grids lose their own inner cap; the column scrolls. */
.billgrid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;align-items:start}
.billcol{max-height:calc(100vh - 340px);min-height:140px;overflow-y:auto;padding-right:2px}
.billcol>fieldset{margin-top:0 !important}
.billcol>fieldset+fieldset{margin-top:10px !important}
.billcol .jb-grid{max-height:none !important;overflow:visible !important}
.brow{margin-bottom:2px}
.brow>div{margin-bottom:6px}
.dcard h2.cardtitle .vbtn{margin-left:auto}
.donebox{margin-top:10px;background:#f1f7f1;border:1px solid #cfdfcf;border-radius:8px;padding:10px 14px}
.donebox h3{margin:0 0 4px;font-size:13px;color:#2e6b34}
.donebox .dtodo{padding:4px 0;font-size:13.5px;color:#33402f;border-bottom:1px dashed #dde8dd}
.donebox .dtodo:last-child{border-bottom:0}
.donebox .tick{color:#2e7d32;font-weight:800;margin-right:6px}
.donebox .dmeta{color:var(--mute);font-size:12px;margin-left:8px}
.donebox .daudit{margin:8px 0 0;font-size:12.5px}
.dcard h2.cardtitle{margin:0 0 4px;font-size:17px;color:var(--frame);display:flex;align-items:center}
.dcard h2.cardtitle .full{margin-left:auto;font-size:12px;font-weight:400}
.dcard h3{margin:6px 0 2px;font-size:13px;color:var(--frame)}
.dcard .mstat{margin:2px 0 6px}
.dcard .mstat span{display:block;font-size:12px;color:var(--mute)}
.dcard .mstat b{font-size:26px;color:var(--frame);font-weight:800;letter-spacing:-.5px}
.rgroup{font-size:19px;color:var(--frame);margin:30px 0 6px;padding-top:12px;border-top:2px solid #d0d5dd}
.more{display:inline-block;background:none;border:0;color:var(--mute);
  font-size:12px;padding:4px 8px;cursor:pointer}
.more:hover{color:var(--frame);text-decoration:underline}
.apop{position:fixed;inset:0;background:rgba(27,42,74,.45);z-index:100;display:flex;
  align-items:center;justify-content:center;padding:24px}
.apop[hidden]{display:none}
.apop-win{background:var(--surface);border-radius:0;box-shadow:0 12px 40px rgba(0,0,0,.35);
  width:min(880px,94vw);height:min(640px,88vh);min-width:320px;min-height:240px;
  display:flex;flex-direction:column;resize:both;overflow:hidden}
.apop-bar{display:flex;align-items:center;gap:8px;background:var(--frame);color:#fff;
  padding:8px 12px;cursor:move;user-select:none;flex:0 0 auto}
.apop-bar .t{flex:1;font-weight:700;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.apop-bar button,.apop-bar a{background:#46586E;border:0;color:#fff;
  border-radius:4px;padding:3px 10px;font-size:12px;cursor:pointer;text-decoration:none;width:auto}
.apop-bar button:hover,.apop-bar a:hover{background:#54687F}
.apop-win iframe{flex:1;border:0;width:100%;background:var(--surface)}
/* Popup geometry (build 'aa', Jason 2026-10-26): BOTH popup shells
   collapse to their bar/heading and restore; Shell A keeps its
   resize grip + title-bar drag at every text size, and Shell B
   (.wpop — the inline working popups) gains the same three
   behaviors: collapse, CSS resize, drag by its heading. Collapse
   state is in-page only; it is never persisted. */
.apop-win.collapsed{height:auto !important;min-height:0}
.apop-win.collapsed iframe,.apop-win.collapsed .note-body,
.apop-win.collapsed .apop-foot{display:none !important}
.wpop{resize:both}
.wpop .wpop-h{cursor:move;user-select:none}
.wpop.collapsed{height:auto !important;min-height:0;max-height:none}
.wpop.collapsed>*:not(.wpop-h){display:none !important}
/* Notes doctrine (Jason 2026-10-24): a note shows only what fits its
   little field everywhere; the full text reads in a pop-up. Clickable
   note text is dotted-underlined; the pop-up body is plain readable
   text, wrapped and scrollable. */
.notepop{cursor:pointer;text-decoration:underline dotted}
.notepop-btn{margin-left:6px}
/* Summary line-note box (build 'ah', Jason 2026-10-28): a note
   longer than its summary cell opens in this temporary box,
   editable. The box carries exactly ONE control — Minimize; there
   is no Close and no Save (a note saves with the document, via the
   summary's Print door). Named exception to the standing popup
   furniture, by Jason's explicit design for this box. */
#sumnotebox{display:none;position:fixed;inset:0;z-index:95;background:rgba(20,28,38,.45);align-items:center;justify-content:center}
#sumnotebox.open{display:flex}
#sumnotebox .snb-card{background:#fff;border-radius:10px;box-shadow:0 18px 50px rgba(16,24,40,.35);width:min(560px,92vw);padding:16px;display:flex;flex-direction:column;gap:10px}
#sumnotebox textarea{width:100%;min-height:180px;font:inherit;font-size:15px;line-height:1.5;padding:10px;border:1px solid #c8d0da;border-radius:6px;resize:vertical}
#sumnotebox .snb-row{display:flex;justify-content:flex-end}
.note-body{display:none;padding:18px;white-space:pre-wrap;word-break:break-word;overflow:auto;flex:1;font-size:15px;line-height:1.55}
@media (max-width:900px){
  .dashgrid{grid-template-columns:1fr}
  .pbox-grid{grid-template-columns:minmax(0,1fr)}
  .dcard.today{grid-row:auto}
  .dashgrid>.pbox{grid-row:auto}
  .dcard.hidephone{display:none}}
@media (max-width:700px){
  .apop{padding:0}
  .apop-win{width:100%;height:100%;border-radius:0;resize:none}
  .apop-bar{cursor:default}
}
/* Text size shifts the responsive breakpoints the way browser zoom does
   (CSS zoom alone can't move them): large=1.15x, xlarge=1.3x. */
@media (max-width:736px){
  body.ts-large .row,.row3,.fgrid,.row4s,.row4s2,.row5s,.row4w,.row5s2{grid-template-columns:1fr}
  body.ts-large table{display:block;overflow-x:auto;-webkit-overflow-scrolling:touch;white-space:nowrap}
  body.ts-large .backup-bar input{width:100%}
  body.ts-large header{gap:6px 10px;padding:8px 10px}
  body.ts-large header nav.main{flex-wrap:nowrap;overflow-x:auto;max-width:100%;padding-bottom:4px}
  body.ts-large header nav.aside{margin-left:0}
  body.ts-large .mark{display:none}
}
@media (max-width:832px){
  body.ts-xlarge .row,.row3,.fgrid,.row4s,.row4s2,.row5s,.row4w,.row5s2{grid-template-columns:1fr}
  body.ts-xlarge table{display:block;overflow-x:auto;-webkit-overflow-scrolling:touch;white-space:nowrap}
  body.ts-xlarge .backup-bar input{width:100%}
  body.ts-xlarge header{gap:6px 10px;padding:8px 10px}
  body.ts-xlarge header nav.main{flex-wrap:nowrap;overflow-x:auto;max-width:100%;padding-bottom:4px}
  body.ts-xlarge header nav.aside{margin-left:0}
  body.ts-xlarge .mark{display:none}
}
/* Build 'aa' (2026-10-26): the text-size full-screen rules that
   stripped the audit popup's resize + drag at large/xlarge are
   REMOVED — the popup keeps its geometry controls at every text
   size. Only the <=700px small-screen rule above still makes the
   popup full-screen. */
@media (max-width:1035px){
  body.ts-large .dashgrid{grid-template-columns:1fr}
  body.ts-large .pbox-grid{grid-template-columns:minmax(0,1fr)}
  body.ts-large .dcard.today{grid-row:auto}
  body.ts-large .dashgrid>.pbox{grid-row:auto}
  body.ts-large .dcard.hidephone{display:none}
}
@media (max-width:1170px){
  body.ts-xlarge .dashgrid{grid-template-columns:1fr}
  body.ts-xlarge .pbox-grid{grid-template-columns:minmax(0,1fr)}
  body.ts-xlarge .dcard.today{grid-row:auto}
  body.ts-xlarge .dashgrid>.pbox{grid-row:auto}
  body.ts-xlarge .dcard.hidephone{display:none}
}
/* Global print (Jason 2026-10-24): every view prints clean — the
   chrome goes away (header, nav, tabs, buttons, action links, move
   grips, the popup overlay itself) and the data stays. Form values
   stay too: inputs are hidden only inside popup fragments (frag
   doc), where they are filter/entry chrome, never record data. */
@media print{
  header,nav.main,footer,.tabs,.btn,.actions,button,.pbox-move,.pbox-grip,.pbox-width,.dcard-ctl,.dcard-grip,#apop,.wpop,.lockbanner{display:none !important}
  .print-head{display:block !important;font-size:14px;font-weight:700;margin:0 0 10px;padding-bottom:6px;border-bottom:2px solid #222}
}
/* Locked banner (build 'al', Jason 2026-10-28): a form sitting
   locked says so — a red box at the top of the form, screen only
   (the print block above removes it from paper). _LOCK_JS stands
   it at the locked form's head. */
.lockbanner{border:2px solid #b00020;background:#fdecea;color:#b00020;font-weight:700;font-size:15px;padding:6px 12px;margin:0 0 10px;border-radius:6px;text-align:center}
/* Revised-to line (build 'al', Jason 2026-10-28): a voided
   original names its revision across its top — on its summary
   and on its printed document. It PRINTS (no print rule hides
   it): the reprint of an original states where its money went. */
.revto{font-weight:700;font-size:15px;margin:0 0 8px;text-align:center}
/* Printed-view header (Jason 2026-10-24): company · title · date,
   print-only — a printed view says what it is and when it printed. */
.print-head{display:none}
"""

"""FleetSheet views: core — page chrome, auth/session plumbing (desk PIN, yard devices), dashboard, setup, export/print handlers. Mixins: CoreViews."""

__all__ = ['page', 'tabs', 'tabs_reports', 'tabs_boards', 'weekly_tabs', 'tabs_admin', 'tabs_invoice', 'tabs_quotes', 'tabs_money', '_cstat', '_trigger_opts', 'opts', 'lan_urls', 'qr_data_uri', 'QR_UNAVAILABLE', '_nav_section', 'money_val', 'quote_expiry_panel', 'task_nudge', 'more_link', 'DASH_CAP', 'view_button', 'note_pop_html', 'NOTE_POPUP_JS', 'AUDIT_TABLE_JS', 'news_strip', 'combo_field', 'combo_opts', 'COMBO_JS', 'lookup_select', 'LOOKUP_SELECT_JS', 'capped_table', 'fmt_date', 'fmt_datetime', 'enabled_values', 'ENABLED_CORES', 'SETUP_FLOW', 'next_setup_step', 'setup_in_progress', 'setup_chain', 'setup_finished', 'setup_rerun', 'chain_advance', 'chain_banner', 'chain_banner_rerun', 'chain_banner_admin', 'chain_layout_current', 'chain_rerun_target', 'folder_field', 'US_STATES', 'state_field']

# How many rows a landing-page list shows before the quiet "+ N more" hint.
DASH_CAP = 5


def more_link(total, shown, audit_url, audit_title):
    """Quiet '+ N more' hint under a capped list; opens the audit popup.

    The audit views (/today/all, /money/*/audit, /assets/all, ...) stay complete —
    this never hides anything, it just keeps the working list short."""
    n = total - shown
    if n <= 0:
        return ""
    return (f"<button type='button' class='vbtn' data-audit='{html.escape(audit_url, quote=True)}' "
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
   option, submit its id; otherwise submit the free text via data-freetext.
   Issue 1 (2026-10-15): a typed near-match that is a UNIQUE prefix of one
   option also syncs that option's id — typing "Lafayette County" must not
   silently blank the tax location just because the full label carries
   " · 8.75% (LOC-1)". Ambiguous prefixes (two or more matches) sync
   nothing, same as before. */
document.querySelectorAll('input[data-combo]').forEach(function(inp){
  var dl = document.getElementById(inp.getAttribute('list'));
  if(!dl) return;
  function sync(){
    var t = inp.value.trim(), id = '', free = '';
    var prefix = [];
    Array.prototype.forEach.call(dl.options, function(o){
      if(o.value.trim() === t){ id = o.getAttribute('data-id') || ''; }
      else if(t && o.value.trim().toLowerCase().indexOf(t.toLowerCase()) === 0){ prefix.push(o); }
    });
    if(!id && prefix.length === 1){ id = prefix[0].getAttribute('data-id') || ''; }
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


def lookup_select(con, kind, name, current="", blank=False, label_map=None,
                  required=False, css="", extra="", vals=None, add_option=True):
    """A <select> for a lookups list with the global Other/-Add- rule
    (Issue 4, 2026-10-15): options from lookups(kind) + the record's
    current value even when off-list + Other + -Add-.

    Picking Other swaps in a text input pre-filled "Other" — the typed
    value submits as the field (record-level only, never added to the
    list). Picking -Add- swaps in a text input + Add button; Add POSTs to
    /setup/lookups/add (PIN-gated), and on success the new option joins
    every same-kind select on the page and is selected. LOOKUP_SELECT_JS
    (included in page()) drives the swap; without JS, Other submits as
    "Other" and -Add- degrades to the neutral default server-side.
    `label_map` translates stored legacy values (e.g. cert slugs) for
    display; `extra` carries raw select attributes (e.g. an id).
    `vals` lets a caller pass a curated subset (Spec 7: editors pass the
    operator-enabled set); the record's current value is still always
    shown when off-list (see below). `add_option=False` omits the
    "-Add-" entry in editor contexts — adding lives in Setup; "Other"
    (the one-off Custom blank) always remains."""
    vals = engine.lookups(con, kind) if vals is None else list(vals)
    cur = (current or "").strip()
    opts = []
    if blank:
        opts.append('<option value=""></option>')
    seen = set(vals)
    for v in vals:
        sel = " selected" if v == cur else ""
        opts.append(f"<option{sel}>{html.escape(v)}</option>")
    if "Other" not in seen:
        # Lists without an Other option still get one — it is the
        # type-over trigger for every covered list.
        sel = " selected" if cur == "Other" else ""
        opts.append(f"<option{sel}>Other</option>")
        seen.add("Other")
    if cur and cur not in seen:
        # Off-list current value (typed-over Other, legacy slug, or a
        # list option since removed): still display it, selected.
        lab = (label_map or {}).get(cur, cur)
        opts.append(
            f'<option value="{html.escape(cur, quote=True)}" selected>{html.escape(lab)}</option>')
    if add_option:
        opts.append('<option value="__add__">-Add-</option>')
    req = " required" if required else ""
    cls = f' class="{html.escape(css, quote=True)}"' if css else ""
    ex = f" {extra}" if extra else ""
    return (
        '<span class="lookup-wrap">'
        f'<select name="{html.escape(name, quote=True)}" data-lookup data-kind="{html.escape(kind, quote=True)}" '
        f'data-field="{html.escape(name, quote=True)}"{cls}{req}{ex}>{"".join(opts)}</select>'
        f'<input data-lookup-input type="text" hidden disabled maxlength="60"{cls}>'
        '<button type="button" data-lookup-add hidden>Add</button> '
        '<button type="button" data-lookup-list hidden>\u21a9 list</button>'
        '<span data-lookup-err class="err" hidden></span>'
        "</span>"
    )


LOOKUP_SELECT_JS = """
<script>
/* Lookup selects with the global Other/-Add- rule (Issue 4, 2026-10-15).
   Picking Other swaps in a text input pre-filled "Other" (typed value
   submits as the field, record-level only); picking -Add- swaps in a text
   input + Add button that POSTs the new option to /setup/lookups/add
   (PIN-gated) and, on success, adds it to every same-kind select on the
   page and selects it. Delegated: covers rows cloned by Add Item / Add
   PO Line. Without JS, Other submits as "Other" and -Add- degrades to
   the neutral default server-side. */
(function(){
  function wrapOf(el){ return el.closest('.lookup-wrap'); }
  function parts(wrap){
    return {
      sel: wrap.querySelector('select[data-lookup]'),
      inp: wrap.querySelector('[data-lookup-input]'),
      add: wrap.querySelector('[data-lookup-add]'),
      back: wrap.querySelector('[data-lookup-list]'),
      err: wrap.querySelector('[data-lookup-err]')
    };
  }
  function show(el, on){ if(el) el.hidden = !on; }
  function setMode(wrap, mode){
    var p = parts(wrap);
    if(!p.sel || !p.inp) return;
    if(mode === 'other'){
      if(p.inp.dataset.mode !== 'other'){ p.inp.value = 'Other'; }
      p.inp.dataset.mode = 'other';
      p.inp.name = p.sel.dataset.field;
      p.inp.required = p.sel.required;
      p.sel.hidden = true; p.sel.disabled = true;
      p.inp.hidden = false; p.inp.disabled = false;
      show(p.add, false); show(p.back, true);
    } else if(mode === 'add'){
      if(p.inp.dataset.mode !== 'add'){ p.inp.value = ''; }
      p.inp.dataset.mode = 'add';
      p.sel.dataset.prev = p.sel.value;
      p.inp.name = p.sel.dataset.field + '_new';
      p.inp.required = false;
      p.sel.hidden = true; p.sel.disabled = true;
      p.inp.hidden = false; p.inp.disabled = false;
      show(p.add, true); show(p.back, true);
    } else {
      p.inp.dataset.mode = 'list';
      p.inp.disabled = true; p.inp.hidden = true;
      p.sel.hidden = false; p.sel.disabled = false;
      show(p.add, false); show(p.back, false);
      if(p.err){ p.err.hidden = true; p.err.textContent = ''; }
    }
  }
  function syncFromSelect(sel){
    var wrap = wrapOf(sel);
    if(!wrap) return;
    if(sel.value === 'Other') setMode(wrap, 'other');
    else if(sel.value === '__add__') setMode(wrap, 'add');
    else setMode(wrap, 'list');
  }
  function doAdd(wrap){
    var p = parts(wrap);
    if(!p.sel || !p.inp) return Promise.resolve(false);
    var val = p.inp.value.trim();
    if(!val){
      if(p.err){ p.err.textContent = 'Type the new option first.'; p.err.hidden = false; }
      p.inp.focus();
      return Promise.resolve(false);
    }
    return fetch('/setup/lookups/add', {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: 'kind=' + encodeURIComponent(p.sel.dataset.kind) + '&value=' + encodeURIComponent(val)
    }).then(function(res){
      var ct = res.headers.get('content-type') || '';
      if(ct.indexOf('application/json') === -1) throw new Error('PIN locked — unlock and try again.');
      return res.json();
    }).then(function(data){
      if(!data || !data.ok) throw new Error((data && data.error) || 'Could not add it');
      // The new option joins every same-kind select on the page.
      document.querySelectorAll('select[data-lookup][data-kind="' + p.sel.dataset.kind + '"]').forEach(function(s){
        var exists = false;
        Array.prototype.forEach.call(s.options, function(o){ if(o.value === val || o.text === val) exists = true; });
        if(!exists){
          var opt = document.createElement('option');
          opt.text = val; opt.value = val;
          var addOpt = s.querySelector('option[value="__add__"]');
          if(addOpt) s.insertBefore(opt, addOpt); else s.appendChild(opt);
        }
      });
      p.sel.value = val;
      setMode(wrap, 'list');
      p.sel.dispatchEvent(new Event('change', {bubbles: true}));
      return true;
    }).catch(function(e){
      if(p.err){ p.err.textContent = e.message || 'Could not add it.'; p.err.hidden = false; }
      return false;
    });
  }
  document.addEventListener('change', function(e){
    var sel = e.target && e.target.closest ? e.target.closest('select[data-lookup]') : null;
    if(sel) syncFromSelect(sel);
  });
  document.addEventListener('click', function(e){
    var addBtn = e.target && e.target.closest ? e.target.closest('[data-lookup-add]') : null;
    if(addBtn){ var w = wrapOf(addBtn); if(w) doAdd(w); return; }
    var backBtn = e.target && e.target.closest ? e.target.closest('[data-lookup-list]') : null;
    if(backBtn){
      var w2 = wrapOf(backBtn); if(!w2) return;
      var p2 = parts(w2);
      if(p2.inp.dataset.mode === 'add' && p2.sel.dataset.prev) p2.sel.value = p2.sel.dataset.prev;
      setMode(w2, 'list');
    }
  });
  document.addEventListener('keydown', function(e){
    if(e.key !== 'Enter') return;
    var inp = e.target && e.target.closest ? e.target.closest('[data-lookup-input]') : null;
    if(inp && inp.dataset.mode === 'add'){
      e.preventDefault();
      var w = wrapOf(inp); if(w) doAdd(w);
    }
  });
  document.addEventListener('submit', function(e){
    var form = e.target;
    if(!form || !form.querySelector) return;
    if(form.dataset.lookupSubmitting){ delete form.dataset.lookupSubmitting; return; }
    var pending = [];
    form.querySelectorAll('select[data-lookup]').forEach(function(sel){
      var wrap = wrapOf(sel);
      if(!wrap) return;
      var p = parts(wrap);
      if(p.inp && p.inp.dataset.mode === 'add' && !p.inp.disabled) pending.push(wrap);
    });
    if(pending.length){
      e.preventDefault();
      (function next(i){
        if(i >= pending.length){
          form.dataset.lookupSubmitting = '1';
          if(form.requestSubmit) form.requestSubmit(); else form.submit();
          return;
        }
        doAdd(pending[i]).then(function(ok){
          if(ok) next(i + 1);
          // On failure the error shows and the form stays put.
        });
      })(0);
    }
  });
  // Init: records already holding "Other" render in type-over mode.
  document.querySelectorAll('select[data-lookup]').forEach(function(sel){ syncFromSelect(sel); });
})();
</script>
"""


US_STATES = ("AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
             "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
             "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
             "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
             "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI",
             "WY")


def state_field(name, value="", extra=""):
    """A state entry, list-plus-custom (Batch 3 #4): a text input with
    a datalist of US state abbreviations. The datalist only suggests —
    any custom value types over and saves exactly as entered. One
    helper for every state input in the app (company, customer, site,
    customer location). `extra` carries the caller's own attributes
    (id, class, maxlength) untouched."""
    dl_id = "fs-states-" + "".join(
        ch if ch.isalnum() else "-" for ch in name)
    opts = "".join(f'<option value="{s}"></option>' for s in US_STATES)
    ex = f" {extra}" if extra else ""
    return (f'<input name="{html.escape(name, quote=True)}" '
            f'list="{dl_id}" value="{html.escape(value or "", quote=True)}" '
            f'autocomplete="off"{ex}>'
            f'<datalist id="{dl_id}">{opts}</datalist>')


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
      <button data-apop-collapse>Collapse</button>
      <button data-apop-reload>Refresh</button>
      <button data-apop-print>Print</button>
      <button data-apop-close>Close</button>
    </div>
    <iframe title="audit"></iframe>
    <div class="note-body" role="document"></div>
    <div class="apop-foot">
      <button data-apop-reload>Refresh</button>
      <button data-apop-print>Print</button>
      <button data-apop-close>Close</button>
    </div>
  </div>
</div>
"""

DASH_RESIZE_JS = """
<script>
(function(){
  /* Today cards: drag the bottom grip to stretch the card, revealing the
     extra list rows (items 6-10, rendered but hidden). Persists per card,
     per layout slot (Jason 2026-10-24: Main/Alternate — Main inherits
     the pre-slot key on first read). */
  function layoutSlot(){ try { return localStorage.getItem('fs-layout-slot') === 'Alternate' ? 'Alternate' : 'Main'; } catch(e){ return 'Main'; } }
  var SLOT = layoutSlot();
  var KEY = 'dcard-size:' + SLOT + ':' + location.pathname;
  var state = {};
  var raw = null;
  try { raw = localStorage.getItem(KEY); } catch(e){}
  if (raw) { try { state = JSON.parse(raw); } catch(e){ state = {}; } }
  // Migration only: Main inherits the pre-slot key. Alternate starts
  // from natural sizes, never from Main's.
  else if (SLOT === 'Main') { try { state = JSON.parse(localStorage.getItem('dcard-size:' + location.pathname) || '{}'); } catch(e){ state = {}; } }
  else { state = {}; }
  if (!state) state = {};
  function persist(){ try { localStorage.setItem(KEY, JSON.stringify(state)); } catch(e){} }
  document.querySelectorAll('.dashgrid .dcard').forEach(function(card){
    var h = card.querySelector('h2, h3');
    // Key on the heading text WITHOUT the DCARD_JS controls (grip/arrows
    // live in .dcard-ctl inside the heading). Without the strip, the key
    // would change with script order and orphan saved sizes.
    var title = 'card';
    if (h) {
      var probe = h.cloneNode(true);
      var ctl = probe.querySelector('.dcard-ctl');
      if (ctl) ctl.remove();
      title = probe.textContent.trim().slice(0, 40);
    }
    var st = state[title] || {};
    if (st.expanded) card.classList.add('expanded');
    if (st.minH) { card.style.minHeight = st.minH + 'px'; card.style.flex = '0 0 auto'; }
    var grip = card.querySelector('.card-resize');
    if (!grip) return;
    grip.addEventListener('pointerdown', function(e){
      e.preventDefault();
      // 2026-10-15: .dcard{flex:1 1 auto} refills a dragged card to
      // its column share, so dragging up never shrank it. Opt out of
      // the fill while sizing; the explicit minHeight owns the height.
      card.style.flex = '0 0 auto';
      var startY = e.clientY, startH = card.offsetHeight;
      var was = card.classList.contains('expanded');
      function move(ev){
        var nh = Math.max(60, startH + (ev.clientY - startY));
        card.style.minHeight = nh + 'px';
        var dy = ev.clientY - startY;
        if (dy > 12) card.classList.add('expanded');
        else if (dy < -12) card.classList.remove('expanded');
        else card.classList.toggle('expanded', was);
      }
      function up(){
        document.removeEventListener('pointermove', move);
        document.removeEventListener('pointerup', up);
        var expanded = card.classList.contains('expanded');
        if (!expanded) { card.style.minHeight = ''; card.style.flex = ''; }
        state[title] = { minH: expanded ? Math.round(card.offsetHeight) : 0, expanded: expanded };
        persist();
      }
      document.addEventListener('pointermove', move);
      document.addEventListener('pointerup', up);
    });
  });
})();
</script>
"""

PBOX_JS = """
<script>
(function(){
  // Page boxes: collapsible, under the layout lock (Administration
  // page, Page Layout card), one lock per layout slot. Unlocked,
  // boxes drag to reorder and flip full/half width; locked, the
  // layout freezes.
  // Everything is fenced: boxes stay in a 2-col grid (1 col when narrow),
  // so they can never overlap or slide offscreen. Persisted per-page.
  // Layout slots (Jason 2026-10-24): Main (the default) and Alternate
  // (for another user). Each slot saves its own arrangement and locks
  // on its own. Main inherits the pre-slot key on first read, so the
  // arrangement already on the desk carries over as Main.
  function layoutSlot(){ try { return localStorage.getItem('fs-layout-slot') === 'Alternate' ? 'Alternate' : 'Main'; } catch(e){ return 'Main'; } }
  var SLOT = layoutSlot();
  var KEY = 'pbox:' + SLOT + ':' + location.pathname + location.search;
  var state = {};
  var raw = null;
  try { raw = localStorage.getItem(KEY); } catch(e){}
  if (raw) { try { state = JSON.parse(raw); } catch(e){ state = {}; } }
  // Migration only: Main inherits the pre-slot key. Alternate starts
  // from the factory order, never from Main's arrangement.
  else if (SLOT === 'Main') { try { state = JSON.parse(localStorage.getItem('pbox:' + location.pathname + location.search) || '{}'); } catch(e){ state = {}; } }
  else { state = {}; }
  if (!state) state = {};
  function persist(){ try { localStorage.setItem(KEY, JSON.stringify(state)); } catch(e){} }
  function locked(){
    // Per-slot lock; the pre-slot global key is Main's fallback.
    try {
      var v = localStorage.getItem('fs-layout-locked:' + SLOT);
      if (v !== null) return v !== '0';
      return localStorage.getItem('fs-layout-locked') !== '0';
    } catch(e){ return true; }
  }
  // Slot switch (Page Layout card): saves the choice and reloads so
  // every layout script re-reads under the new slot. Defined up here
  // so it exists even on pages with no boxes.
  window.FSLayoutSlotSet = function(s){
    try { localStorage.setItem('fs-layout-slot', s === 'Alternate' ? 'Alternate' : 'Main'); } catch(e){}
    location.reload();
  };
  // Collapsed-headers lock (Jason 2026-10-21): a DEDICATED switch in
  // Administration (Page Layout card), separate from the
  // layout lock. It freezes/unfreezes the collapse arrangement.
  // Factory default UNLOCKED: the double-click gesture works and
  // choices save. LOCKED: loads render the saved arrangement exactly
  // and the gesture is inert. It never shows/hides anything itself.
  function collapseLocked(){ try { return localStorage.getItem('fs-collapse-locked') === '1'; } catch(e){ return false; } }
  // First-ever view (Jason 2026-10-21): the first time this page is
  // opened under this regime, every box renders expanded. Collapse
  // state saved before the regime existed (older builds on the same
  // origin — the poisoned check browser) is not the customer's
  // arrangement: it is cleared here, once, and the page is marked
  // seen. From then on, his own choices rule.
  if (!state.seen) {
    state.seen = 1;
    if (state.collapsed) delete state.collapsed;
    persist();
  }
  var main = document.querySelector('main');
  if (!main) return;
  var hasDash = !!document.querySelector('.dashgrid');
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
    // Popup containers are never section boxes (build 'aa', Jason
    // 2026-10-26): a hidden working popup (.wpop, or any fixed
    // overlay div) standing among a page's sections used to be
    // wrapped as its own .pbox, and the box rendered as an EMPTY
    // horizontal strip on the page — the summary pages carried one
    // strip per working popup. Skip them: a popup is not a section,
    // and the sections around it close up without it.
    if ((el.classList && el.classList.contains('wpop')) ||
        (el.style && el.style.position === 'fixed')) {
      cur = null; curParent = null; return;
    }
    if (el.classList && el.classList.contains('pbox')) {
      // Dashboard columns (dashgrid): NOT boxes. The three column
      // containers are glue, and the CARDS inside them are the movable
      // units (DCARD_JS owns them). Registering the columns here would
      // put per-column controls on them and move whole columns (the
      // 2026-10-13 Today bug: Compliance/task/notes had no controls,
      // and ↓ on Assets moved Compliance with it).
      if (c.pkey === 'dashgrid') { cur = null; curParent = null; return; }
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
  // Layout lock (Jason 2026-10-18; per-slot 2026-10-24): the switch on
  // the Administration page's Page Layout card — the header carries
  // nav and actions only. Default locked; 'fs-layout-locked:<slot>'
  // = '0' means unlocked (the pre-slot global key is Main's fallback).
  window.FSLayoutToggle = function(){
    var now = locked();
    try { localStorage.setItem('fs-layout-locked:' + SLOT, now ? '0' : '1'); } catch(e){}
    applyLock();
    Array.prototype.forEach.call(document.querySelectorAll('[data-layout-state]'),
      function(el){ el.textContent = locked() ? 'Locked' : 'Unlocked'; });
    return locked();
  };
  // Collapsed-headers switch (Jason 2026-10-21), wired to the Page
  // Layout card in Administration. It only freezes/unfreezes: saved
  // collapse state is NEVER cleared or overridden here, so the
  // unlock -> adjust one thing -> re-lock flow keeps the rest of the
  // arrangement exactly as it was.
  window.FSCollapseToggle = function(){
    var nowLocked = !collapseLocked();
    try { localStorage.setItem('fs-collapse-locked', nowLocked ? '1' : '0'); } catch(e){}
    Array.prototype.forEach.call(document.querySelectorAll('[data-collapse-state]'),
      function(el){ el.textContent = nowLocked ? 'Locked' : 'Unlocked'; });
    return nowLocked;
  };
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
  boxes.forEach(function(box){
    var h = box.querySelector('h2, h3');
    if (!h) return;
    var title = box.dataset.title;
    // Collapse via double-click on the heading (Jason 2026-10-06): no
    // toggle button — the heading itself is the control. While
    // collapsed headers are locked, the gesture is inert — the
    // arrangement is frozen (Jason 2026-10-21).
    function toggleCollapse(){
      if (collapseLocked()) return;
      var c = state.collapsed || {};
      c[title] = !c[title];
      state.collapsed = c;
      persist();
      applyCollapse(box, c[title]);
    }
    // The saved arrangement rules (Jason 2026-10-21): what the
    // operator collapsed stays collapsed, what he left open stays
    // open. The first-ever view was already normalized above — the
    // pre-regime state is gone and the marker is set — so nothing
    // inherited can hide a box here. (The operator once found the
    // Compliance upload form only by accidentally double-clicking
    // its heading: state from an older build had it hidden.)
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
    h.title = 'Collapse / expand';
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
    // Dashboard cards (server-pre-wrapped): the box's direct child is the
    // whole section.dcard, which CONTAINS the heading — so the guard above
    // hides nothing and double-click looks dead. Descend into each card
    // and hide its non-heading children instead. (On Today, dashgrid
    // columns are NOT pbox boxes — DCARD_JS owns per-card collapse there,
    // so a second card in the same column never folds away with the first.)
    if (box.querySelector('section.dcard')) {
      Array.prototype.forEach.call(box.querySelectorAll('section.dcard'), function(card){
        Array.prototype.forEach.call(card.children, function(el){
          if (el !== hh && !el.contains(hh)) el.style.display = collapsed ? 'none' : '';
        });
      });
    }
  }
})();
</script>
"""

DCARD_JS = """
<script>
(function(){
  // Today dashboard cards: each dcard is its own movable unit. The three
  // .dashgrid columns are glue (they keep a lower card stuck tight under
  // the one above it — the fix for Compliance hanging low); cards move
  // WITHIN a column (↑ ↓, drag) or BETWEEN columns (← →, drag).
  // Per-card collapse via double-click on the card heading.
  // Persisted per card under a NEW key (dcard:...). Old pbox-level state
  // (titles Today/Billing/Assets) is never read for layout or collapse,
  // so stale laptop state can't lose or duplicate cards. The lock itself
  // is the current slot's layout lock, shared with PBOX_JS.
  var grid = document.querySelector('.dashgrid');
  if (!grid) return;
  // Layout slots (Jason 2026-10-24): the same Main/Alternate slots
  // PBOX_JS reads — card order, collapse, and sizes follow the slot.
  // Main inherits the pre-slot keys on first read.
  function layoutSlot(){ try { return localStorage.getItem('fs-layout-slot') === 'Alternate' ? 'Alternate' : 'Main'; } catch(e){ return 'Main'; } }
  var SLOT = layoutSlot();
  var KEY = 'dcard:' + SLOT + ':' + location.pathname + location.search;
  var state = {};
  var raw = null;
  try { raw = localStorage.getItem(KEY); } catch(e){}
  if (raw) { try { state = JSON.parse(raw); } catch(e){ state = {}; } }
  // Migration only: Main inherits the pre-slot key. Alternate starts
  // from the factory arrangement, never from Main's.
  else if (SLOT === 'Main') { try { state = JSON.parse(localStorage.getItem('dcard:' + location.pathname + location.search) || '{}'); } catch(e){ state = {}; } }
  else { state = {}; }
  if (!state) state = {};
  function persist(){ try { localStorage.setItem(KEY, JSON.stringify(state)); } catch(e){} }
  function locked(){
    try {
      var v = localStorage.getItem('fs-layout-locked:' + SLOT);
      if (v !== null) return v !== '0';
      return localStorage.getItem('fs-layout-locked') !== '0';
    }
    catch(e){ return true; }
  }
  // Collapsed-headers lock: same dedicated switch PBOX_JS reads
  // (Administration page, Page Layout card). It freezes the
  // arrangement; factory default UNLOCKED (gesture works).
  function collapseLocked(){
    try { return localStorage.getItem('fs-collapse-locked') === '1'; }
    catch(e){ return false; }
  }
  // First-ever view (Jason 2026-10-21): same rule as PBOX_JS — on
  // this page's first open under the regime, pre-regime collapse
  // state is cleared once and the page is marked seen; after that
  // the operator's own arrangement rules.
  if (!state.seen) {
    state.seen = 1;
    if (state.collapsed) delete state.collapsed;
    persist();
  }
  function columns(){
    return Array.prototype.slice.call(grid.querySelectorAll(':scope > .pbox'));
  }
  function colOf(card){
    var cc = card.closest('.card-col');
    return cc || card.parentNode;
  }
  function colPbox(card){
    var cc = card.closest('.card-col');
    return cc ? cc.parentNode : card.parentNode;
  }
  function cardsIn(col){
    return Array.prototype.filter.call(col.children, function(el){
      return el.classList && el.classList.contains('dcard');
    });
  }
  function allCards(){
    var out = [];
    columns().forEach(function(pbox){
      var cc = pbox.querySelector('.card-col') || pbox;
      out = out.concat(cardsIn(cc));
    });
    return out;
  }
  function cardId(card){ return card.dataset.card || ''; }
  function saveLayout(){
    state.layout = columns().map(function(pbox){
      var cc = pbox.querySelector('.card-col') || pbox;
      return cardsIn(cc).map(cardId);
    });
    persist();
  }
  function restoreLayout(){
    var layout = state.layout;
    if (!Array.isArray(layout) || !layout.length) return;
    var cols = columns();
    var byId = {};
    allCards().forEach(function(card){ byId[cardId(card)] = card; });
    var placed = {};
    layout.forEach(function(ids, ci){
      if (ci >= cols.length) return;
      var cc = cols[ci].querySelector('.card-col') || cols[ci];
      (ids || []).forEach(function(id){
        var card = byId[id];
        if (card && !placed[id]) { cc.appendChild(card); placed[id] = true; }
      });
    });
    // Cards missing from saved state (new/renamed) stay where the server
    // put them; saved ids matching no card are ignored. Nothing is
    // dropped or duplicated.
  }
  restoreLayout();
  function applyCollapse(card, collapsed){
    var h = card.querySelector('h2, h3');
    Array.prototype.forEach.call(card.children, function(el){
      if (el === h || (h && el.contains(h))) return;
      el.style.display = collapsed ? 'none' : '';
    });
    // A stretched card keeps its minHeight while collapsed or it shows
    // as a tall blank box. Park it, restore on expand.
    if (collapsed) {
      if (!card.dataset.savedMinH) card.dataset.savedMinH = card.style.minHeight || '';
      card.style.minHeight = '';
    } else if (card.dataset.savedMinH !== undefined) {
      card.style.minHeight = card.dataset.savedMinH;
      delete card.dataset.savedMinH;
    }
    // 2026-10-15: .dcard{flex:1 1 auto} in a flex column regrows a
    // collapsed card to its share of the column — the card looked
    // un-collapsed (heading + blank box). Opt out of the fill while
    // collapsed so the card shrinks to just its heading. On expand,
    // keep the opt-out only if the card still carries an explicit
    // minHeight (a stretched card); a natural card goes back to fill.
    // (DCARD_JS runs after DASH_RESIZE_JS, so a blind flex='' here
    // would clobber a restored stretched size.)
    card.style.flex = (collapsed || card.style.minHeight) ? '0 0 auto' : '';
    card.classList.toggle('dcard-collapsed', !!collapsed);
  }
  function toggleCollapse(card){
    if (collapseLocked()) return; // locked: arrangement frozen
    var c = state.collapsed || {};
    var id = cardId(card);
    c[id] = !c[id];
    state.collapsed = c;
    persist();
    applyCollapse(card, c[id]);
  }
  function moveWithin(card, dir){
    var col = colOf(card);
    var sibs = cardsIn(col);
    var i = sibs.indexOf(card);
    var j = i + dir;
    if (j < 0 || j >= sibs.length) return;
    if (dir < 0) col.insertBefore(card, sibs[j]);
    else col.insertBefore(card, sibs[j].nextSibling);
    saveLayout();
  }
  function moveAcross(card, dir){
    var cols = columns();
    var i = cols.indexOf(colPbox(card));
    var j = i + dir;
    if (j < 0 || j >= cols.length) return;
    var target = cols[j].querySelector('.card-col') || cols[j];
    // Moved cards land at the TOP of the target column (2026-10-14):
    // appending put them just below whatever was there, so a card
    // bumped into a column always hung low.
    target.insertBefore(card, target.firstChild);
    saveLayout();
  }
  function dragId(e){
    var raw = '';
    try { raw = e.dataTransfer.getData('text/plain') || ''; } catch(err){}
    return raw.indexOf('dcard:') === 0 ? raw.slice(6) : '';
  }
  function findCard(id){
    var found = null;
    allCards().forEach(function(c){ if (cardId(c) === id) found = c; });
    return found;
  }
  allCards().forEach(function(card){
    var h = card.querySelector('h2, h3');
    if (!h) return;
    var id = cardId(card);
    // The saved arrangement rules (Jason 2026-10-21), same as
    // PBOX_JS; the first-ever view was normalized above.
    applyCollapse(card, (state.collapsed || {})[id]);
    // One control set per card: grip + ↑ ↓ (within column) + ← → (column).
    var ctl = document.createElement('span');
    ctl.className = 'dcard-ctl';
    function mkBtn(text, title, fn){
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'dcard-move'; b.textContent = text;
      b.title = title;
      b.onclick = function(ev){ ev.stopPropagation(); fn(); };
      return b;
    }
    var grip = document.createElement('span');
    grip.className = 'dcard-grip'; grip.textContent = '⋮⋮';
    grip.title = 'Drag to move this card';
    ctl.appendChild(grip);
    ctl.appendChild(mkBtn('↑', 'Move this card up', function(){ moveWithin(card, -1); }));
    ctl.appendChild(mkBtn('↓', 'Move this card down', function(){ moveWithin(card, 1); }));
    ctl.appendChild(mkBtn('←', 'Move this card to the column on the left', function(){ moveAcross(card, -1); }));
    ctl.appendChild(mkBtn('→', 'Move this card to the column on the right', function(){ moveAcross(card, 1); }));
    h.insertBefore(ctl, h.firstChild);
    h.addEventListener('dblclick', function(e){
      if (e.target.closest('button')) return;
      toggleCollapse(card);
    });
    h.title = 'Collapse / expand';
    card.draggable = !locked();
    card.addEventListener('dragstart', function(e){
      if (locked()) { e.preventDefault(); return; }
      e.dataTransfer.setData('text/plain', 'dcard:' + id);
      e.dataTransfer.effectAllowed = 'move';
      card.classList.add('dragging');
    });
    card.addEventListener('dragend', function(){ card.classList.remove('dragging'); });
    card.addEventListener('dragenter', function(e){
      if (!locked()) { e.preventDefault(); card.classList.add('drop-target'); }
    });
    card.addEventListener('dragleave', function(){ card.classList.remove('drop-target'); });
    card.addEventListener('dragover', function(e){
      if (!locked()) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; }
    });
    card.addEventListener('drop', function(e){
      if (locked()) return;
      e.preventDefault();
      e.stopPropagation();
      card.classList.remove('drop-target');
      var src = findCard(dragId(e));
      if (!src || src === card) return;
      var col = colOf(card);
      var r = card.getBoundingClientRect();
      if ((e.clientY - r.top) > r.height / 2) col.insertBefore(src, card.nextSibling);
      else col.insertBefore(src, card);
      saveLayout();
    });
  });
  // Column-gap drops: releasing over a gap (not on a card) appends the
  // card to that column instead of snapping it back.
  columns().forEach(function(pbox){
    var cc = pbox.querySelector('.card-col') || pbox;
    cc.addEventListener('dragover', function(e){
      if (!locked()) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; }
    });
    cc.addEventListener('drop', function(e){
      if (locked()) return;
      e.preventDefault();
      var src = findCard(dragId(e));
      if (!src) return;
      var el = document.elementFromPoint(e.clientX, e.clientY);
      var target = (el && el.closest) ? el.closest('.dcard') : null;
      if (target && target !== src && colOf(target) === cc) {
        var r = target.getBoundingClientRect();
        if ((e.clientY - r.top) > r.height / 2) cc.insertBefore(src, target.nextSibling);
        else cc.insertBefore(src, target);
      } else {
        cc.appendChild(src);
      }
      saveLayout();
    });
  });
  function applyCardLock(){
    var isLocked = locked();
    allCards().forEach(function(card){
      card.draggable = !isLocked;
      var h = card.querySelector('h2, h3');
      if (!h) return;
      h.style.cursor = isLocked ? '' : 'move';
      var ctl = h.querySelector('.dcard-ctl');
      if (ctl) ctl.style.display = isLocked ? 'none' : '';
    });
  }
  applyCardLock();
  // The PBOX_JS lock button (same per-page lock) toggles our controls too.
  // PBOX_JS runs first, so its button exists; its listener fires before
  // ours and the fresh localStorage state is read here.
  var lockBtn = document.querySelector('.pbox-lock');
  if (lockBtn) lockBtn.addEventListener('click', function(){ applyCardLock(); });
})();
</script>
"""

AUDIT_POPUP_JS = """
<script>
function w0win(){ var w = document.getElementById('apop'); return w ? w.querySelector('.apop-win') : null; }
function openAudit(url, title){
  var w = document.getElementById('apop'); if(!w) return;
  w.querySelector('.t').textContent = title || 'Everything';
  // Batch 3 #7: the box loads the chrome-less fragment (?frag=1 — the
  // list only, no app header/nav), never the full page. (Build 'aa',
  // 2026-10-26: the Full page link that used to ride this bar is
  // deleted from the shell — no popup carries one, for anyone.)
  // Popup controls (Jason 2026-10-23): the fragment URL is kept as
  // the popup's identity (data-base) so Refresh re-fetches exactly
  // this popup's content from the server, in place.
  var f = w.querySelector('iframe');
  var base = url + (url.indexOf('?') >= 0 ? '&' : '?') + 'frag=1';
  f.setAttribute('data-base', base);
  f.src = base;
  w.hidden = false; document.body.style.overflow = 'hidden';
}
function refreshAudit(){
  var w = document.getElementById('apop'); if(!w) return;
  var f = w.querySelector('iframe');
  var base = f.getAttribute('data-base');
  if (!base) return;
  // Cache-busted re-fetch of the same fragment: a popup left open
  // all day comes current on demand. A record deleted meanwhile
  // renders the fragment's own empty/unknown state, not an error.
  f.src = base + '&_r=' + Date.now();
}
function closeAudit(){
  var w = document.getElementById('apop'); if(!w) return;
  var _win = w.querySelector('.apop-win'); if (_win) _win.classList.remove('viewpop');
  if (_win) _win.classList.remove('collapsed');
  var _cb = w.querySelector('[data-apop-collapse]'); if (_cb) _cb.textContent = 'Collapse';
  w.hidden = true; w.querySelector('iframe').src = 'about:blank';
  document.body.style.overflow = '';
  // Note pop-up shares this overlay: reset it too, so a closed note
  // never leaks into the next audit popup (and vice versa).
  var nb = w.querySelector('.note-body'); if (nb) nb.style.display = 'none';
  var f = w.querySelector('iframe'); if (f) f.style.display = '';
  var pp = w.querySelector('[data-apop-print]'); if (pp) pp.style.display = '';
}
// Popup geometry (build 'aa', Jason 2026-10-26): the audit window
// collapses to its title bar and expands back — one control on the
// bar, in-page state only, never persisted.
function collapseAudit(){
  var w = document.getElementById('apop'); if(!w) return;
  var _win = w.querySelector('.apop-win'); if(!_win) return;
  var on = _win.classList.toggle('collapsed');
  var _cb = w.querySelector('[data-apop-collapse]');
  if (_cb) _cb.textContent = on ? 'Expand' : 'Collapse';
}
// Print (Jason 2026-10-24): every view popup prints what it shows —
// the filtered, sorted fragment as it stands, via the iframe's own
// print. The fragment's print style drops the filter box and buttons;
// the parent page never prints.
function printAudit(){
  var w = document.getElementById('apop'); if(!w) return;
  var f = w.querySelector('iframe'); if(!f || !f.contentWindow) return;
  try { f.contentWindow.focus(); f.contentWindow.print(); } catch(e){}
}
document.addEventListener('click', function(e){
  // Audit popup opens ONLY for elements carrying data-audit (the "+ N more"
  // buttons and the "View All" buttons). 2026-10-16: this used to match
  // '.more,.vbtn', so EVERY .vbtn click — including the ticker Filter
  // button and the filter form's own Save button — opened the popup with
  // a null URL and the default "Everything" title.
  var m = e.target.closest('[data-audit]');
  if (m) { openAudit(m.getAttribute('data-audit'), m.getAttribute('data-title'));
    // Universal View popups (Jason 2026-10-25, build 'r') carry their
    // controls at the window's bottom right — the .viewpop class
    // switches the footer bar on and the title-bar controls off.
    var _win = w0win(); if (_win) _win.classList.toggle('viewpop', !!m.getAttribute('data-viewpop'));
    return; }
  if (e.target.closest('[data-apop-collapse]')) { collapseAudit(); return; }
  if (e.target.closest('[data-apop-close]')) { closeAudit(); return; }
  var r = e.target.closest('[data-apop-reload]');
  if (r) { refreshAudit(); return; }
  var pr = e.target.closest('[data-apop-print]');
  if (pr) { printAudit(); return; }
  if (e.target.closest('.apop') && !e.target.closest('.apop-win')) { closeAudit(); }
});
document.addEventListener('keydown', function(e){ if (e.key === 'Escape') closeAudit(); });
// Popup controls (Jason 2026-10-23): every popup carries Refresh +
// Close. The Job Info popup holds live form fields, so its refresh
// re-fetches the host page from the server and copies the freshly
// rendered values for this popup's fields — same popup, same record,
// current server state; a file input cannot be re-set and is left.
function refreshJobInfo(pid){
  var dst = document.getElementById(pid); if (!dst) return;
  fetch(location.pathname + location.search, {credentials:'same-origin'})
    .then(function(r){ return r.text(); })
    .then(function(t){
      var doc = new DOMParser().parseFromString(t, 'text/html');
      var src = doc.getElementById(pid); if (!src) return;
      src.querySelectorAll('input[name], textarea[name], select[name]').forEach(function(s){
        if (s.type === 'file') return;
        var d = dst.querySelector('[name="' + s.name + '"]');
        if (!d) return;
        if (d.type === 'checkbox' || d.type === 'radio') d.checked = s.checked;
        else d.value = s.value;
      });
    }).catch(function(){});
}
// The ticker filter popover: refresh re-fetches its own panel from
// the server (the saved category set may have changed elsewhere);
// close is the explicit button, not just clicking away.
function refreshTickf(){
  var cur = document.getElementById('tickf'); if (!cur) return;
  var nxt = cur.querySelector('input[name=next]');
  var path = nxt ? nxt.value : location.pathname;
  fetch('/ticker/panel?frag=1&next=' + encodeURIComponent(path), {credentials:'same-origin'})
    .then(function(r){ return r.text(); })
    .then(function(t){
      var doc = new DOMParser().parseFromString(t, 'text/html');
      var src = doc.getElementById('tickf'); if (!src) return;
      src.style.display = 'block';
      cur.replaceWith(src);
    }).catch(function(){});
}
function closeTickf(){
  var cur = document.getElementById('tickf'); if (cur) cur.style.display = 'none';
}
// The petty-cash float popover: refresh re-reads the saved float
// (and the card showing it) from the server copy of this page.
function refreshFloatpop(){
  var pop = document.getElementById('floatpop'); if (!pop) return;
  fetch(location.pathname + location.search, {credentials:'same-origin'})
    .then(function(r){ return r.text(); })
    .then(function(t){
      var doc = new DOMParser().parseFromString(t, 'text/html');
      var src = doc.querySelector('#floatpop input[name=pc_float]');
      var dst = pop.querySelector('input[name=pc_float]');
      if (src && dst) dst.value = src.value;
    }).catch(function(){});
}
function closeFloatpop(){
  var pop = document.getElementById('floatpop'); if (pop) pop.style.display = 'none';
}
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
// Shell B — the inline working popups (.wpop: _pop_wrap popups, the
// Job Info popups, and their hand-built copies). Build 'aa' (Jason
// 2026-10-26): every one carries the universal furniture — Refresh,
// Print, Close — in that order in its heading, beside the Collapse
// control; the heading drags the popup, the box's corner grip
// resizes it (CSS resize on .wpop), and Collapse shrinks it to its
// heading. State is in-page only; nothing persists.
function wpopCollapse(pid, btn){
  var pop = document.getElementById(pid); if(!pop) return;
  var on = pop.classList.toggle('collapsed');
  if (btn) btn.textContent = on ? 'Expand' : 'Collapse';
}
function wpopPrint(){
  // The working popup's Print prints the host document/page — the
  // same print the host form or summary offers. Print CSS drops the
  // popup itself (and every button) from the sheet.
  window.print();
}
function wpopRefresh(pid){
  // Refresh the way the Job Info popup's refresh works: re-fetch the
  // host page from the server and stand this popup's freshly
  // rendered copy in place of the open one — same popup, same
  // record, current server state.
  var dst = document.getElementById(pid); if (!dst) return;
  fetch(location.pathname + location.search, {credentials:'same-origin'})
    .then(function(r){ return r.text(); })
    .then(function(t){
      var doc = new DOMParser().parseFromString(t, 'text/html');
      var src = doc.getElementById(pid); if (!src) return;
      src.style.display = 'block';
      if (dst.dataset.moved) {
        src.dataset.moved = '1';
        src.style.left = dst.style.left; src.style.top = dst.style.top;
        src.style.width = dst.style.width; src.style.height = dst.style.height;
        src.style.right = 'auto';
      }
      dst.replaceWith(src);
    }).catch(function(){});
}
(function(){
  // Drag a Shell B popup by its heading (buttons exempt), the same
  // gesture as the audit window's title-bar drag.
  var dragPop = null, sx = 0, sy = 0, ox = 0, oy = 0;
  document.addEventListener('pointerdown', function(e){
    var h = e.target.closest ? e.target.closest('.wpop-h') : null;
    if (!h) return;
    if (e.target.closest('button') || e.target.closest('a') ||
        e.target.closest('input') || e.target.closest('select')) return;
    var pop = h.closest('.wpop'); if (!pop) return;
    dragPop = pop; sx = e.clientX; sy = e.clientY;
    var r = pop.getBoundingClientRect(); ox = r.left; oy = r.top;
    pop.style.left = ox + 'px'; pop.style.top = oy + 'px';
    pop.style.right = 'auto'; pop.style.width = r.width + 'px';
    pop.style.margin = '0'; pop.dataset.moved = '1';
    try { h.setPointerCapture(e.pointerId); } catch (err) {}
  });
  document.addEventListener('pointermove', function(e){
    if (!dragPop) return;
    dragPop.style.left = Math.max(0, ox + e.clientX - sx) + 'px';
    dragPop.style.top = Math.max(0, oy + e.clientY - sy) + 'px';
  });
  document.addEventListener('pointerup', function(){ dragPop = null; });
  document.addEventListener('pointercancel', function(){ dragPop = null; });
})();
</script>
"""

NOTE_POPUP_JS = """
<script>
// Notes doctrine (Jason 2026-10-24): the little field shows what fits;
// the full text reads here, in a pop-up. Display spans carry the full
// text in data-notefull; input Read buttons pop the input's live value.
// Buttons stay hidden until the note actually runs long (>60 chars).
function openNote(text){
  var w = document.getElementById('apop'); if(!w) return;
  var _win = w.querySelector('.apop-win'); if (_win) _win.classList.remove('viewpop');
  w.querySelector('.t').textContent = 'Note';
  var f = w.querySelector('iframe'); f.style.display = 'none';
  var pp = w.querySelector('[data-apop-print]'); if (pp) pp.style.display = 'none';
  var nb = w.querySelector('.note-body'); nb.textContent = text || '';
  nb.style.display = 'block';
  w.hidden = false; document.body.style.overflow = 'hidden';
}
function injectNoteBtns(){
  // Every note input on the page gets a Read button after it (and a
  // 2000-char cap, matching the engine). The transport input gets the
  // button but no cap — its value is parsed back into haul_by +
  // haul_note on save, so capping it could cut a note mid-parse.
  document.querySelectorAll('input[name=note],input[name=notes],input[name=location_note],input[name=po_notes],input[name=reason],input[name=haul_by]').forEach(function(inp){
    if (inp.nextElementSibling && inp.nextElementSibling.classList.contains('notepop-btn')) return;
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'notepop-btn vbtn'; b.hidden = true;
    b.title = 'Read the full note'; b.textContent = 'Read';
    inp.insertAdjacentElement('afterend', b);
    if (inp.name !== 'haul_by' && (inp.maxLength < 0 || inp.maxLength > 2000)) inp.maxLength = 2000;
  });
}
function syncNoteBtns(){
  document.querySelectorAll('.notepop-btn').forEach(function(b){
    var inp = b.previousElementSibling;
    if (!inp || inp.tagName !== 'INPUT') {
      inp = b.parentElement.querySelector('input[name=note],input[name=notes],input[name=location_note],input[name=po_notes],input[name=haul_by]');
    }
    if (inp) { b._noteInput = inp; b.hidden = !(inp.value && inp.value.length > 60); }
  });
}
document.addEventListener('click', function(e){
  var d = e.target.closest('[data-notefull]');
  if (d) { openNote(d.getAttribute('data-notefull')); return; }
  var b = e.target.closest('.notepop-btn');
  if (b) {
    var inp = b._noteInput || b.previousElementSibling;
    if (inp && inp.value !== undefined) openNote(inp.value);
  }
});
document.addEventListener('input', function(e){
  if (e.target && e.target.tagName === 'INPUT') syncNoteBtns();
});
document.addEventListener('DOMContentLoaded', function(){ injectNoteBtns(); syncNoteBtns(); });
injectNoteBtns(); syncNoteBtns();
</script>
"""

SUM_NOTE_JS = r"""
<script>
/* Summary line-note box (build 'ah', Jason 2026-10-28). On a
   summary, a line note longer than its cell stands truncated and
   clickable; clicking it opens the temporary box (#sumnotebox)
   holding the full note in an editable field. The box carries
   exactly one control — Minimize. There is no Close and no Save:
   an edited note is held on the page and posts when the operator
   uses the summary's Print door — the record updates first, then
   the print renders — the way everything on a document saves with
   the document. (Named exception to the standing popup furniture,
   by Jason's explicit design for this box.) */
(function(){
  var dirty = {};   /* line_id -> {url, note} */
  var cur = null;   /* {cell, lineId, url, orig} */
  function esc(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
  function openBox(cell){
    var box = document.getElementById('sumnotebox');
    if(!box) return;
    cur = { cell: cell,
            lineId: cell.getAttribute('data-lineid'),
            url: cell.getAttribute('data-noteurl'),
            orig: cell.getAttribute('data-full') || '' };
    box.querySelector('textarea').value =
      (dirty[cur.lineId] ? dirty[cur.lineId].note : cur.orig);
    box.classList.add('open');
  }
  function minimize(){
    var box = document.getElementById('sumnotebox');
    if(!box || !cur) return;
    var v = box.querySelector('textarea').value;
    box.classList.remove('open');
    if(v !== cur.orig){ dirty[cur.lineId] = {url: cur.url, note: v}; }
    else { delete dirty[cur.lineId]; }
    var val = dirty[cur.lineId] ? dirty[cur.lineId].note : cur.orig;
    if(val.length <= 80){
      var t = document.createElement('span');
      t.textContent = val;
      cur.cell.replaceWith(t);
    } else {
      cur.cell.setAttribute('data-full', val);
      cur.cell.textContent = val.slice(0, 80) + '\u2026';
    }
    cur = null;
  }
  document.addEventListener('click', function(e){
    var cell = e.target.closest('.sumnote');
    if(cell){ openBox(cell); return; }
    if(e.target.closest('#sumnotebox .snb-min')){ minimize(); }
  });
  /* The Print door carries the note post: on a click on a print
     option (never the menu's own summary toggle), edited notes
     post first — capture phase, ahead of the option's own
     handler — then the chosen print action proceeds. */
  document.addEventListener('click', function(e){
    var opts = e.target.closest('.pmenu .popts');
    if(!opts) return;
    var keys = Object.keys(dirty);
    if(!keys.length) return;
    var a = e.target.closest('a');
    var btn = e.target.closest('button');
    if(!a && !btn) return;
    e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
    var seq = Promise.resolve();
    keys.forEach(function(k){
      var d = dirty[k];
      seq = seq.then(function(){
        return fetch(d.url, { method: 'POST',
          headers: {'Content-Type': 'application/x-www-form-urlencoded'},
          body: 'line_id=' + encodeURIComponent(k) +
                '&note=' + encodeURIComponent(d.note)
        }).catch(function(){});
      });
    });
    seq.then(function(){
      dirty = {};
      if(a && a.getAttribute('href')){
        window.open(a.getAttribute('href'), '_blank');
      } else if(btn && btn.hasAttribute('data-doc')){
        if(window.fsSaveLoc) window.fsSaveLoc(btn);
      } else if(btn){
        var oc = btn.getAttribute('onclick') || '';
        if(oc.indexOf('fsPrintScreen') >= 0){
          if(window.fsPrintScreen) window.fsPrintScreen();
        } else if(oc.indexOf('fsSavePage') >= 0){
          if(window.fsSavePage) window.fsSavePage(btn);
        } else {
          window.print();
        }
      }
    });
  }, true);
})();
</script>
"""

def money_val(v):
    """Format any value for a money <input>: always two decimals ('150.50')."""
    try:
        return f"{float(v or 0):.2f}"
    except (TypeError, ValueError):
        return "0.00"

# ------------------------------------------------------------- Spec 7
# Curation lives in Setup: the MASTER lists live in the lookups table
# (terms 21 / inv_uom 57 / inv_item 47, seeded in engine.seed_lookups,
# extended by add_lookup). Each book's ENABLED subset is a book option
# holding a JSON array of values. Editors show only the enabled set +
# the Custom blank ("Other"); Setup sees the full master list. When the
# option is absent, the factory-on core below applies. Item 6
# (2026-10-20): Setup can also DELETE a master entry (engine_core
# .delete_lookup — row removed plus a tombstone so the seed never
# resurrects it; stored records keep their strings verbatim) and
# RESTORE the factory list + factory-on set per kind.
ENABLED_OPTION_KEYS = {"terms": "enabled_terms",
                       "inv_uom": "enabled_inv_uom",
                       "inv_item": "enabled_inv_item",
                       "comp_doc": "enabled_comp_doc"}
ENABLED_CORES = {
    "terms": ["Due on Receipt", "Net 10", "Net 15", "Net 30", "Net 45",
              "Net 60"],
    "inv_uom": ["Each", "Hours", "Days", "Weeks", "Months", "Miles",
                "Loads", "Feet", "Yards", "Gallons", "Lot", "Pieces",
                "Sets", "Dozen", "Cases", "Boxes", "Pounds", "Tons",
                "Cubic Feet", "Cubic Yards", "Square Feet", "Trips",
                "Jobs", "Flat Fee"],
    "inv_item": ["Labor", "Parts", "Service", "Equipment Rental",
                 "Materials", "Delivery", "Pickup", "Freight", "Hauling",
                 "Mileage", "Fuel", "Fuel Surcharge", "Damage Waiver",
                 "Environmental Fee", "Setup", "Installation",
                 "Inspection", "Repair", "Maintenance", "Cleaning",
                 "Mobilization", "Demobilization", "Other"],
    # Compliance document types (laptop-pass fix round, 2026-10-20):
    # the factory-on set for the Upload Certificate picker — the
    # everyday certs a rental desk files. The full master list lives
    # in the seed pack (engine.seed_lookups); Setup -> Billing curates.
    "comp_doc": ["Load Test", "NDT", "Visual Inspection",
                 "Ultrasonic/Sonic Testing", "Hydrostatic Test",
                 "Calibration Certificate", "Certificate of Conformance",
                 "Relief Valve Test", "Inspection Report",
                 "DNV", "USCG", "UL", "Other"],
}


def enabled_values(con, kind):
    """The operator-enabled values for a curated lookup kind, in saved
    order. Absent/unreadable option -> the factory-on core. Values are
    user text, stored as a JSON array (never CSV).

    Item 6 (2026-10-20): the result is intersected with the master
    list, so a value deleted from the master can never dangle in the
    enabled set or reappear in a picker — even if a stored enabled
    JSON still names it, and even on the factory-core fallback path
    (deleting a core value before any billing save still prunes it).
    A master list emptied by deletion yields an empty enabled set."""
    key = ENABLED_OPTION_KEYS.get(kind)
    vals = None
    if key:
        raw = engine.get_option(con, key, "") or ""
        if raw:
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                parsed = None
            if isinstance(parsed, list):
                vals = [str(v) for v in parsed]
    if vals is None:
        vals = list(ENABLED_CORES.get(kind, []))
    try:
        master = set(engine.lookups(con, kind))
    except Exception:
        return vals
    return [v for v in vals if v in master]


def fmt_date(v, fallback=""):
    """Display format for a stored date (ITEM A): MM/DD/YYYY, zero-padded.

    Accepts ISO strings ('2026-10-05', optionally with a time tail),
    date/datetime objects, and sqlite values. Empty/missing returns
    `fallback`; an unparseable value is returned unchanged (legacy or
    placeholder text such as '—' stays visible rather than vanishing).
    Storage, inputs, URLs and exports never pass through here — display
    only."""
    if v is None:
        return fallback
    s = str(v).strip()
    if not s:
        return fallback
    try:
        d = date.fromisoformat(s[:10])
    except ValueError:
        return s
    return f"{d.month:02d}/{d.day:02d}/{d.year:04d}"


def fmt_datetime(v, fallback=""):
    """fmt_date plus the time-of-day when the value carries one
    ('2026-10-05 14:32:11' -> '10/05/2026 14:32')."""
    if v is None:
        return fallback
    s = str(v).strip()
    if not s:
        return fallback
    d = fmt_date(s, "")
    if not d or d == s:
        return s if s else fallback
    t = s[11:16] if len(s) >= 16 and s[10] in " T" else ""
    return f"{d} {t}" if t else d


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
      <b>Quote check:</b> quote {html.escape(qc['quote_no'])} expired {html.escape(qc['date_str'])}.
    </div>"""


# Desk text-size preference ("standard" | "large" | "xlarge"), set per
# request by app.py from the ui_text_size option. Rendered as CSS zoom on
# <html> so the whole px-based stylesheet scales exactly like browser zoom.
TEXT_SIZE = "standard"
# Kept at 60 for the pages that still inject window.FS_IDLE_MINS alongside
# FS_LOCK_MINS (the dead-server banner shell reads it; the banner text
# itself never claims idle). There is no server idle timeout anymore —
# Jason removed it 2026-10-20 as redundant with the desk idle lock below.
IDLE_MINS = 60
# Desk idle lock (Jason 2026-10-15): minutes of no interaction after which
# the desk locks and asks for the PIN again. 0 = Off (never lock). Default
# 60. The lock only clears the PIN session; it never stops or closes
# anything. Set per request by app.py; 0 when no PIN is set
# (nothing to lock).
LOCK_MINS = 60


def desk_lock_mins(con) -> int:
    """desk_lock_mins option, clamped: 0 = Off, else 5–1440. Default 60."""
    try:
        v = int(engine.get_option(con, "desk_lock_mins", "60") or 60)
    except (TypeError, ValueError):
        return 60
    if v <= 0:
        return 0
    return max(5, min(1440, v))
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


QR_UNAVAILABLE = ("QR unavailable on this machine — type the address below "
                  "into the device's browser.")


def qr_data_uri(url: str):
    """One shared QR helper (Issue 2, 2026-10-15): returns (uri, error).
    A missing segno package is LOUD — callers show the error text plus the
    plain URL, never a blank and never a bare traceback."""
    try:
        import segno
    except ImportError:
        return None, QR_UNAVAILABLE
    return segno.make(url, error="m").png_data_uri(scale=6), ""


TIPS_ON = True


# Which top-nav section a given path belongs to, for active-state highlighting.
_NAV_SECTIONS = [
    # Every desk page lights exactly one header tab — its own kind's
    # home (Jason 2026-10-24 sweep: no work page lights Reports or
    # nothing at all). Reports is read-only: print, sort, filter.
    ("dash", ("/today", "/done")),
    # Assets lives under Equipment (tweak round 2026-10-20): /assets and
    # /unit light the Equipment header tab; Assets is a right-justified
    # subheader on the Equipment pages, not a header tab of its own.
    ("ticketnew", ("/ticket/new", "/tickets", "/ticket/", "/wos", "/wo/",
                   "/quote", "/changes", "/sale", "/assets", "/unit")),
    ("acct", ("/invoice", "/pay", "/credit", "/cash", "/money")),
    ("compliance", ("/compliance", "/compack", "/ucompliance")),
    # Reports is read-only (Jason 2026-10-24): print, sort, filter —
    # no work done there. Rental tickets are work (charges, transport,
    # money, inline off-rent entry on the list), so the rental ticket
    # list and detail live under Equipment with the rest of ticket
    # work, not under Reports. (They previously lit Reports gold.)
    ("reports", ("/reports", "/export")),
    # Petty cash sits under Administration (Jason 2026-10-24): the
    # drawer is sealed from the money system, so its page and its
    # audit (/petty/audit) light Admin, never Billing.
    ("admin", ("/setup", "/customers", "/customer", "/sites", "/site",
               "/backup", "/health", "/petty")),
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


def note_pop_html(text, limit=80):
    """Notes doctrine (Jason 2026-10-24): a note shows only what fits
    its little field, everywhere; the full text reads in a pop-up.
    Short notes render plain. Long notes render truncated with a
    dotted underline — click opens the full text in the note pop-up.
    Newlines survive the attribute round-trip via &#10;."""
    t = text or ""
    if len(t) <= limit:
        return html.escape(t)
    full = html.escape(t, quote=True).replace("\n", "&#10;").replace("\r", "&#10;")
    return (f'<span class="notepop" data-notefull="{full}" '
            f'title="Click to read the full note">{html.escape(t[:limit])}…</span>')


"""The Read button is injected by NOTE_POPUP_JS after every note input
on page load (not hand-placed per form), so every note entry — present
and future — gets the pop-up affordance with no per-form edits. It
stays hidden until the note actually runs long (>60 chars), so short
notes carry no extra chrome."""


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
    // Dates compare CHRONOLOGICALLY (laptop-pass fix round, 2026-10-20):
    // displayed dates are MM/DD/YYYY (fmt_date) — parseFloat reads only
    // the month off those, so date columns sorted by month and shuffled
    // days/years. Normalize ISO (2026-11-15) and US (11/15/2026, with or
    // without a time tail) to a YYYYMMDD key and compare the keys. One
    // fix covers all audit tables.
    function dkey(s){
      var m = /^(\\d{4})-(\\d{2})-(\\d{2})/.exec(s);
      if (m) return m[1] + m[2] + m[3];
      m = /^(\\d{1,2})\\/(\\d{1,2})\\/(\\d{4})/.exec(s);
      if (m) return m[3] + ('0' + m[1]).slice(-2) + ('0' + m[2]).slice(-2);
      return null;
    }
    var xk = dkey(x), yk = dkey(y);
    var cmp = (xk && yk) ? xk.localeCompare(yk) : ((!isNaN(xn) && !isNaN(yn) && x !== '' && y !== '') ? xn - yn : x.localeCompare(y));
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


def _ack_forms(key, path, con=None, minutes=None):
    """Snooze (minutes) form riding the alert-ack machinery. One action
    only — Jason's final ruling (2026-10-15, restated 2026-10-18):
    Snooze temporarily hides the alert for N minutes — the
    bedside-alarm word, the behavior users already understand.
    No days-based dismiss, no Sleep: Sleep had no common
    understanding, and two "not now" controls read as clutter.
    The stepper moves ±15 minutes; the number is typeable
    (1–1440). The group sits right-justified inside .ack-right; the
    number input is narrow. (The strip-level Clear button was
    removed 2026-10-24 — Jason's 'm' look-see item 1: he never
    asked for it.)

    The standard default (2026-10-17): the stepper opens at the
    install's standard — option ack_snooze_minutes, factory 30 —
    and using it teaches the standard: the /alert/ack handler
    saves the value actually used (stepper posts carry
    src=stepper), so the control opens where the operator last
    left it, on every list."""
    if minutes is None:
        minutes = 30
        if con is not None:
            try:
                minutes = int(engine.get_option(con, "ack_snooze_minutes", "30") or 30)
            except (TypeError, ValueError):
                minutes = 30
    key = html.escape(key, quote=True)
    nxt = html.escape(path, quote=True)
    return (
        f"<span class='ack-right'>"
        f"<form method='post' action='/alert/ack' class='ackf'>"
        f"<input type='hidden' name='key' value='{key}'>"
        f"<input type='hidden' name='next' value='{nxt}'>"
        f"<input type='hidden' name='src' value='stepper'>"
        f"<span class='stepper'><button type='button' data-step='-15' title='15 minutes less'>&minus;</button>"
        f"<input type='number' name='minutes' value='{minutes}' min='1' max='1440' step='1' title='Snooze minutes'>m"
        f"<button type='button' data-step='15' title='15 minutes more'>+</button></span>"
        f"<button type='submit' name='action' value='snooze' title='Snooze this item'>Snooze</button></form>"
        f"</span>"
    )


def ticker_details(bits, n, key, cls="news"):
    """Wrap ticker rows in a <details> whose open state persists in
    localStorage (per page key, the 'ticker:<path>' family — the
    ticker's own store; it is not a page box, so it does not ride
    the pbox layout store). The save handler is FSTickerToggle,
    defined by the ticker's own trailing script (guarded, so it
    exists before any toggle event can dispatch). Build 'w': the
    previous inline ontoggle handler's quoting made it a syntax
    error in the browser — 'Unexpected identifier' — so no state
    was ever written and the strip forgot its state on every
    navigation. Saved values: '1' open, '0' closed; absent renders
    closed, the markup default. The restore script runs inline at
    first paint — no flash of collapsed-then-open."""
    k = html.escape(key, quote=True)
    return (f"<details class='news-wrap' style='margin:0' data-ticker-key='{k}' "
            f"ontoggle='FSTickerToggle(this)'>"
            f"<summary style='cursor:pointer;font-size:11px;color:#666;padding:1px 0;line-height:1.3'>"
            f"Alerts ({n})</summary>"
            f"<div class='{cls}'>{bits}</div></details>"
            f"<script>if(!window.FSTickerToggle){{window.FSTickerToggle=function(d){{"
            f"try{{localStorage.setItem('ticker:'+d.getAttribute('data-ticker-key'),"
            f"d.open?'1':'0');}}catch(e){{}}}}}}"
            f"try{{var d=document.currentScript.previousElementSibling;"
            f"if(d&&d.classList.contains('news-wrap')&&localStorage.getItem('ticker:{k}')==='1')"
            f"{{d.open=true;}}}}catch(e){{}}</script>")


_SNOOZE_LABELS = (
    ("dash:fitship:", "Shipping paper — Rental Ticket "),
    ("dash:nooff:", "Open-ended rental — Rental Ticket "),
    ("acct:disputed:", "Disputed invoice "),
    ("acct:pastdue:", "Past-due invoice "),
    ("acct:poexp:", "PO expiring — "),
    ("poack:", "PO missing expiry — "),
    ("aconf:", "Asset conflict — Rental Ticket "),
    ("aq:", "Accepted quote "),
    ("aoff:", "Off-rent return — Rental Ticket "),
    ("asole:", "Sole unit — asset "),
    ("comp:idle:", "Idle unit paper — asset "),
    ("comp:", "Compliance — "),
    ("money:late:", "Late invoice "),
    ("money:due:", "Invoice due today "),
    ("money:paid:", "Payment received — "),
    ("top:asset:", "Asset item — Rental Ticket "),
    ("mt:", "Money ticker — "),
)


def _snooze_label(key):
    """Human-readable label for a snoozed alert key. Keys are
    structured (prefix:id...); unknown shapes fall back to the raw
    key. money:paid keys still carry their date (a daily event), so
    the date is stripped from the label."""
    key = key or ""
    for prefix, label in _SNOOZE_LABELS:
        if key.startswith(prefix):
            rest = key[len(prefix):]
            if prefix == "money:paid:":
                # date:invoice:amount — drop the date, keep invoice:amount
                parts = rest.split(":", 1)
                if len(parts) == 2 and len(parts[0]) == 10 and parts[0][:2] == "20":
                    rest = parts[1]
            return label + rest
    return key


def _snooze_returns(until_ts):
    """When a snoozed alert comes back: today/tomorrow HH:MM, else M/D HH:MM."""
    lt = time.localtime(until_ts)
    hm = time.strftime("%H:%M", lt)
    d = date.fromtimestamp(until_ts)
    delta = (d - date.today()).days
    if delta == 0:
        return f"today {hm}"
    if delta == 1:
        return f"tomorrow {hm}"
    return f"{fmt_date(d)} {hm}"


def _snoozed_section(con):
    """Snoozed alerts: what's hidden and when it comes back, with an
    Unsnooze button per item. A collapsed <details> — one line when
    closed. Renders nothing when nothing is snoozed. Covers ticker /
    strip snoozes (alert_ack); sticky-note hides live on the notes
    themselves, not here."""
    try:
        rows = engine.list_snoozed(con)
    except Exception:
        return ""
    if not rows:
        return ""
    items = ""
    for key, until_ts in rows:
        items += (
            f"<div class='tapbox lv0'><span class='msg'>{html.escape(_snooze_label(key))} "
            f"<span class='mute'>— returns {html.escape(_snooze_returns(until_ts))}</span></span>"
            f"<form method='post' action='/alert/ack' class='ackf'>"
            f"<input type='hidden' name='key' value='{html.escape(key, quote=True)}'>"
            f"<input type='hidden' name='next' value='/'>"
            f"<button type='submit' name='action' value='unsnooze' title='Bring this alert back now'>Unsnooze</button></form>"
            f"</div>")
    return (
        f"<details class='news-wrap' style='margin:0'>"
        f"<summary style='cursor:pointer;font-size:12px;color:#666;padding:4px 0'>"
        f"Snoozed alerts ({len(rows)})</summary>"
        f"<div class='news'>{items}</div></details>")


def tickf_html(cats, path):
    """The ticker filter popover (Batch 3-era; popup controls Jason
    2026-10-23): saved category checkboxes + Save, and the shared
    popup controls — Refresh re-fetches this panel from the server
    (/ticker/panel), Close hides it. One builder, so the strip and
    the refresh endpoint serve identical markup."""
    boxes = ""
    for c in engine.TICKER_CATS:
        chk = " checked" if cats and c in cats else ""
        boxes += (f"<label><input type='checkbox' name='cat_{c}' value='1'{chk}> "
                  f"{html.escape(engine.CAT_LABELS[c])}</label>")
    return (
        f"<div id='tickf' class='tickfilter' style='display:none'>"
        f"<div style='display:flex;gap:6px;align-items:center;margin-bottom:6px'>"
        f"<b style='flex:1'>Filter</b>"
        f"<button type='button' onclick='refreshTickf()'>Refresh</button>"
        f"<button type='button' onclick='wpopPrint()'>Print</button>"
        f"<button type='button' onclick='closeTickf()'>Close</button></div>"
        f"<form method='post' action='/ticker/cats'>{boxes}"
        f"<input type='hidden' name='next' value='{html.escape(path, quote=True)}'>"
        f"<button type='submit' class='vbtn'>Save</button>"
        f"</form></div>")


def news_strip(alerts, path="/", top_items=None, alert_total=None, cats=None):
    """The Today ticker (build 'x': the only ticker in the build):
    at most five items show — the first boxed (boxed means this
    needs a decision from you), the next four as plain whole-row
    links.

    Every shown item's text is a link to the item itself, and every
    shown item carries the snooze stepper (laptop-pass fix round,
    2026-10-20 — the earlier verb/"Handle now" button and the
    mention rows' missing snooze are gone). Beyond the three shown,
    a quiet "+ N more". Handling or snoozing the hero lets the next
    one roll up. Calm line when there is nothing to tap about
    (dashboard only).

    `cats` is the enabled ticker-category set (from get_ticker_cats). When
    provided, a quiet Filter button at the strip's right end opens a small
    popover to choose which categories earn a slot. (2026-10-06)"""
    top_items = list(top_items or [])
    alerts = list(alerts or [])
    # One ordered pool — top_items first, then alerts, skipping any
    # alert whose key duplicates an item already in the pool — and
    # at most FIVE items show (build 'x': the one ticker captures
    # every pool, so the cut is five again; the single-spacing
    # squeeze allows it). Laptop-pass fix round (2026-10-20)
    # reshaped the rows: no verb button anywhere (the alert text is
    # the link), and every shown row carries the snooze stepper.
    #
    # One document, one row (build 'x'): the top-of-day hero and an
    # alert tap can name the SAME document under different keys —
    # the hero invoice is also the past-due (or disputed) tap, and
    # the hero ticket is also the shipping-paper tap. Capture-all
    # must not show the same document twice — the hero stands, the
    # tap for the same document stands down, and its weight leaves
    # the workload total with it. PO-expiry taps are NOT suppressed:
    # they name the PO, a different condition from the invoice's
    # lateness.
    hero_docs = set()
    for it in top_items:
        k = it.get("key") or ""
        for pfx in ("money:late:", "money:due:"):
            if k.startswith(pfx):
                hero_docs.add(("inv", k[len(pfx):]))
        if k.startswith("top:asset:"):
            hero_docs.add(("tkt", k[len("top:asset:"):]))
    def _hero_dupe(it):
        k = it.get("key") or ""
        for pfx in ("acct:pastdue:", "acct:disputed:"):
            if k.startswith(pfx):
                return ("inv", k[len(pfx):]) in hero_docs
        if k.startswith("dash:fitship:"):
            return ("tkt", k[len("dash:fitship:"):]) in hero_docs
        return False
    pool = []
    seen_keys = set()
    for it in top_items:
        k = it.get("key") or ""
        if k:
            if k in seen_keys:
                continue
            seen_keys.add(k)
        pool.append(it)
    for it in alerts:
        k = it.get("key") or ""
        if k:
            if k in seen_keys:
                continue
            seen_keys.add(k)
        if _hero_dupe(it):
            continue
        pool.append(it)
    shown = pool[:5]
    # Total for "+ N more" and the Alerts (n) count: WORKLOAD, not rows
    # (Batch 3 #2/#18) — each pool item weighs what it stands for (a
    # grouped compliance line weighs its item count; everything else
    # weighs 1), widened by whatever alert_total counted beyond the
    # alerts actually passed in (alerts_for truncates its shown list).
    # A tap suppressed as the hero's duplicate needs no adjustment
    # here: it never enters pool_weight, and the widening term only
    # ever adds taps that were NOT passed in.
    pool_weight = sum(it.get("weight", 1) for it in pool)
    if alert_total is not None:
        passed_weight = sum(it.get("weight", 1) for it in alerts)
        total_unique = pool_weight + max(0, alert_total - passed_weight)
    else:
        total_unique = pool_weight
    bits = ""
    for i, it in enumerate(shown):
        href = html.escape(it['href'], quote=True)
        key = it.get("key") or ""
        # Laptop-pass fix round (2026-10-20, Jason): NO verb/"Handle now"
        # button — the alert text itself is the link that goes to the
        # item. EVERY shown alert carries the snooze stepper, riding
        # right-justified (the .ack-right rule). app.py stamps the book's
        # standard minutes onto each item; the stepper teaches it.
        ack = (_ack_forms(key, path, None, it.get("snooze_minutes"))
               if key else "")
        if i == 0:
            bits += (
                f"<div class='tap top'><span class='msg'>Top of the day</span>"
                f"<a href='{href}'>{html.escape(it['text'])}</a>{ack}</div>"
            )
        else:
            bits += (
                f"<div class='tap mentionrow'><a href='{href}'>"
                f"{html.escape(it['text'])}</a>{ack}</div>"
            )
    # No Clear button (Jason 2026-10-24, 'm' look-see item 1): he never
    # asked for one. Snooze is the strip's only defer control.
    util_row = ""
    # Items 2–5 render as link + snooze rows (laptop-pass fix
    # round): the link goes to the item's page; the snooze is the one
    # defer control. Everything past the five shown rolls into the
    # quiet "+ N more" below.
    # Overflow counts workload past the shown rows (Batch 3 #2): the
    # shown rows' weights leave the total, and the line reads "+ N
    # more" and NOTHING else — no explanatory sentence, app-wide rule.
    more = total_unique - sum(it.get("weight", 1) for it in shown)
    if more < 0:
        more = 0
    more_html = ""
    if more > 0:
        more_html = (f"<span class='tap calm' style='border:none;background:none;"
                     f"padding:0;margin:0;flex:1'><span class='msg'>+ {more} more</span></span>")
    if cats is not None:
        # Category filter: quiet funnel button at the strip's right end.
        # Popover with three checkboxes + Save, posting to /ticker/cats
        # (markup: tickf_html — shared with the refresh endpoint).
        util_row += (
            f"<div class='tapbox filterbox' style='display:inline-block'>"
            f"<button type='button' class='vbtn' title='Choose which alerts show on the ticker' "
            f"onclick=\"var f=document.getElementById('tickf');"
            f"f.style.display=(f.style.display==='none'?'block':'none')\">⧩ Filter</button>"
            + tickf_html(cats, path)
            + "</div>"
        )
    footer = ""
    if util_row or more_html:
        # One footer line for the whole strip (2026-10-17 one-page rule):
        # the +N more note and the Filter utility share it.
        footer = (f"<div style='display:flex;gap:8px;align-items:center;justify-content:flex-end;margin:0'>"
                  f"{more_html}{util_row}</div>")
    n = total_unique
    if n == 0:
        # Quiet book (tweak round 2026-10-20): the strip still renders on
        # Today — the calm line IS the ticker at rest. Before this fix the
        # Filter footer populated `bits` first, so the calm branch below
        # was unreachable and a quiet book showed no ticker at all. The
        # Filter rides along so a filtered-out category can be let back in.
        if path == "/":
            return ("<div class='news'><div class='tap calm'>"
                    "<span class='msg'>Nothing overdue.</span>"
                    "</div>" + footer + "</div>")
        return ""
    bits += footer
    return ticker_details(bits, n, path)


# Line-item delete X (Jason 2026-10-14): one delegated handler for every
# line-item row in the app. Empty row -> removed at once; populated row ->
# Per-page zoom REMOVED (tweak round 2026-10-20, Jason): the header
# zoom control and its per-page localStorage factors are gone.
# One general zoom remains — the Text size setting
# (ui_text_size), set under Setup -> Administration (and kept
# on Setup -> Devices), applied equally to every page.

# confirm("Delete this line item?") first; last row in its group -> cleared
# instead of removed so a form never ends up with zero rows. Empty = every
# field blank, 0, or (qty fields only) the untouched default 1. Backends
# read fixed index ranges and skip blanks, so gaps left by a removed middle
# row are harmless — no renumbering needed.
PRINTMENU_JS = """
<script>
/* Print menu actions (Jason 2026-10-18). Print to Screen builds a
   document-like view of the CURRENT page (live values included):
   controls become their values, app chrome is stripped. Print to
   Location files that same view (form pages) or the document's file
   (document menus) into the operator's print folder. */
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
      span.textContent = c.checked ? '\u2611' : '\u2610';
    } else {
      span.textContent = c.value || '';
    }
    c.parentNode.replaceChild(span, c);
  });
  Array.prototype.slice.call(clone.querySelectorAll(
    'script,header,footer,nav,button,.pmenu,.mark,#morebelow,.pbox-lock,.news-wrap'
  )).forEach(function(n){ n.remove(); });
  var st = clone.ownerDocument.createElement('style');
  st.textContent = FS_PV_CSS;
  clone.querySelector('head').appendChild(st);
  return '<!doctype html>' + clone.outerHTML;
}
function fsPrintScreen(){
  var w = window.open('', '_blank');
  if (!w) return;
  w.document.write(fsBuildPrintHTML());
  w.document.close();
}
function fsPstat(btn, msg){
  var m = btn.closest('.pmenu');
  var st = m ? m.querySelector('.pstat') : null;
  if (st) st.textContent = msg;
}
function fsSaveLoc(btn){
  fsPstat(btn, 'Saving\u2026');
  var body = new URLSearchParams(); body.set('doc', btn.getAttribute('data-doc'));
  fetch('/print/save', {method:'POST', body: body}).then(function(r){ return r.json(); })
    .then(function(j){ fsPstat(btn, j.ok ? ('Saved to ' + j.path) : ('Could not save: ' + (j.error || 'error'))); })
    .catch(function(e){ fsPstat(btn, 'Could not save.'); });
}
function fsSavePage(btn){
  fsPstat(btn, 'Saving\u2026');
  var body = new URLSearchParams();
  body.set('name', document.title || 'FleetSheet document');
  body.set('html', fsBuildPrintHTML());
  fetch('/print/save-page', {method:'POST', body: body}).then(function(r){ return r.json(); })
    .then(function(j){ fsPstat(btn, j.ok ? ('Saved to ' + j.path) : ('Could not save: ' + (j.error || 'error'))); })
    .catch(function(e){ fsPstat(btn, 'Could not save.'); });
}
document.addEventListener('click', function(e){
  document.querySelectorAll('details.pmenu[open]').forEach(function(d){
    if (!d.contains(e.target)) d.removeAttribute('open');
  });
});
/* Anchoring (Jason 2026-10-24): when a print menu opens, flip it up
   (.up) if the downward options would run past the viewport bottom —
   the menu always renders fully on-screen. */
document.addEventListener('toggle', function(e){
  var d = e.target;
  if (!d.classList || !d.classList.contains('pmenu')) return;
  if (!d.open) { d.classList.remove('up'); return; }
  var p = d.querySelector('.popts');
  if (!p) return;
  d.classList.remove('up');
  var r = p.getBoundingClientRect();
  if (r.bottom > window.innerHeight - 8) d.classList.add('up');
}, true);
</script>
"""

LINEDEL_JS = """
<script>(function(){
  function isQtyName(n){return /^(qty\\d*|quantity|q\\d+)$/i.test(n||"");}
  function fieldEmpty(el){
    var t=(el.type||"").toLowerCase(), v=el.value;
    if(t==="checkbox"||t==="radio") return !el.checked;
    if(t==="file") return !v;
    if(el.tagName==="SELECT") return el.selectedIndex<=0||v==="";
    if(v==null) return true;
    v=String(v).trim();
    if(v==="") return true;
    var n=Number(v);
    if(isNaN(n)) return false;
    if(n===0) return true;
    if(isQtyName(el.name)&&n===1) return true;
    return false;
  }
  function rowEmpty(row){
    var els=row.querySelectorAll("input,select,textarea");
    for(var i=0;i<els.length;i++){ if(!fieldEmpty(els[i])) return false; }
    return true;
  }
  function rowOf(btn){
    return btn.closest("tr")||btn.closest(".iline")||btn.closest(".lineitem-row");
  }
  // #1 protection: a line-item row is the group's first row when no
  // earlier sibling is a line-item row. #1 can never be deleted — to
  // kill it, leave the form. Every other row deletes (confirm when
  // populated). Saved lines on the invoice detail page use
  // .line-del-submit below and are not form rows.
  function isFirstRow(row){
    var s=row.previousElementSibling;
    while(s){
      if(s.matches&&s.matches(".lineitem-row, tr.co-line, .iline")) return false;
      s=s.previousElementSibling;
    }
    return true;
  }
  // Hide #1's red X (and re-show every other row's — clones copy the
  // hidden style, so refresh must run after every add/delete).
  function refreshLineDel(){
    document.querySelectorAll(".lineitem-row, tr.co-line, .iline").forEach(function(row){
      var b=row.querySelector("button.line-del");
      if(b) b.style.display=isFirstRow(row)?"none":"";
    });
  }
  document.addEventListener("click",function(e){
    var sub=e.target&&e.target.closest?e.target.closest("button.line-del-submit"):null;
    if(sub){
      // Saved line on the invoice detail page: confirm, then submit the
      // form. requestSubmit keeps the clerk Name required-check.
      e.preventDefault();
      if(window.confirm("Delete this line item?")&&sub.form){
        if(sub.form.requestSubmit) sub.form.requestSubmit(sub);
        else sub.form.submit();
      }
      return;
    }
    var btn=e.target&&e.target.closest?e.target.closest("button.line-del"):null;
    if(!btn) return;
    var row=rowOf(btn); if(!row) return;
    if(isFirstRow(row)) return;
    if(!rowEmpty(row)&&!window.confirm("Delete this line item?")) return;
    var container=row.parentNode;
    container.removeChild(row);
    if(container) container.dispatchEvent(new Event("input",{bubbles:true}));
  });
  // Description textareas (point 4.5, 2026-10-18): grow down their own
  // column as text wraps; the bordered row grows with them.
  function growDesc(t){ t.style.height="auto"; t.style.height=(t.scrollHeight+2)+"px"; }
  function growAllDesc(){ document.querySelectorAll("textarea.ldesc").forEach(growDesc); }
  document.addEventListener("input",function(e){
    if(e.target&&e.target.classList&&e.target.classList.contains("ldesc")) growDesc(e.target);
  });
  refreshLineDel();
  growAllDesc();
  new MutationObserver(function(){ refreshLineDel(); growAllDesc(); })
    .observe(document.body,{childList:true,subtree:true});
})();</script>
"""

# Heartbeat: every open FleetSheet page (desk, yard, PIN-lock, EULA) tells the
# server "I'm still here" once a minute. The beats drive the yard-device note
# and the dead-server banner below. The server itself stops when the
# FleetSheet window closes (app-window watcher / close-grace in app.py) —
# the old idle watchdog that stopped it after quiet minutes was removed
# 2026-10-20 (tweak round 2) as redundant with the desk idle lock.
# On failure a slim banner appears once; no auto-reload.
HEARTBEAT_JS = """
<script>
(function(){
  var lost=false, warned=false;
  function showLost(){
    if(lost)return;lost=true;
    var b=document.createElement('div');
    // Name the observable cause, not a guess: the client only knows the
    // server stopped responding. Never claim idle — a crash or a killed
    // server looks identical from here.
    b.textContent = 'FleetSheet is not responding — the server stopped. Close this window and start FleetSheet again.';
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
  // Desk idle lock (Jason 2026-10-15): no interaction for FS_LOCK_MINS
  // minutes -> clear the PIN session and show the PIN form. 0 = Off.
  // Heartbeat fetches are not activity — only real interaction resets.
  // Never fires on auth/onboarding pages, and never navigates away when
  // the server is already known dead (the banner stays put).
  var lockMins = (typeof window.FS_LOCK_MINS === 'number' && window.FS_LOCK_MINS > 0) ? window.FS_LOCK_MINS : 0;
  var lockSkip = (function(){var p = location.pathname;
    return p === '/pin' || p === '/pin/forgot' || p === '/eula' || p === '/welcome' ||
      p === '/setup/security/pin' || p === '/phone.html' || p.indexOf('/d') === 0;})();
  var lockTimer = null;
  function armLock(){
    if(!lockMins || lockSkip) return;
    if(lockTimer) clearTimeout(lockTimer);
    lockTimer = setTimeout(function(){
      if(!lost) location.href = '/pin/lock?next=' + encodeURIComponent(location.pathname + location.search);
    }, lockMins * 60000);
  }
  ['mousemove','mousedown','keydown','wheel','touchstart','input','scroll'].forEach(function(ev){
    window.addEventListener(ev, armLock, {passive:true});
  });
  armLock();
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
    // Same rule as the desk banner: name the observable cause, not a guess.
    b.textContent = 'FleetSheet is not responding — the server stopped. Ask the desk to start FleetSheet again.';
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
    b.textContent='The desk window closed. Server stops in '+remain+'s.';
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


# Printed-view header (Jason 2026-10-24): every printed view carries
# company · title · date. The date fills client-side (the browser's
# timezone is the desk's), so the header is right wherever it prints.
PRINT_DATE_JS = ("<script>document.querySelectorAll('[data-print-date]')"
                 ".forEach(function(el){el.textContent=new Date()"
                 ".toLocaleDateString(undefined,{year:'numeric',"
                 "month:'short',day:'numeric'});});</script>")


def print_head(company, title):
    return (f"<div class='print-head'>{html.escape(company)} · "
            f"{html.escape(title)} · <span data-print-date></span></div>"
            f"{PRINT_DATE_JS}")


def page(title, body, company="FleetSheet", path="", alerts=None, top_items=None,
         alert_total=None, cats=None, mods=None):
    body_cls = _body_classes()
    sec = _nav_section(path)
    def cls(name):
        return ' class="on"' if sec == name else ""
    # Shop flow (Jason, 2026-10-21): a module switched OFF loses its
    # top-level nav tab — the route itself never dies. mods=None (the
    # EULA/PIN/welcome renders) or compliance ON renders byte-identical
    # nav to before.
    compliance_link = ("" if (mods is not None and not mods.get("compliance", True))
                       else f'<a href="/compliance"{cls("compliance")}>Compliance</a>\n')
    billing_link = ("" if (mods is not None and not mods.get("billing", True))
                    else f'<a href="/money"{cls("acct")}>Billing</a>\n')
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
    # No sticky catch form in the header (Jason 2026-10-18): the header
    # carries brand, nav, and actions only. Sticky notes live in their
    # card on Today, which has its own add form.
    return f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<link rel="icon" href="/favicon.ico">
<title>{html.escape(title)} · {html.escape(company)}</title><style>{CSS}</style>{_text_size_style()}</head>
<body class="{body_cls}"><header><div class="brand"><img src="/company-logo" alt="" onerror="this.remove()">{html.escape(company)}</div>
<nav class="main">
<a href="/"{cls('dash')}>Today</a>
{billing_link}<a href="/ticket/new"{cls('ticketnew')}>Equipment</a>
{compliance_link}<a href="/reports"{cls('reports')}>Reports</a>
<span class="tabright"><a href="/setup/admin"{cls('admin')}>Admin</a></span>
</nav>
{yard_note}</header>{"" if path in ("/assets", "/compliance") else news_strip(alerts, path, top_items, alert_total, cats)}<main>{print_head(company, title)}{body}</main>
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
{DCARD_JS}
{COMBO_JS}
{LOOKUP_SELECT_JS}
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
    "Save customer":"Tax exempt: on site",
    "Save site":"Tax follows location",
    "Save work order":"Internal or billable",
    "Create invoice":"One customer",
    "Apply cash":"Invoice balance only",
    "Pay from box":"Petty-cash out",
    "Put in box":"Petty-cash in",
    "Save float":"Box target amount",
    "Work ticket":"Crew print sheet",
    "Delivery ticket":"Sign-off sheet",
    "Show stays":"Units on rent by date",
    "Phone button file":"Phone HTML file",
    "Windows shortcut":"PC shortcut file",
    "Tickets CSV":"Rental fact table",
    "Invoices CSV":"Invoice headers, balances",
    "Work orders CSV":"Service rows",
    "Units CSV":"Fleet list, rates",
    "Customers CSV":"Account list",
    "All tables JSON":"JSON bundle",
    "All CSV + JSON zip":"Full export zip",
    "Quoted":"Estimate only",
    "Reserved":"Unit held",
    "Dispatched":"On truck, not on rent",
    "On Rent":"Clock running",
    "Off Rent":"Clock stopped",
    "Ready to Bill":"Awaiting invoice",
    "Invoiced":"On an invoice",
    "Void":"Rental Ticket void, unit free"
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
</script>{AUDIT_POPUP_JS}{NOTE_POPUP_JS}{SUM_NOTE_JS}<script>window.FS_IDLE_MINS={IDLE_MINS};window.FS_LOCK_MINS={LOCK_MINS};</script>{HEARTBEAT_JS}{LINEDEL_JS}{PRINTMENU_JS}
</body></html>"""


def tabs(active, items, right_html=""):
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
    if right_bits or right_html:
        out += ('<span class="tabright">' + "".join(right_bits)
                + right_html + "</span>")
    return out + "</div>"


def tabs_reports(active="/reports", con=None):
    items = [
        ("/reports", "Operations", "Availability, certs, invoicing, recap, stays, maintenance"),
        ("/tickets", "Rental Tickets", "Rental Tickets and status"),
        ("/wos", "Work orders", "Yard and billable service work"),
        ("/export", "Data", "Weekly reports and exports"),
    ]
    # Shop flow (Jason, 2026-10-21): work orders OFF drops the tab —
    # surface only; /wos itself stays live. con=None renders as before.
    if con is not None and not engine.module_on(con, "work_orders"):
        items = [i for i in items if i[0] != "/wos"]
    return tabs(active, items)


def weekly_tabs(active="", con=None):
    """The three weekly push-button reports — AR aging, fleet utilization,
    this week's flow. One row, always one click away. Billing OFF drops
    the Weekly money tab (surface only; con=None renders as before)."""
    items = [
        ("/reports/weekly/money", "Weekly money", "AR aging"),
        ("/reports/weekly/fleet", "Fleet utilization", "Days on rent / idle / down"),
        ("/reports/weekly/flow", "This week's flow", "Reservations, quotes, job ends, shop work"),
    ]
    if con is not None and not engine.module_on(con, "billing"):
        items = [i for i in items if i[0] != "/reports/weekly/money"]
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
        ("avail", "Availability", "Availability, certs, off-rent, maintenance"),
        ("money", "Billing", "Invoicing status and recap"),
        ("stays", "Stays", "Asset stays by date range"),
    ]
    bits = []
    for key, lab, tip in items:
        cls = "on" if key == active else ""
        bits.append(
            f'<a class="{cls}" href="/reports?b={key}{qs}" data-tip="{html.escape(tip)}">{lab}</a>'
        )
    return '<div class="tabs" style="margin-bottom:12px">' + "".join(bits) + "</div>"


# The sealed Petty Cash door (Jason 2026-10-25, build 'w'): a popup
# button, not a tab — it opens the drawer popup (data-audit). It
# renders in the Admin tab row at tab-button size (.tabdoor mirrors
# .tabs a), right end. (Build 'aa', 2026-10-26: the data-nofullpage
# opt-out that build 'w' hung on this door is retired — the Full
# page element is deleted from the popup shell itself, so no
# opener needs, or carries, a suppression flag.)
_PETTY_DOOR = ("<button type=\"button\" class=\"tabdoor\" data-audit=\"/petty\" "
               "data-title=\"Petty Cash\">Petty Cash</button>")


def tabs_admin(active="/setup/admin", heading="", petty_door=False,
               con=None):
    # Heading renders ABOVE the sub-tabs (Jason 2026-10-06): the page title
    # leads, the section tabs follow. Two-row Admin nav (Jason
    # 2026-10-24): Row 1 order Administration, Billing, Security,
    # Setup. Row 2 shows ONLY on setup pages: Company, Customers,
    # Vendors, Job Sites below Setup (order of importance, Jason's
    # 'l' look, pack 'm'). Petty Cash's one door sits IN the
    # Administration page's tab row (Jason 2026-10-25, build 'w' —
    # supersedes pack 'm''s standalone button below the row): same
    # row, same size as the tab buttons, right-justified. It renders
    # only on the Administration page (petty_door=True), so the
    # sealed one-door world stands; the drawer page lights
    # Administration. Admin functions reached from the Administration
    # page (devices, health, backups, anything unlisted) light
    # Administration.
    h = f"<h1>{heading}</h1>" if heading else ""
    row2_active = None
    if active == "/setup":
        row1, row2_active = "/setup", "/setup"
    elif active == "/customers" or active.startswith("/customer"):
        row1, row2_active = "/setup", "/customers"
    elif active == "/sites" or active.startswith("/site"):
        row1, row2_active = "/setup", "/sites"
    elif active == "/setup/vendors":
        row1, row2_active = "/setup", "/setup/vendors"
    elif active == "/setup/billing":
        row1 = "/setup/billing"
    elif active == "/setup/security":
        row1 = "/setup/security"
    elif active.startswith("/petty"):
        row1 = "/setup/admin"
    else:
        row1 = "/setup/admin"
    out = h + tabs(row1, [
        ("/setup/admin", "Administration", "Devices, backups, data health, and system maintenance."),
        ("/setup/billing", "Billing", "Invoice numbering, payment terms, billing email, and billing defaults."),
        ("/setup/security", "Security", "Desk PIN and protected-function access."),
        ("/setup", "Setup", "Company, customers, job sites, and vendors."),
    ], right_html=_PETTY_DOOR if petty_door else "")
    if row2_active:
        # Build 'ai' (Jason 2026-10-28): the Company tab wears the
        # company's own name — the entered DBA when one stands, else
        # the entered legal name, else "Company" (no company info
        # yet). The label reads the LIVE company record: a tab label
        # is screen furniture, not a printed document, so the
        # issuance-snapshot rule does not apply to it.
        _co_label = "Company"
        if con is not None:
            try:
                _crow = con.execute(
                    "SELECT dba, name FROM company WHERE id=1").fetchone()
                if _crow:
                    _co_label = ((str(_crow[0] or "").strip())
                                 or (str(_crow[1] or "").strip())
                                 or "Company")
            except Exception:
                _co_label = "Company"
        out += tabs(row2_active, [
            ("/setup", _co_label, "Company identity, address, phone numbers, and business profile."),
            ("/customers", "Customers", "Customers, locations, contacts, and commercial terms."),
            ("/setup/vendors", "Vendors", "Outside vendors and services for repairs, inspections, and rentals."),
            ("/sites", "Job Sites", "Physical work locations and their optional tax treatment."),
        ])
    return out


# Setup chain (Batch 3 #3; Jason's order, 2026-10-22/23): Company ->
# Admin (operational settings) -> Customers -> Assets/Equipment ->
# Billing -> Job Sites (OPTIONAL) -> Layout and functional options ->
# Finished -> Today. Admin is visited twice by design: step 2 is the
# Admin page's operational settings, step 7 is the same page's Page
# Layout / functional options (its editor carries ?step=layout so the
# page knows which stop this is). The chain governs the INITIAL run
# only: once the last required step lands, the setup_finished option
# is set and every Setup page goes back to save-stays-on-page. Each
# entry: (anchor path the save handlers report, step key, display
# name, editor path the operator is carried to, optional?).
SETUP_FLOW = [
    ("/setup", "company", "Company", "/setup?edit=1", False),
    ("/setup/admin", "admin", "Admin \u2014 operational settings", "/setup/admin", False),
    ("/customers", "customer", "Customers", "/customer/new", False),
    ("/units", "equipment", "Assets / Equipment", "/unit/new", False),
    ("/setup/billing", "billing", "Billing", "/setup/billing", False),
    ("/sites", "site", "Job Sites", "/site/new", True),
    ("/setup/admin", "layout", "Layout and functional options", "/setup/admin?step=layout", False),
]


def _chain_progress(con):
    """Done-ness for the chain's record steps. Demo-seeded rows don't
    count until the company is real (the standing rule since 2026-10-07)."""
    try:
        c = con.execute("SELECT name FROM company WHERE id=1").fetchone()
        cname = ((c["name"] if c else "") or "").strip()
        company_done = bool(cname) and cname.upper() not in ("YOUR COMPANY LLC", "FLEETSHEET")
        return {
            "company": company_done,
            "customer": company_done and con.execute("SELECT 1 FROM customers LIMIT 1").fetchone() is not None,
            "equipment": company_done and con.execute("SELECT 1 FROM assets LIMIT 1").fetchone() is not None,
            "site": company_done and con.execute("SELECT 1 FROM sites LIMIT 1").fetchone() is not None,
        }
    except Exception:
        return {}


def _setup_step_done(con, step, progress=None):
    """Is a chain step complete? Visit steps (admin/billing/layout) are
    done once their form is saved, tracked via options."""
    if step == "billing":
        try:
            if not engine.module_on(con, "billing"):
                # Billing OFF (shop flow, Jason 2026-10-21): a shop that
                # doesn't bill is never routed through the billing step
                # — it counts done.
                return True
        except Exception:
            pass
    if step in ("admin", "billing", "layout"):
        try:
            return engine.get_option(con, "setup_%s_done" % step, "") == "1"
        except Exception:
            return False
    if progress is None:
        progress = _chain_progress(con)
    return bool(progress.get(step))


def _backfill_setup_finished(con):
    """Existing installs predate the setup_finished flag: a book whose
    company is real (not the placeholder) finished setup under the old
    flow, so set the flag on first load and never re-enter the chain.
    One-shot: the first load under this code stamps setup_chain_seen;
    later loads never re-evaluate (a fresh install's company becomes
    real mid-chain, at its first save — that must not trip this)."""
    try:
        row = con.execute(
            "SELECT value FROM options WHERE key='setup_finished'").fetchone()
        if row is not None:
            return
        seen = con.execute(
            "SELECT value FROM options WHERE key='setup_chain_seen'").fetchone()
        if seen is not None:
            return
        engine.set_option(con, "setup_chain_seen", "1")
        c = con.execute("SELECT name FROM company WHERE id=1").fetchone()
        cname = ((c["name"] if c else "") or "").strip()
        if cname and cname.upper() not in ("YOUR COMPANY LLC", "FLEETSHEET"):
            engine.set_option(con, "setup_finished", "1")
        con.commit()
    except Exception:
        pass


def setup_finished(con):
    _backfill_setup_finished(con)
    try:
        return engine.get_option(con, "setup_finished", "") == "1"
    except Exception:
        return False


def setup_rerun(con):
    """True while a "Run setup again" review pass is in progress."""
    try:
        return engine.get_option(con, "setup_rerun", "") == "1"
    except Exception:
        return False


# In a review pass, record steps open on their LIST — the existing
# records with current values — not on a blank create form.
_RERUN_LIST_TARGETS = {"customer": "/customers", "equipment": "/assets",
                       "site": "/sites"}


def chain_rerun_target(step_key):
    """Where a review pass lands for a step."""
    for _a, step, _n, editor, _o in SETUP_FLOW:
        if step == step_key:
            return _RERUN_LIST_TARGETS.get(step, editor)
    return "/setup"


def setup_chain(con):
    """The chain as display rows: number, key, name, editor, optional, done."""
    progress = _chain_progress(con)
    return [{"n": i, "key": step, "name": name, "editor": editor,
             "optional": optional,
             "done": _setup_step_done(con, step, progress)}
            for i, (_a, step, name, editor, optional)
            in enumerate(SETUP_FLOW, 1)]


def setup_chain_active(con):
    """True during a setup run: a review pass, or the initial run with
    at least one required step incomplete. Job Sites never keeps the
    chain alive."""
    if setup_rerun(con):
        return True
    if setup_finished(con):
        return False
    return any(not s["done"] for s in setup_chain(con) if not s["optional"])


def next_setup_step(con, current_path):
    """Editor path of the next incomplete chain step after current_path,
    or None. Kept for the legacy flow callers (the PIN-set handler):
    a path that is not a chain stop (e.g. /setup/security, collected in
    onboarding) resolves to the chain's first incomplete required step."""
    if setup_finished(con) and not setup_rerun(con):
        return None
    chain = setup_chain(con)
    idx = -1
    for i, (anchor, _s, _n, _e, _o) in enumerate(SETUP_FLOW):
        if current_path == anchor or current_path.startswith(anchor + "?"):
            idx = i
            break
    if idx < 0:
        for i, (anchor, _s, _n, _e, _o) in enumerate(SETUP_FLOW):
            if current_path and current_path.startswith(anchor + "/"):
                idx = i
                break
    if idx < 0:
        for s in chain:
            if not s["done"] and not s["optional"]:
                return s["editor"]
        return None
    for s in chain:
        if s["n"] > idx + 1 and not s["done"]:
            return s["editor"]
    return None


def _chain_msg(saved_label, cur, nxt):
    """The save statement for a chain step: what was saved, then
    Jason's step statement ("Step N done. Step M next \u2014 <Name>.",
    or the Finished statement on the last step)."""
    head = f"{saved_label}. " if saved_label else ""
    if nxt is None:
        return (f"{head}Step {cur['n']} done. Setup is complete \u2014 "
                "FleetSheet opens on Today, ready for work.")
    return (f"{head}Step {cur['n']} done. "
            f"Step {nxt['n']} next \u2014 {nxt['name']}.")


def chain_advance(con, just_step, saved_label=None):
    """After a chain step saves, where does the operator go?

    Returns (url, msg) \u2014 msg in Jason's form: "Step N done. Step M
    next \u2014 <Name>."; the last required step sets setup_finished and
    aims at Today with "Step N done. Finished." Returns None when the
    chain is not in play (already Finished, or a detour save), so
    callers fall back to their normal save-stays-on-page redirect.
    In-order guard (initial run): the chain advances only when the
    saved step actually completed and every earlier required step is
    done. A review pass advances in order regardless of done-ness."""
    if setup_rerun(con):
        chain = setup_chain(con)
        by_key = {s["key"]: s for s in chain}
        cur = by_key.get(just_step)
        if cur is None:
            return None
        later = [s for s in chain if s["n"] > cur["n"]]
        if not later:
            try:
                engine.set_option(con, "setup_rerun", "")
                engine.set_option(con, "setup_finished", "1")
            except Exception:
                pass
            return ("/", _chain_msg(saved_label, cur, None))
        nxt = later[0]
        return (chain_rerun_target(nxt["key"]),
                _chain_msg(saved_label, cur, nxt))
    if setup_finished(con):
        return None
    chain = setup_chain(con)
    by_key = {s["key"]: s for s in chain}
    cur = by_key.get(just_step)
    if cur is None:
        return None
    if not cur["done"]:
        return None
    if any(not s["done"] for s in chain
           if s["n"] < cur["n"] and not s["optional"]):
        return None
    remaining = [s for s in chain if not s["done"] and not s["optional"]]
    if not remaining:
        try:
            engine.set_option(con, "setup_finished", "1")
        except Exception:
            pass
        return ("/", _chain_msg(saved_label, cur, None))
    nxt = remaining[0]
    site = by_key.get("site")
    if (site and not site["done"] and cur["key"] == "billing"
            and nxt["n"] > site["n"]):
        nxt = site
    return (nxt["editor"], _chain_msg(saved_label, cur, nxt))


def setup_in_progress(con):
    """True while a setup run (initial or review) is in progress."""
    return setup_chain_active(con)


# Guidance copy for the chain pages. Jason's register exception
# (2026-10-22): setup may talk the operator through it, even hold their
# hand. Everywhere else the app stays terse. These strings appear ONLY
# inside chain_banner output, which renders only while the chain runs.
_CHAIN_GUIDE = {
    "company": "Start here. Your company name and address print on every invoice, quote, and report FleetSheet makes, so two careful minutes now saves corrections all year.",
    "admin": "These settings run the working side of FleetSheet \u2014 backups, printing, and the system tools. Set them once; you can change them any time.",
    "customer": "Add the customers you bill. One is enough to keep moving \u2014 the rest can be added as work comes in.",
    "equipment": "Add the equipment you rent and track. Start with one unit; the fleet grows from there.",
    "billing": "How your invoices are numbered, and the terms new work starts from. Any single invoice can override these.",
    "site": "Job Sites is optional. Add a site now if your work happens at named locations \u2014 or skip this step and add sites later, whenever they're needed.",
    "layout": "Last step: make FleetSheet comfortable to look at all day \u2014 page layout, text size, and what your shop does, all on this page. Set them how you like, then save.",
}


def _chain_banner_html(con, current_key, rerun):
    chain = setup_chain(con)
    cur = next((s for s in chain if s["key"] == current_key), None)
    if cur is None:
        return ""
    named = " \u00b7 ".join(
        f"{s['n']} {s['name']}{' (optional)' if s['optional'] else ''} "
        f"{'\u2713' if s['done'] else '\u25cb'}" for s in chain)
    if rerun:
        title = (f"Setup review \u2014 Step {cur['n']} of {len(chain)} "
                 f"\u2014 {html.escape(cur['name'])}")
        guide = ("Your current settings are in place. Review them, "
                 "change what you like, and save to move to the next "
                 "step. Nothing here deletes anything.")
        later = [s for s in chain if s["n"] > cur["n"]]
        nav = ""
        if later:
            nxt = later[0]
            nav = (f"<a class='btn' href='{chain_rerun_target(nxt['key'])}'>"
                   "Next step \u2192</a> ")
        extra = ("<p class='actions' style='margin:6px 0 0'>" + nav +
                 "<form method=post action='/setup/rerun/cancel' "
                 "style='display:inline'><button class='secondary'>"
                 "End review</button></form></p>")
    else:
        title = (f"Step {cur['n']} of {len(chain)} "
                 f"\u2014 {html.escape(cur['name'])}")
        guide = _CHAIN_GUIDE.get(current_key, "")
        extra = ""
        if current_key == "site":
            nxt = next((s for s in chain if s["n"] == cur["n"] + 1), None)
            if nxt:
                extra = ("<p class='actions' style='margin:6px 0 0'>"
                         f"<a class='btn secondary' href='{nxt['editor']}'>"
                         "Skip this step \u2192</a></p>")
    return (f"<section class='card' style='border-left:4px solid #b8860b'>"
            f"<p style='margin:0 0 4px'><b>{title}</b></p>"
            f"<p style='margin:0'>{html.escape(guide)}</p>"
            f"<p class='hint' style='margin:4px 0 0'>Setup: {named}</p>"
            f"{extra}</section>")


def chain_banner(con, current_key):
    """The hand-holding banner for a chain step page: which step this
    is, a sentence of guidance, and the whole chain NAMED with its
    marks (never a bare count). Renders only while a setup run \u2014 the
    initial pass or a review pass \u2014 is in progress."""
    try:
        if not setup_chain_active(con):
            return ""
    except Exception:
        return ""
    return _chain_banner_html(con, current_key, setup_rerun(con))


def chain_banner_rerun(con, current_key):
    """The walk banner for LIST pages, which are review-pass stops for
    the record steps. Renders only during a review pass."""
    if not setup_rerun(con):
        return ""
    return _chain_banner_html(con, current_key, True)


def chain_banner_admin(con, q=None):
    """The chain banner for the Administration page, which hosts TWO
    chain stops: step 2 (admin) and step 7 (layout). The step is the
    layout stop when the URL says so (?step=layout, the chain's own
    editor for step 7), or when step 2 is already done and layout is
    the stop the chain is waiting on."""
    key = "admin"
    try:
        if (q or {}).get("step") == "layout":
            key = "layout"
        elif not setup_rerun(con):
            chain = setup_chain(con)
            by_key = {s["key"]: s for s in chain}
            if (by_key.get("admin", {}).get("done")
                    and not by_key.get("layout", {}).get("done")
                    and all(s["done"] for s in chain
                            if s["n"] < by_key["layout"]["n"]
                            and not s["optional"])):
                key = "layout"
    except Exception:
        key = "admin"
    return chain_banner(con, key)


def chain_layout_current(con, q=None):
    """True when the layout stop is the chain stop in play \u2014 the
    Admin page's layout card then carries its chain save form. In a
    review pass the Admin page is visited twice; only the
    ?step=layout visit is the layout stop."""
    try:
        if setup_rerun(con):
            return (q or {}).get("step") == "layout"
        if setup_finished(con):
            return False
        chain = setup_chain(con)
        by_key = {s["key"]: s for s in chain}
        lay = by_key.get("layout")
        if not lay or lay["done"]:
            return False
        return all(s["done"] for s in chain
                   if s["n"] < lay["n"] and not s["optional"])
    except Exception:
        return False


# Folder picking (Batch 3 #10e): no folder path is typed anywhere.
# The two folder settings (backup folder, print-to-location folder)
# render as a read-only field plus a Browse link into the server-side
# folder browser at /setup/folders, which offers New Folder. The
# browser lists directories on this computer only — it reads no file
# contents and sets nothing until "Use this folder" is posted.
def folder_field(target, current):
    """The folder setting control for the save forms: read-only field
    (name kept for the existing POST handlers) + Browse link."""
    name = "backup_dir" if target == "backup" else "print_folder"
    return (f"<input name={name} value=\"{html.escape(current or '', quote=True)}\" "
            f"readonly placeholder=\"(default folder)\"> "
            f"<a class='btn secondary' href='/setup/folders?for={target}'>Browse\u2026</a>")


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


def _billing_items():
    """The Billing door row — ONE grammar app-wide (Jason 2026-10-24,
    'm' look-see items 6–9): tabs are PLACES, named for the documents
    that live there; creating is an ACTION — a New button on the
    place — never a tab. Both Billing tab builders render this row.
    The places land on their documents: Invoices on the most recent
    invoice (blank when none), Payments / Credit Memos / Cash on
    their forms — the same land-on-the-document pattern the ticket
    kind tabs use."""
    return [
        ("/money?tab=invoice", "Invoices", "Open invoices"),
        ("/pay", "Payments", "Payments against invoices"),
        ("/credit", "Credit Memos", "Credits against invoices"),
        ("/cash", "Cash", "Cash against Invoice / Work Order / Rental Ticket"),
    ]


def tabs_invoice(active="/invoices", con=None):
    """Billing tabs on the invoice pages. Quotes and change orders
    are not here; they live on their own pages. Billing OFF: the
    whole door row steps aside (con=None renders as before).
    Petty cash is NOT here (Jason 2026-10-24): sealed from the money
    system, it lives under Administration behind its own button."""
    if con is not None and not engine.module_on(con, "billing"):
        return ""
    items = _billing_items()
    bits = []
    for href, lab, tip in items:
        on = (href == active or
              (href == "/money?tab=invoice"
               and active in ("/invoices", "/money/all")))
        cls = "on" if on else ""
        bits.append(
            f'<a class="{cls}" href="{href}" data-tip="{html.escape(tip)}">{lab}</a>')
    return '<div class="tabs">' + "".join(bits) + "</div>"


def tabs_quotes(active="/quotes"):
    """Quiet home for Quotes and Change orders — off the money tabs.
    Places only (Jason 2026-10-24): the Quotes place lands on the
    blank quote form, so no "New quote" action tab exists."""
    items = [
        ("/quotes", "Quotes", "Stand-alone estimates"),
        ("/changes", "Change orders", "Changes against a quote"),
    ]
    bits = []
    for href, lab, tip in items:
        cls = "on" if href == active else ""
        bits.append(
            f'<a class="{cls}" href="{href}" data-tip="{html.escape(tip)}">{lab}</a>')
    return '<div class="tabs">' + "".join(bits) + "</div>"


def tabs_money(active="invoice", con=None):
    """Billing sub-tabs: the shared place row (_billing_items) —
    Invoices, Payments, Credit Memos, Cash. Flat, no groupings;
    quotes and change orders live under New Ticket, not here.
    Billing OFF: no door row (con=None renders as before). Petty
    cash is NOT here (Jason 2026-10-24): the drawer is sealed from
    the money system, so it lives under Administration behind its
    own button, never as a money tab."""
    if con is not None and not engine.module_on(con, "billing"):
        return ""
    keys = ["/money?tab=invoice", "/pay", "/credit", "/cash"]
    active_href = {"invoice": keys[0], "pay": keys[1],
                   "credit": keys[2], "cash": keys[3]}.get(active, "")
    bits = []
    for href, lab, tip in _billing_items():
        cls = "on" if href == active_href else ""
        bits.append(
            f'<a class="{cls}" href="{href}" data-tip="{html.escape(tip)}">{lab}</a>')
    return '<div class="tabs">' + "".join(bits) + "</div>"


def format_phone(value):
    """Display formatting for phone numbers — the ONE shared formatter
    (engine_core.format_phone_number, Jason 2026-10-21): no prefix is
    invented for a plain 10-digit number, and anything unparseable
    shows exactly as stored."""
    return engine.format_phone_number(value)

def opts(rows, value_key, label_key, selected=""):
    out = ['<option value="">— pick —</option>']
    for r in rows:
        v, lab = r[value_key], r[label_key]
        sel = " selected" if str(v) == str(selected) else ""
        out.append(f'<option value="{html.escape(str(v))}"{sel}>{html.escape(str(lab))} ({html.escape(str(v))})</option>')
    return "\n".join(out)


# --- Desk PIN: gates the money pages -------------------------------------------
# Money routes need a signed fspin cookie, issued by /pin after the desk PIN
# is entered. The PIN itself is set in Admin -> Security and stored in the
# engine as a salted hash. Yard-device (/d) routes are never PIN-gated.
PIN_SESSION_HOURS = 8
PIN_MAX_FAILS = 5
PIN_LOCK_SECONDS = 600
MONEY_PREFIXES = ("/invoice", "/invoices", "/pay", "/credit", "/petty", "/cash",
                  "/export", "/backup", "/money", "/setup/devices",
                  "/print/invoice", "/print/credit", "/print/petty", "/print/quote",
                  "/print/change", "/print/work", "/print/delivery", "/print/report/aging")
# PIN-gated prefixes (2026-10-24, Admin/Setup reversal): money routes
# plus the whole Admin section. Money especially — but Security is the
# keys to the kingdom (it sets the PIN itself), and the rest of Admin
# (Company, Customers, Vendors, Job Sites, Billing setup, Health,
# backups, restores, updater checks) is regulated the same way. /setup
# subsumes the old explicit /setup/security, /setup/admin, /setup/lookups
# and /setup/folders entries. Yard /d stays ungated, as does /manual.
GATED_PREFIXES = MONEY_PREFIXES + ("/setup", "/customers", "/customer",
                                    "/sites", "/site", "/health",
                                    "/print/save", "/print/save-page")
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
    return f"<div class='nudge'><b>Today list</b> {items}</div>"


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

    def _send_json(self, obj, code=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
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
        # A 303 with no body still needs Content-Length: 0 — without it a
        # strict HTTP/1.1 keep-alive client waits for the timeout to learn
        # the response is over (same defect class as the v1.0 spinner fix).
        self.send_header("Content-Length", "0")
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
        "/cash/save": "/cash",
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
        "/setup/lookups/add": "/setup",
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
            f"<main>{body}</main><script>window.FS_IDLE_MINS={IDLE_MINS};</script>{HEARTBEAT_JS_YARD}</body></html>"
        )

    def _device_denied(self, reason):
        return self._device_page(
            "Not authorized",
            f"<div class='stat'><b>Device not authorized.</b><br>{html.escape(reason)}.<br>"
            "<br>"
            "<a href='/'>Back to the desk</a> · <a href='/setup/devices'>Pair a device</a></div>",
        )


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

    def _gated_path(self, path):
        """True when the desk PIN gate covers this path: money routes plus
        the whole Admin section (Company, Customers, Vendors, Job Sites,
        Billing setup, Health, and everything under /setup)."""
        return any(path == p or path.startswith(p + "/") for p in GATED_PREFIXES)

    def _pin_gate(self, con, path, is_post=False):
        """Redirect to /pin when a gated route needs the desk PIN.

        Returns True when the request may continue."""
        # Test harnesses set FLEETSHEET_TEST_MODE=1 to bypass the PIN gate
        # entirely — they manage their own auth state. (2026-10-06)
        if os.environ.get("FLEETSHEET_TEST_MODE") == "1":
            return True
        if not self._gated_path(path):
            return True
        if not engine.pin_is_set(con):
            # No PIN yet: Security itself must stay reachable (it is where
            # the PIN gets set); everything else redirects there to set one.
            # First-time setup also funnels through /welcome → PIN set, so
            # this branch never strands onboarding.
            if path == "/setup/security" or path.startswith("/setup/security/"):
                return True
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
            f"<p class=mute>Unlocked for {PIN_SESSION_HOURS} hours on this browser.</p>"
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

    def _sq_fields(self, q1sel=0, q2sel=1, sa1="", sa2=""):
        """Two security-question dropdowns + answer inputs. sa1/sa2 carry
        retained answers on a failed post (Batch 3 #1: the form is
        retained — what was typed stays typed)."""
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
            f"<input name='sa1' autocomplete=off required style='max-width:40ch' "
            f"value=\"{html.escape(sa1 or '', quote=True)}\">"
            "<label>Security question 2</label>"
            f"<select name='sq2'>{''.join(opts2)}</select>"
            "<label>Answer 2</label>"
            f"<input name='sa2' autocomplete=off required style='max-width:40ch' "
            f"value=\"{html.escape(sa2 or '', quote=True)}\">")

    def _retained_sq(self, q):
        """(q1sel, q2sel, sa1, sa2) retained values from a query/post dict."""
        q = q or {}
        def _qi(v, d):
            try:
                return int(v)
            except (TypeError, ValueError):
                return d
        return (_qi(q.get("sq1"), 0), _qi(q.get("sq2"), 1),
                q.get("sa1") or "", q.get("sa2") or "")

    def view_pin_forgot(self, con, q):
        err = q.get("err") or ""
        err_box = f"<div class=err>{html.escape(err)}</div>" if err else ""
        sq_section = ""
        if engine.pin_security_is_set(con):
            q1, q2 = engine.pin_security_questions(con)
            qs = engine.PIN_SECURITY_QUESTIONS
            # Retained answers on a failed post (Batch 3 #1).
            _ra1 = html.escape((q or {}).get("sa1") or "", quote=True)
            _ra2 = html.escape((q or {}).get("sa2") or "", quote=True)
            sq_section = (
                "<h3 style='margin-top:24px'>Or answer your security questions</h3>"
                f"{err_box}"
                "<form method=post action='/pin/forgot/questions'>"
                f"<label>{html.escape(qs[q1])}</label>"
                f"<input name='sa1' autocomplete=off required style='max-width:40ch' value=\"{_ra1}\">"
                f"<label>{html.escape(qs[q2])}</label>"
                f"<input name='sa2' autocomplete=off required style='max-width:40ch' value=\"{_ra2}\">"
                "<button type=submit class=sqsave>"
                "Save</button></form>")
        return (
            "<div class=card style='max-width:420px;margin:24px auto'>"
            "<h2 style='margin-top:0'>Reset the desk PIN</h2>"
            "<p class=mute>Answer your security questions to clear the PIN, "
            "then set a new one in Admin → Security.</p>"
            f"{err_box if not sq_section else ''}"
            f"{sq_section}"
            "<p class=mute><a href='/pin'>Back</a></p></div>"
        )

    def view_security(self, con, q):
        is_set = engine.pin_is_set(con)
        _pin_style = "font-size:24px;letter-spacing:6px;text-align:center;max-width:16ch"
        if not is_set:
            form = (
                "<h3>Set a desk PIN</h3>"
                "<p class=mute style='margin:4px 0 8px'>The PIN is 4\u20138 "
                "digits. Billing pages (invoices, payments, credits, petty "
                "cash, and exports) ask for it on this Wi-Fi. Yard devices "
                "are never asked.</p>"
                "<form method=post action='/setup/security/pin'>"
                "<input type=hidden name=mode value='set'>"
                "<div class=\"row3\">"
                f"<div><label>New PIN</label><input type=password name=pin1 inputmode=numeric maxlength=8 required style='{_pin_style}'></div>"
                f"<div><label>Repeat PIN</label><input type=password name=pin2 inputmode=numeric maxlength=8 required style='{_pin_style}'></div>"
                "<div></div>"
                "</div>"
                "<h3 style='margin-top:20px'>Security questions</h3>"
                "<p class=mute style='margin:4px 0 8px'>The security "
                "questions are used to reset a forgotten PIN. Pick "
                "questions only you could answer.</p>"
                f"{self._sq_fields(*self._retained_sq(q))}"
                "<button type=submit class=sqsave>Save</button></form>")
        else:
            form = (
                "<h3>Change the desk PIN</h3>"
                "<p class=mute style='margin:4px 0 8px'>The new PIN is "
                "4\u20138 digits. Yard devices are never asked for it.</p>"
                "<form method=post action='/setup/security/pin'>"
                "<input type=hidden name=mode value='change'>"
                "<div class=\"row3\">"
                f"<div><label>Current PIN</label><input type=password name=cur inputmode=numeric maxlength=8 required style='{_pin_style}'></div>"
                f"<div><label>New PIN</label><input type=password name=pin1 inputmode=numeric maxlength=8 required style='{_pin_style}'></div>"
                f"<div><label>Repeat new PIN</label><input type=password name=pin2 inputmode=numeric maxlength=8 required style='{_pin_style}'></div>"
                "</div>"
                "<button type=submit>Save</button></form>")
        # No standing security-questions card (Jason 2026-10-21,
        # look-see batch 2): the questions live only inside the flows
        # that use them — PIN set (above, and the welcome flow) and
        # PIN reset (/pin/forgot, where they are asked and the
        # answers verified). The old change-questions card sat on
        # this page full-time for a job that happens at reset.
        # Desk idle lock (Jason 2026-10-15): minutes of no interaction
        # before the desk locks and asks for the PIN again. 0 = Off.
        try:
            _lock_mins = desk_lock_mins(con)
        except Exception:
            _lock_mins = 60
        lock_card = (
            "<h3>Desk idle lock</h3>"
            "<p class=mute style='margin:4px 0 8px'>Minutes idle before the desk "
            "locks and asks for the PIN again. 0 = Off. Locking closes "
            "nothing — it just asks for the PIN.</p>"
            "<form method=post action='/setup/security/lock'>"
            "<div class=frow><div><label>Lock after (minutes)</label>"
            f"<input name=desk_lock_mins type=number min=0 max=1440 class=w-xs value=\"{_lock_mins}\"></div>"
            "<div style='align-self:end'><button class=secondary>Save</button></div>"
            "</div></form>")
        # Tightened layout (laptop-pass fix round, 2026-10-20, Jason):
        # the lock card and the PIN card share one row instead of two
        # full-width cards stretched over white space.
        return (tabs_admin("/setup/security")
                + "<style>.seccard{padding:10px 14px}.seccard h3{margin:0 0 6px}</style>"
                + f"<div class='fgrid' style='margin-top:10px'>"
                  f"<div class='card seccard'>{lock_card}</div>"
                  f"<div class='card seccard'>{form}</div></div>")

    def view_welcome(self, con, q):
        """First-run onboarding: set the desk PIN right after the EULA.

        The money pages are PIN-gated, so the PIN is collected up front as
        part of setup rather than as a surprise wall mid-workflow. (2026-10-06)
        """
        err = q.get("err") or ""
        err_box = f"<p class=err>{html.escape(err)}</p>" if err else ""
        return (
            "<div class='card' style='max-width:560px;margin:32px auto'>"
            "<h2 style='margin-top:0'>Set your desk PIN</h2>"
            "<p class=mute>Your money pages are protected by a desk PIN. "
            "Set it now; you enter it once per session. The PIN is "
            "4\u20138 digits. Yard devices are never asked.</p>"
            f"{err_box}"
            "<form method=post action='/setup/security/pin'>"
            "<input type=hidden name=mode value='set'>"
            "<input type=hidden name=next value='/'>"
            "<label>New PIN</label><input type=password name=pin1 inputmode=numeric "
            "maxlength=8 required style='font-size:24px;letter-spacing:6px;text-align:center;max-width:16ch'>"
            "<label>Repeat PIN</label><input type=password name=pin2 inputmode=numeric "
            "maxlength=8 required style='font-size:24px;letter-spacing:6px;text-align:center;max-width:16ch'>"
            "<h3 style='margin-top:20px'>Security questions</h3>"
            "<p class=mute>Answering these two questions resets a "
            "forgotten PIN. Pick questions only you could answer.</p>"
            f"{self._sq_fields(*self._retained_sq(q))}"
            "<button type=submit class=sqsave>Save</button></form>"
            "</div>")

    def view_devices(self, con, q):
        devs = engine.list_devices(con)
        saved_base = engine.get_option(con, "device_base_url", "")
        lan = lan_urls()
        guess = saved_base or (lan[0] if lan else "http://127.0.0.1:8765")
        rows = []
        for d in devs:
            tok = d["token"]
            state = d["state"]
            exp = fmt_date(d["expires_at"], "—")
            if d["state"] == "expiring":
                exp = f"{exp} ({d['days_left']}d left)"
            seen = fmt_datetime(d["last_seen_at"], "never")
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
        return tabs_admin("/setup/devices") + f"""
        {net_note}
        <div class="row">
          <div>
            <h2 style="font-size:16px;color:var(--frame)">Add a Yard Device</h2>
            <p class="mute" style="margin:4px 0 8px">Create a temporary authorization for a phone, tablet, or scanner. The desk PIN is set under Security.</p>
            <form method=post action="/setup/devices/issue">
              <label>Device Name</label>
              <input name=label maxlength=60 required placeholder="Yard tablet 1" style="max-width:220px">
              <div class="row">
                <div><label>Expires (days)</label><input name=days value="90" inputmode=numeric style="max-width:80px"></div>
                <div><label>Server address in QR</label>
                  <input name=base_url value="{html.escape(guess)}" style="max-width:220px"></div>
              </div>
              <p><button>Issue + show QR</button></p>
            </form>
            <h2 style="font-size:16px;color:var(--frame)">Authorized Devices</h2>
            <table><tr><th>Device</th><th>State</th><th>Expires</th><th>Last seen</th><th>Actions</th></tr>
            {"".join(rows) or "<tr><td colspan=5>No devices yet.</td></tr>"}</table>
          </div>
          <div>
            {self._devices_done_button(con, q)}
            <h2 style="font-size:16px;color:var(--frame)">Display Preferences</h2>
            <form method=post action="/setup/options">
              <label><input type=checkbox name=tooltips value=1 {"checked" if tips_on else ""}> Show delayed tips</label>
              <label for="text_size">Text size</label>
              <select name=text_size id=text_size class=w-sm data-tip="Scales every FleetSheet page up or down — like browser zoom, but built in, so it stays put.">
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
        # Suppressed (Batch 3 #3): the old Done button jumped to the
        # standalone Setup Complete page; the setup chain's own
        # "Finished" (last step's save -> Today) replaces it. Devices
        # is not a chain stop.
        return ""

    def view_device_show(self, con, token, base):
        dev = engine.get_device(con, token or "")
        if not dev:
            return tabs_admin("/setup/devices") + "<p>Unknown device.</p>"
        url = (base or "").rstrip("/") + "/d/" + token
        qr_uri, qr_err = qr_data_uri(url)
        if qr_uri:
            img = f"<img src=\"{qr_uri}\" alt=\"device QR\" width=240 height=240>"
            dl = (f"<p><a class=\"btn\" href=\"{qr_uri}\" "
                  f"download=\"fleetsheet-device.png\">Download QR image</a></p>")
        else:
            # Loud fallback (Issue 2): the QR is unavailable, but the
            # address itself still works — say so and show it to type.
            img = (f"<p class='err'>{html.escape(qr_err)}</p>")
            dl = ""
        return tabs_admin("/setup/devices") + f"""
        <h1>Device QR — {html.escape(dev['label'])}</h1>
        <div class="qrbox" style="max-width:340px">
          {img}
        </div>
        {dl}
        <p>Link (type it on a scanner with no camera):</p>
        <p class="code">{html.escape(url)}</p>
        <p class="hint">Expires {html.escape(fmt_date(dev['expires_at'], '—'))}.
        Rotating issues a new code; the old one works 24 more hours. Revoking kills it at once.</p>
        <p><a class="btn" href="/setup/devices">Back to devices</a></p>
        """

    def view_device_home(self, con, dev):
        ph = ",".join("?" * len(self.DEVICE_LIST_STATUSES))
        rows = con.execute(
            f"SELECT t.ticket_id, c.customer_id, a.asset_id, t.status, t.on_rent "
            f"FROM tickets t JOIN customers c ON c.id = t.customer_id "
            f"JOIN assets a ON a.id = t.asset_id "
            f"WHERE t.status IN ({ph}) ORDER BY t.status, t.on_rent", self.DEVICE_LIST_STATUSES
        ).fetchall()
        items = "".join(
            f"<a class=trow href='/d/ticket/{html.escape(r['ticket_id'])}'>"
            f"<b>{html.escape(r['ticket_id'])}</b> · {html.escape(r['status'])}"
            f"<small>{html.escape(r['customer_id'])} · {html.escape(r['asset_id'])} · on {html.escape(fmt_date(r['on_rent'], '—'))}</small></a>"
            for r in rows
        ) or "<div class='stat'>No yard Rental Tickets right now.</div>"
        exp = f"Code good through {fmt_date(dev['expires_at'])}." if dev.get("expires_at") else ""
        return self._device_page(
            "Yard", f"<h2 style='margin:4px 0 8px'>Yard Rental Tickets</h2>{items}"
                    f"<p class='hint' style='color:#5C6B7A'>{html.escape(exp)}</p>"
                    f"<p><a href='/d/forget' style='color:#5C6B7A;font-size:14px'>"
                    f"Sign out of yard mode</a></p>",
            label=f"Yard · {dev['label']}",
        )

    def view_device_ticket(self, con, dev, tid, flash=""):
        t = con.execute("SELECT * FROM tickets WHERE ticket_id=?", (tid,)).fetchone()
        if not t:
            return self._device_page("Yard", "<div class='stat'>Unknown Rental Ticket.</div>",
                                     label=f"Yard · {dev['label']}")
        conds = list(engine.COND_RANK.keys())
        def sel(cur):
            pre = (f"<option selected>{html.escape(engine.COND_NOT_RECORDED)}</option>"
                   if cur == engine.COND_NOT_RECORDED else "")
            return pre + "".join(f"<option{' selected' if cur == c else ''}>{html.escape(c)}</option>" for c in conds)
        crew_opts = "".join(f'<option value="{html.escape(n)}"></option>' for n in engine.list_crew(con))
        name_field = (f"<label>Your Name</label><input name=clerk list=dcrew required maxlength=40>"
                      f"<datalist id=dcrew>{crew_opts}</datalist>")
        nxt = [s for s in engine.ALLOWED_NEXT.get(t["status"], ()) if s in self.DEVICE_STATUSES]
        # The deliberate escape rides on the yard forms too (shop-flow,
        # Jason 2026-10-21): a "Proceed anyway" checkbox appears on a
        # move only when a gate would refuse it — a missing condition
        # (switch ON) or a non-PASS FIT (either switch mode).
        _fit = engine.ticket_money(con, tid).get("fit", "PASS")
        _cond_on = engine.module_on(con, "condition")
        def _proceed_for(s):
            parts = []
            if s in ("Dispatched", "On Rent"):
                if _cond_on and not t["out_condition"]:
                    parts.append("no check-out condition")
                if _fit and _fit != "PASS":
                    parts.append(f"FIT {_fit}")
            if s == "Off Rent" and _cond_on and not t["in_condition"]:
                parts.append("no check-in condition")
            if not parts:
                return ""
            return ("<label><input type=checkbox name=proceed value=1> Proceed anyway — "
                    + " and ".join(parts) + " (logged)</label>")
        status_btns = "".join(
            f"<form method=post action='/d/ticket/{html.escape(tid)}/status' style='margin:0'>"
            f"<input type=hidden name=status value='{html.escape(s)}'>"
            f"<label>Your Name</label><input name=clerk list=dcrew required maxlength=40>"
            f"<datalist id=dcrew>{crew_opts}</datalist>"
            + (f"<label>Off-rent date (only for Off Rent)</label><input type=date name=off_rent value=\"{date.today().isoformat()}\">" if s == "Off Rent" else "")
            + _proceed_for(s)
            + f"<button class='big' type=submit>Mark {html.escape(s)}</button></form>"
            for s in nxt
        ) or ("<div class='stat'>No yard moves from here.</div>")
        cust = con.execute("SELECT account_name, customer_id FROM customers WHERE id=?", (t["customer_id"],)).fetchone()
        cust_name = cust["account_name"] if cust else engine.cust_code(con, t["customer_id"])
        _asset_disp = engine.asset_code(con, t["asset_id"]) or t["asset_id"]
        return self._device_page(
            tid,
            f"""{flash}
            <div class="stat"><b>{html.escape(tid)}</b> · {html.escape(t["status"])}<br>
            <small>{html.escape(cust_name)} · {html.escape(_asset_disp)} ·
            out: {html.escape(t["out_condition"] or "—")} · in: {html.escape(t["in_condition"] or "—")} ·
            FIT: {html.escape(_fit or "")}{(" · override: " + html.escape(t["fit_override"])) if ("fit_override" in t.keys() and t["fit_override"]) else ""}</small></div>
            <form method=post action="/d/ticket/{html.escape(tid)}/condition" data-autosave enctype="multipart/form-data">
              <input type=hidden name=side value=out>
              <h3 style="margin:0 0 4px">Check out</h3>
              {name_field}
              <label>Out Condition</label><select name=condition required>{sel(t["out_condition"])}</select>
              <label>Meter / hours / fuel</label><input name=meter value="{html.escape(t["out_meter"] or "")}">
              {self._photo_field(tid, "out", t["out_photo"])}
              <label>Note</label><input name=note value="{html.escape(t["out_note"] or "")}">
              <button class="big" type=submit>Save</button>
            </form>
            <form method=post action="/d/ticket/{html.escape(tid)}/condition" data-autosave enctype="multipart/form-data">
              <input type=hidden name=side value=in>
              <h3 style="margin:0 0 4px">Check in</h3>
              {name_field}
              <label>In Condition</label><select name=condition required>{sel(t["in_condition"])}</select>
              <label>Meter / hours / fuel</label><input name=meter value="{html.escape(t["in_meter"] or "")}">
              {self._photo_field(tid, "in", t["in_photo"])}
              <label>Note</label><input name=note value="{html.escape(t["in_note"] or "")}">
              <button class="big" type=submit>Save</button>
            </form>
            <h3>Status</h3>
            {status_btns}
            <p><small>Yard moves only.</small></p>
            <p><a class="bigbtn" style="display:block;text-align:center" href="/d">← All yard Rental Tickets</a></p>
            """,
            label=f"Yard · {dev['label']}",
        )

    def _pin_nag(self, con):
        """Desk-PIN reminder: stays up top until the PIN is set, or snoozed
        for this browser session (the nag returns next visit — not forgotten)."""
        if engine.pin_is_set(con):
            return ""
        if self._cookies().get("pin_nag") == "off":
            return ""
        return ("<div class=err><b>Billing pages are open on this Wi-Fi.</b> "
                "Set a desk PIN in <a href='/setup/security'>Admin → Security</a>. "
                "<form method='post' action='/pin/nagoff' style='display:inline'>"
                "<button type='submit' style='margin-left:10px'>Snooze</button>"
                "</form></div>")

    def _view_door(self, view_url=None, view_title=None, links=False,
                   extra=""):
        """The universal View button (Jason 2026-10-25, build 'r',
        facelift item 3 — supersedes the 2026-10-24 'm' lone-door
        compromise and the 2026-10-20 every-page Done-View provision):
        EVERY form page ends with this row — one View button at the
        BOTTOM LEFT of the form, opening the page's own
        filterable/sortable list pop-up (Refresh / Print / Close at
        the popup's bottom right, via data-viewpop). Nothing else
        renders below a form. links=True renders a plain link for
        ?frag=1 fragments (the petty drawer pattern)."""
        if not view_url:
            return ""
        _vt = view_title or "View"
        if links:
            return (f"<p class='daudit'><a class='vbtn' "
                    f"href=\"{html.escape(view_url, quote=True)}\">View</a></p>")
        return (f"<div class='viewrow'><button type='button' class='vbtn' "
                f"data-audit=\"{html.escape(view_url, quote=True)}\" "
                f"data-title=\"{html.escape(_vt)}\" data-viewpop=\"1\">View</button>{extra}</div>")

    def _view_row(self, view_url, view_title, extra=""):
        """The universal View row for a form page that carried no door
        before build 'r' — same button, same place (bottom left).
        `extra` rides inside the row after the View button (build
        'ai': a summary's Payment navigation button — same .vbtn
        size, same line, so the row stays one size throughout)."""
        return self._view_door(view_url, view_title, extra=extra)

    # --- Universal summary pattern (build 'u', Jason 2026-10-25) -----
    # The third universal pattern, beside the universal form and the
    # universal popup: every document has a summary view titled
    # "Summary of <Kind># <id>". The summary is for looking — the
    # document's facts stated the same way on each (customer, date,
    # status, lines, totals, notes, Job Info values, record stamps) —
    # with doors the same on each: Edit (to the form, where a form
    # exists), Print (the document's three-choice print), View (the
    # kind's list), plus that kind's working-popup doors. The work
    # stays on the forms and in the forms' popups; no working section
    # stands on a summary. (Build 'aa', 2026-10-26: the contract is
    # now BUILT, not just stated — every kind flows through _sum_page
    # and every door row through _sum_doors; the Invoice's hand-built
    # page is folded in, and a standing census — checks/census_ui.py
    # — diffs the eight door rows so the class cannot drift again.)
    _POP_STYLE = ("display:none;position:fixed;top:8%;left:8%;right:8%;"
                  "background:white;border:2px solid #333;padding:18px;"
                  "z-index:1000;max-height:84%;overflow:auto")

    def _pop_door(self, pop_id, label):
        """A working-popup door in the summary's door row, opening
        the inline popup _pop_wrap renders (the pattern the Job
        Info / sale-confirm / quote popups established). Build 'ac'
        (Jason 2026-10-27): the door carries .sumdoor — the door
        row is one line and renders at one size, the large
        standard, like the row's Edit and Print."""
        return (f"<button type=\"button\" class=\"vbtn sumdoor\" "
                f"onclick=\"document.getElementById('{pop_id}')"
                f".style.display='block'\">{html.escape(label)}</button> ")

    def _pop_furniture(self, pop_id, refresh_onclick=None):
        """The universal popup furniture (Jason 2026-10-24: every
        popup gets Close + Refresh + Print; build 'aa', 2026-10-26:
        the same set on BOTH shells, in this order — Collapse,
        Refresh, Print, Close — in the popup's heading). Print
        prints the host document/page; Refresh re-fetches the
        popup's content from the server (the Job Info popup's own
        refresh, refreshJobInfo, may be named by the host)."""
        _ref = refresh_onclick or f"wpopRefresh('{pop_id}')"
        # Build 'af': the furniture buttons ride the one gap
        # standard (flex gap:8px) rather than text spaces.
        return (
            f"<span style=\"float:right;display:inline-flex;gap:8px\">"
            f"<button type=\"button\" "
            f"onclick=\"wpopCollapse('{pop_id}',this)\">Collapse</button>"
            f"<button type=\"button\" onclick=\"{_ref}\">Refresh</button>"
            f"<button type=\"button\" onclick=\"wpopPrint()\">Print</button>"
            f"<button type=\"button\" "
            f"onclick=\"document.getElementById('{pop_id}')"
            f".style.display='none'\">Close</button></span>")

    def _pop_wrap(self, pop_id, title, inner):
        """The working popup itself (Shell B): fixed box, heading
        carrying the universal furniture, the working form(s)
        inside. One builder for every working popup — the Job Info
        popups and the few hand-built copies carry the same class,
        the same heading, the same furniture."""
        return (
            f"<div id=\"{pop_id}\" class=\"wpop\" style=\"{self._POP_STYLE}\">"
            f"<h3 class=\"wpop-h\" style=\"margin-top:0\">{html.escape(title)} "
            f"{self._pop_furniture(pop_id)}</h3>"
            f"{inner}</div>")

    @staticmethod
    def _fact_empty(val):
        """Whether a summary fact value is NO value (build 'af',
        Jason 2026-10-28): None, blank, or the bare em dash a
        builder writes for 'nothing here'. $0.00 is a value; '0'
        is a value."""
        if val is None:
            return True
        txt = re.sub(r"<[^>]+>", "", str(val)).strip()
        return txt in ("", "—")

    def _sum_facts(self, pairs):
        """One fact block's table: label/value rows, stated the same
        way on every summary. Values are pre-rendered HTML. Build
        'af' (Jason 2026-10-28, superseding the fact-row half of
        build 'ac''s anatomy rule FOR SUMMARIES): a fact with no
        value is OMITTED — no row, no em dash — and a block whose
        pairs all omit renders nothing. Doors, columns and sections
        keep their anatomy; only empty fact rows drop."""
        rows = "".join(
            f"<tr><th>{html.escape(str(lab))}</th><td>{val}</td></tr>"
            for lab, val in pairs if not self._fact_empty(val))
        return f"<table>{rows}</table>" if rows else ""

    def _sum_groups(self, groups):
        """The grouped fact blocks of a summary (build 'af', Jason
        2026-10-28): (heading, pairs) blocks in columns mimicking
        the kind's creation form — customer block up-left, Job Info
        block at right, the document's facts in their own block.
        A block with no surviving facts does not render."""
        out = []
        for heading, pairs in groups:
            tbl = self._sum_facts(pairs)
            if tbl:
                out.append(f"<div class='sumblk'><h3>"
                           f"{html.escape(heading)}</h3>{tbl}</div>")
        return (f"<div class='sumfacts'>{''.join(out)}</div>"
                if out else "")

    def _ji_pairs(self, triples):
        """Job Info block pairs with print-inclusion markers
        (build 'af', Jason 2026-10-28): (label, value, printed)
        triples become fact pairs whose value carries a small
        check when the field goes on the kind's printed document,
        a no-check otherwise. MARKER ONLY — a plain span with a
        title, never a link, button or handler. printed reflects
        what the kind's print actually carries (verified per kind
        in its summary builder); it is never a second setting."""
        out = []
        for lab, val, printed in triples:
            if self._fact_empty(val):
                continue
            mark = ("<span class='jmark' title='On the printed "
                    "document'>✓</span>" if printed else
                    "<span class='jmark no' title='Not printed'>✗</span>")
            out.append((lab, f"{val}{mark}"))
        return out

    def _job_att_list(self, kind, ref):
        """The document's existing job attachments (build 'af'):
        (stored_name, display_name) pairs from the shared document
        folder — the same filename scan printpack's invoice
        attachments use (fourth-from-last underscore segment is
        the yyyymmdd stamp)."""
        out = []
        try:
            import os
            d = engine.doc_dir()
            pref = f"{kind}_{ref}_"
            for name in sorted(os.listdir(d)):
                if not name.startswith(pref):
                    continue
                parts = name.rsplit("_", 3)
                if (len(parts) == 4 and len(parts[1]) == 8
                        and parts[1].isdigit()):
                    out.append((name, parts[3]))
        except Exception:
            pass
        return out

    def _sum_paperwork(self, kind, ref, extra_links=(), ret=None):
        """The Paperwork section at the foot of every summary
        (build 'af', Jason 2026-10-28): the document's existing
        attachments as plain links — add-only: no edit, replace or
        delete control stands here — and ONE bare file field whose
        form auto-submits on change (no button), posting to the
        shared /summary/upload handler, which files the upload
        through engine.save_job_attachment."""
        links = [
            f"<div><a href=\"/jobdoc/{html.escape(n, quote=True)}\">"
            f"{html.escape(disp)}</a></div>"
            for n, disp in self._job_att_list(kind, ref)]
        links += [f"<div>{h}</div>" for h in extra_links]
        ret = ret or (f"/invoice/{ref}" if kind == "invoice" else
                      f"/ticket/{ref}" if kind == "ticket" else
                      f"/sale/{ref}" if kind == "sale" else
                      f"/summary/{kind}/{ref}")
        return (
            f"<div class='sumsec'>Paperwork</div>"
            f"{''.join(links)}"
            f"<form method=post action='/summary/upload' "
            f"enctype='multipart/form-data'>"
            f"<input type=hidden name=kind value='{html.escape(kind, quote=True)}'>"
            f"<input type=hidden name=ref value='{html.escape(str(ref), quote=True)}'>"
            f"<input type=hidden name=return value='{html.escape(ret, quote=True)}'>"
            f"<input type=file name=attach onchange='this.form.submit()'>"
            f"</form>")

    def _sum_note_cell(self, kind, ref, line_id, note):
        """The Note cell of a summary lines table (build 'ah', Jason
        2026-10-28). A note that fits its cell stands as plain text.
        A longer note stands truncated and clickable: clicking it
        opens the temporary note box (see _sum_note_box_html /
        SUM_NOTE_JS), where the full note edits in place and posts
        with the summary's Print door. There is no per-line Read or
        Save button — a note saves with the document."""
        note = note or ""
        if len(note) <= 80:
            return html.escape(note)
        seg = {"invoice": "invoice", "wo": "wo", "ticket": "ticket",
               "sale": "sale", "quote": "quote",
               "change": "change"}[kind]
        return (f"<span class=\"notepop sumnote\" data-full=\""
                f"{html.escape(note.replace(chr(10), '&#10;'), quote=True)}\" "
                f"data-noteurl=\"/{seg}/{html.escape(str(ref), quote=True)}/linenote\" "
                f"data-lineid=\"{int(line_id)}\">"
                f"{html.escape(note[:80])}\u2026</span>")

    def _sum_note_box_html(self):
        """The temporary line-note box: one per summary page, opened
        by a long note's cell (build 'ah', Jason 2026-10-28). It
        carries exactly ONE control — Minimize. No Close, no Save:
        Jason's explicit design for this box, a named exception to
        the standing popup furniture; the edited note posts with
        the summary's Print door (SUM_NOTE_JS)."""
        return ("<div id=\"sumnotebox\"><div class=\"snb-card\">"
                "<label>Line note</label>"
                "<textarea maxlength=2000></textarea>"
                "<div class=\"snb-row\">"
                "<button type=button class=\"secondary snb-min\">"
                "Minimize</button></div></div></div>")

    def _sum_doors(self, working_html, edit_href=None, print_html=""):
        """The summary door row, built one way for every kind
        (build 'aa', Jason 2026-10-26 — the template contract the
        _sum_page comment has always stated): the kind's working
        popup doors first (in the kind's own order), then Edit
        (present only where the kind has its own editor — WS5's
        uniform rule), then ONE Print on every kind. Nothing else
        stands in the row. Build 'ac' (Jason 2026-10-27): every
        door in the row renders at the one large standard (see
        _pop_door / .sumdoor)."""
        tail = ""
        if edit_href:
            tail += (f"<a class=\"btn\" href=\""
                     f"{html.escape(edit_href, quote=True)}\">Edit</a> ")
        return working_html + tail + print_html

    def _sum_lines(self, cols, rows, empty_text="No lines."):
        """The one summary lines table (build 'ac', Jason
        2026-10-27): every kind's lines area renders through this
        builder — the same table classes (the Credit Memo's
        grid sum-lines set) and one column vocabulary. cols is a
        list of (header, numeric) pairs; rows are lists of
        pre-rendered cell HTML in the same order (numeric cells
        right-align, the family's standing figure style). A kind
        with no lines renders the shell — headers standing, one
        empty-state row — never a blank area: state changes
        values, not anatomy."""
        head = "".join(f"<th>{html.escape(h)}</th>" for h, _n in cols)
        if rows:
            body = ""
            for r in rows:
                cells = "".join(
                    f"<td class=num style='text-align:right'>{c}</td>"
                    if n else f"<td>{c}</td>"
                    for c, (_h, n) in zip(r, cols))
                body += f"<tr>{cells}</tr>"
        else:
            body = (f"<tr><td colspan={len(cols)}>"
                    f"{html.escape(empty_text)}</td></tr>")
        return (f"<table class='grid sum-lines'><tr>{head}</tr>"
                f"{body}</table>")

    def _sum_page(self, kind_label, ref, facts_pairs, lines_html,
                  doors_html, popups_html, view_url, view_title,
                  extra_top="", sections_html="", fact_groups=None,
                  paper_html="", pay_doc=None):
        """The one summary layout: title, fact table, lines, the
        standard sections (build 'ac': a kind's standing blocks
        after its lines — totals, panels, payments — composed as
        discrete sections, not glued inside the lines area), the
        door row (working-popup doors, Edit, Print), the popups,
        and the universal View row at the bottom left.
        Build 'af' (Jason 2026-10-28): facts ride in grouped
        blocks (fact_groups — see _sum_groups) instead of one
        full-width table, and the Paperwork section (paper_html)
        stands at the foot of the content, before the door row.
        Build 'ai' (Jason 2026-10-28, REVERSING the 'ag'/'ah'
        door removal at his word): pay_doc=(kind, ref) puts ONE
        small Payment button in the bottom row beside View — a
        NAVIGATION button to the Billing payment form with this
        record prefilled as the allocation target. No money is
        worked on the summary; the payment form governs from
        there. Money summaries pass it; the Payment and Credit
        Memo summaries do not."""
        facts_html = (self._sum_groups(fact_groups)
                      if fact_groups is not None
                      else self._sum_facts(facts_pairs))
        _pay_btn = ""
        if pay_doc:
            _pay_href = ("/money?tab=pay&doc="
                         + quote(f"{pay_doc[0]}:{pay_doc[1]}",
                                 safe=":"))
            _pay_btn = (f"<a class='vbtn' href=\"{_pay_href}\">"
                        f"Payment</a>")
        return f"""
        <h1>Summary of {html.escape(kind_label)}# {html.escape(str(ref))}</h1>
        {extra_top}
        {facts_html}
        {lines_html}
        {sections_html}
        {paper_html}
        <div class="viewrow" style="align-items:center">{doors_html}</div>
        {popups_html}
        {self._sum_note_box_html()}
        {self._view_row(view_url, view_title, extra=_pay_btn)}
        """

    def _assoc_co_fact(self, con, kind, ref):
        """The associated-change-orders fact for a money document's
        summary (build 'v', Jason 2026-10-25): a Change Order may
        name ONE associated document; the association is stated on
        BOTH summaries as a linked fact and changes no totals.
        Returns an HTML value or None."""
        try:
            cos = engine.associated_change_orders(con, kind, ref)
        except Exception:
            return None
        if not cos:
            return None
        return " · ".join(
            f"Change Order <a href=\"/summary/change/"
            f"{html.escape(c, quote=True)}\">{html.escape(c)}</a>"
            for c in cos)

    def view_summary_route(self, con, rest):
        """The /summary/<kind>/<id> routes (build 'u', Jason
        2026-10-25): the kinds whose record page was a form or a
        print view get their summary here — Work Order, Quote,
        Change Order, Payment, Credit Memo. Rental, Sales Ticket, and
        Invoice summaries live on their own record routes (/ticket/,
        /sale/, /invoice/), which ARE their summaries. Returns
        (title, body) for the prefix-route handler."""
        kind, _, ref = rest.partition("/")
        ref = unquote(ref or "")
        if kind == "wo":
            return (f"Work Order {ref}", self.view_wo_summary(con, ref))
        if kind == "quote":
            return (f"Quote {ref}", self.view_quote_summary(con, ref))
        if kind == "change":
            return (f"Change Order {ref}",
                    self.view_change_summary(con, ref))
        if kind == "payment":
            return (f"Payment {ref}", self.view_payment_summary(con, ref))
        if kind == "credit":
            return (f"Credit Memo {ref}",
                    self.view_credit_summary(con, ref))
        return ("Summary", "<p>Unknown summary.</p>")

    def _job_box(self, lines):
        """The header zone's Job Info box (Jason 2026-10-25, build
        't', universal form law): Row 2 right of the header — the
        form's own Job Info values, the fields its Job Info popup
        edits, each a value or a dash (the printed box's convention).
        Display only; the popup is where they are set."""
        body = "".join(
            f"<div>{html.escape(str(lab))} "
            f"{('<b>' + html.escape(str(val)) + '</b>') if str(val or '').strip() else '—'}</div>"
            for lab, val in lines)
        return (f"<div class=\"fh-job\"><div class=\"fh-job-h\">Job Info</div>"
                f"{body}</div>")

    def _form_head(self, con, doc_html, date_html, cust_html="", job_lines=None,
                   stacked=False):
        """The one header zone for every document form (Jason
        2026-10-25, build 'r', facelift items 4–6): Company block
        (left), Customer/Address block (middle), form # + Date
        (right — the number larger and bold, see .fh-no), then the
        bar (.fhead's bottom border). Nothing else stands above the
        line items. doc_html/date_html/cust_html are the form's own
        rendered fields; their names and mechanics are unchanged.

        Build 't' (Jason 2026-10-25, universal form law — his 'r'
        look enumeration): a document form passes job_lines (its
        Job Info box lines, see _job_box) and the head renders TWO
        rows — Row 1: Company (left), form # + Date (right); the
        bar; Row 2: Customer (left), Job Info box (right) — the
        layout his enumeration names and the printed sheet carries.
        Callers without job_lines (whose bodies are their work)
        keep the one-row head. Build 'ao' (Jason 2026-10-29): the
        Payment form passes stacked=True — it carries no Job Info
        lines, so its head renders the same two-row anatomy minus
        the box: Row 1 Company (left), form # + Date (right); the
        bar; Row 2 Customer (left) — the Customer below the
        Company, like every other money form, not to its right."""
        if job_lines is None:
            if stacked:
                return (f"<div class=\"fhead fhead2\">"
                        f"<div class=\"fh-row1\">{self._company_band(con)}"
                        f"<div class=\"fh-doc\"><div class=\"fh-no\">{doc_html}</div>"
                        f"<div class=\"fh-date\">{date_html}</div></div></div>"
                        f"<div class=\"fh-row2\"><div class=\"fh-cust2\">{cust_html}</div></div></div>")
            return (f"<div class=\"fhead\">{self._company_band(con)}"
                    f"<div class=\"fh-cust\">{cust_html}</div>"
                    f"<div class=\"fh-doc\"><div class=\"fh-no\">{doc_html}</div>"
                    f"<div class=\"fh-date\">{date_html}</div></div></div>")
        return (f"<div class=\"fhead fhead2\">"
                f"<div class=\"fh-row1\">{self._company_band(con)}"
                f"<div class=\"fh-doc\"><div class=\"fh-no\">{doc_html}</div>"
                f"<div class=\"fh-date\">{date_html}</div></div></div>"
                f"<div class=\"fh-row2\"><div class=\"fh-cust2\">{cust_html}</div>"
                f"{self._job_box(job_lines)}</div></div>")

    def _done_box(self, con, back="/", view_url=None, view_title=None,
                  links=False):
        """Done Today: what got done. Explicit completions only — tasks clicked
        off the to-do list plus hand-logged 'Add Done' entries. Nothing is
        pulled in from anywhere else; payments and everything else live behind
        the View audit button. `back` keeps Undo / Remove / Add Done on this page.

        Placement (Jason 2026-10-24, 'm' look-see item 11, ruling —
        supersedes the 2026-10-20 every-page provision): this box
        renders on the TODAY page only. Every other page that carried
        it now renders _view_door (its list pop-up door) instead."""
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
        _vu = view_url or "/done"
        _vt = view_title or "Done log"
        # links=True (Jason 2026-10-24, petty drawer fragment): inside a
        # ?frag=1 iframe there is no audit-popup JS, so the box's
        # buttons would be dead — plain links instead, which the
        # fragment's <base target=_top> sends to the main window.
        if links:
            _btns = (f"<a class='vbtn' href='/today/done/other?back={quote(back or '/', safe='')}'>Add Done</a> "
                     f"<a class='vbtn' href='{html.escape(_vu, quote=True)}'>View</a>")
        else:
            _btns = (f"<button type='button' class='vbtn' data-audit='/today/done/other?back={quote(back or '/', safe='')}' "
                     f"data-title='Add Done'>Add Done</button> "
                     f"<button type='button' class='vbtn' "
                     f"data-audit='{html.escape(_vu, quote=True)}' data-title='{html.escape(_vt)}'>View</button>")
        return (f"<div class='donebox' id='done-today'><h3>Done Today</h3>{rows}"
                f"<p class='daudit'>{_btns}</p></div>")

    def view_done_other(self, con, q=None):
        """'Add Done' pop-up: log an ad-hoc completion by hand. Opens in the
        audit pop-up; the form targets _top so saving lands back on the page
        that opened it."""
        desk = html.escape(self.desk(con), quote=True)
        back = html.escape(((q or {}).get("back") or "/"), quote=True)
        return f"""
        <h1>Add Done</h1>
        <form method="post" action="/today/done/other" target="_top" class="tform">
        <input type="hidden" name="clerk" value="{desk}">
        <input type="hidden" name="back" value="{back}">
        <p><input name="text" placeholder="What got done?" size="40" maxlength="200" required></p>
        <p><input name="link" placeholder="Link to record (optional, e.g. /invoice/INV-1024)" size="40" maxlength="200"></p>
        <p><button>Save</button></p>
        </form>
        """

    def view_done(self, con, q=None):
        """Done log — the list behind the Done Today View button
        (laptop-pass fix round, 2026-10-20, Jason): ONE filterable,
        sortable list of everything recorded done. The old Today /
        This week / This year tab grouping is gone — it was never
        asked for. Explicit completions plus payments collected, each
        an audit table under the shared filter + column sort. The
        ?period= parameter is still accepted (old links, the CSV dump
        and the print route keep their own period behavior) but the
        page itself always shows the whole log."""
        start, end = "2000-01-01", date.today().isoformat()
        tasks = engine.done_tasks(con, start, end, 5000)
        pays = engine.done_payments(con, start, end, 5000)
        trows = "".join(
            f"<tr><td>{html.escape(fmt_datetime(t['done_at']))}</td>"
            f"<td>{html.escape(t['text'])}</td>"
            f"<td>{html.escape(t['tier'])}</td>"
            f"<td>{html.escape(t['done_by'] or '—')}</td></tr>"
            for t in tasks) or "<tr><td colspan=4 class='mute'>Nothing logged.</td></tr>"
        prows = "".join(
            f"<tr><td>{html.escape(fmt_datetime(p['pay_date']))}</td>"
            f"<td><a href='/invoice/{html.escape(p['invoice_no'], quote=True)}'>"
            f"{html.escape(p['invoice_no'])}</a></td>"
            f"<td>{html.escape(p['account_name'])}</td>"
            f"<td style='text-align:right'>${p['amount']:,.2f}</td>"
            f"<td>{html.escape(p['method'])}</td>"
            f"<td>{html.escape(p['clerk'] or '—')}</td></tr>"
            for p in pays) or "<tr><td colspan=6 class='mute'>No payments collected.</td></tr>"
        ptotal = sum(p["amount"] for p in pays)
        return f"""
        <p class="hint"><input id="auditq" placeholder="Filter" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        </p>
        <div><a class='btn secondary' href='/done/dump?period=year'>Dump CSV</a>
           {self._print_menu(screen=f"/print/done?period=week")}</div>
        <h2>Completed ({len(tasks)})</h2>
        <table class="audit"><tr><th>When</th><th>Task</th><th>Tier</th><th>Input by:</th></tr>{trows}</table>
        <h2>Payments collected ({len(pays)}) — ${ptotal:,.2f}</h2>
        <table class="audit"><tr><th>When</th><th>Invoice</th><th>Customer</th>
        <th style='text-align:right'>Amount</th><th>Method</th><th>Input by:</th></tr>{prows}</table>
        """ + AUDIT_TABLE_JS

    def view_system_health(self, con):
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
        return tabs_admin("/health") + body

    def view_backups(self, con):
        b = engine.backup_status(con)
        last = html.escape(fmt_datetime(b.get("last"), "never"))
        folder = html.escape(b.get("folder") or "")
        sched, every_days = engine.get_backup_schedule(con)
        stale = "backup overdue" if b.get("stale") else "up to date"
        rows = engine.list_backups(con)
        if rows:
            trs = "".join(
                f"<tr><td>{html.escape(r['name'])}</td>"
                f"<td>{'Archive' if r['kind'] == 'archive' else 'Legacy (book only)'}</td>"
                f"<td>{fmt_datetime(r['mtime'])}</td>"
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
        <p class="mute" style="max-width:70ch">Each backup is one complete archive: the book plus every Rental Ticket photo and every data-book document, with integrity hashes. Only the newest dated copies are kept; older ones are pruned automatically. Downloads and restores need the desk PIN.</p>
        <h2>Backup Folder</h2>
        <form method=post action="/setup/admin">
          <input type=hidden name=chain_step value="admin">
          <div class="frow">
            <div style="flex:1">{folder_field("backup", b.get("folder") or "")}</div>
            <div style="align-self:end"><button class="secondary">Save</button></div>
          </div>
        </form>
        <p class=hint>Last backup: <b>{last}</b> ({stale}). Folder: {folder}.</p>
        <form method=post action="/backup" class="backup-bar">
          <span class="backup-msg">Copy the book, photos, and documents to a new dated archive now.</span>
          <button class="secondary">Backup now</button>
        </form>
        <h2>Automatic Backup Schedule</h2>
        <p class="mute">When FleetSheet starts, it makes a backup automatically if the last one is older than this schedule.</p>
        <form method=post action="/backup/schedule" class="schedule-form">
          {sched_radios}
          <button class="secondary">Save</button>
        </form>
        <h2>Saved Copies</h2>
        {table}
        <h2>Restore from a File</h2>
        <p class="mute" style="max-width:70ch">Restoring replaces the live book and the Rental Ticket photos with the uploaded copy. A safety snapshot of the current book is taken first, so a bad restore can itself be undone. The file is fully checked before anything is touched: it must be a healthy FleetSheet backup archive (.zip).</p>
        <form method=post action="/backup/restore" enctype="multipart/form-data">
          <label>Backup file (.zip, or a legacy .db)</label>
          <input type=file name=backup_file accept=".zip,.db" required>
          <label><input type=checkbox name=confirm value="yes" required>
          I understand this replaces the live book, photos, and documents</label>
          <button class="danger">Restore this file</button>
        </form>
        """

    def view_folder_picker(self, con, q=None):
        """Server-side folder browser (Batch 3 #10e): pick the backup
        folder or the print-to-location folder by browsing, with New
        Folder — no path is typed anywhere. Lists directory names
        only; nothing is set until "Use this folder" posts."""
        q = q or {}
        target = q.get("for") if q.get("for") in ("backup", "print") else "backup"
        if target == "backup":
            _row = con.execute(
                "SELECT backup_dir FROM company WHERE id=1").fetchone()
            configured = ((_row["backup_dir"] if _row else "") or "").strip()
            label = "Backup folder"
            back = "/backup"
        else:
            configured = (engine.get_option(con, "print_folder", "") or "").strip()
            label = "Print-to-location folder"
            back = "/setup/admin"
        raw = (q.get("path") or "").strip()
        if raw:
            cur = Path(raw)
        elif configured:
            cur = Path(configured)
        else:
            cur = Path(engine.DB_PATH).parent
        try:
            cur = cur.resolve()
            while not cur.is_dir() and cur.parent != cur:
                cur = cur.parent
        except Exception:
            cur = Path(engine.DB_PATH).parent
        try:
            subs = sorted(
                (p for p in cur.iterdir()
                 if p.is_dir() and not p.name.startswith(".")),
                key=lambda p: p.name.lower())
            list_err = ""
        except OSError as e:
            subs = []
            list_err = ("<p class='err'>This folder could not be opened. "
                        "Move up to a folder that is available, or pick a "
                        "different folder.</p>")
        rows = ""
        if cur.parent != cur:
            rows += (f"<p style='margin:2px 0'><a href='/setup/folders?for={target}"
                     f"&path={quote_plus(str(cur.parent))}'>\u2191 Up</a></p>")
        rows += "".join(
            f"<p style='margin:2px 0'><a href='/setup/folders?for={target}"
            f"&path={quote_plus(str(p))}'>{html.escape(p.name)}/</a></p>"
            for p in subs)
        if not subs and not list_err:
            rows += "<p class='hint'>No folders here.</p>"
        cur_s = html.escape(str(cur), quote=True)
        return tabs_admin("/setup/admin") + f"""
        <h2>Choose folder \u2014 {label}</h2>
        <p style="margin:4px 0"><b>{html.escape(str(cur))}</b></p>
        {list_err}
        <div style="max-height:300px;overflow:auto;border:1px solid #d0d5dd;padding:6px 10px">{rows}</div>
        <form method=post action="/setup/folders/pick" style="margin-top:8px;display:inline">
          <input type=hidden name=target value="{target}">
          <input type=hidden name=path value="{cur_s}">
          <button>Use this folder</button>
        </form>
        <form method=post action="/setup/folders/pick" style="display:inline">
          <input type=hidden name=target value="{target}">
          <input type=hidden name=path value="">
          <button class="secondary">Use default folder</button>
        </form>
        <a class="btn secondary" href="{back}">Close</a>
        <form method=post action="/setup/folders/new" style="margin-top:10px">
          <input type=hidden name=target value="{target}">
          <input type=hidden name=path value="{cur_s}">
          <div class="frow">
            <div><label>New folder name</label><input name=name class=w-md required maxlength=80></div>
            <div style="align-self:end"><button class="secondary">New Folder</button></div>
          </div>
        </form>
        """

    def _sticky_notes(self, con, q):
        """Sticky notes (2026-10-17 glimpse rules).
        The face is the words + Done + Pin; everything else (priority,
        color, Snooze, edit, peel) lives behind one \u2022\u2022\u2022 per note.
        Snooze is the one defer verb: the minutes stepper (the
        standard, same as everywhere) or pick a day. Still never
        taps, never blocks."""
        try:
            edit_id = int((q or {}).get("sticky_edit") or 0)
        except (TypeError, ValueError):
            edit_id = 0
        try:
            ctl_id = int((q or {}).get("sticky_ctl") or 0)
        except (TypeError, ValueError):
            ctl_id = 0
        colors = {"yellow": "#fff3b0", "pink": "#ffd6e0", "green": "#d3f2d3", "blue": "#d6e8ff"}
        try:
            _std_minutes = int(engine.get_option(con, "ack_snooze_minutes", "30") or 30)
        except (TypeError, ValueError):
            _std_minutes = 30
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
            if sid == ctl_id:
                toggle = "<a class='tiny' href='/'>close</a>"
                ctl = (
                f"<div class='sticky-ctl'>"
                f"<form method='post' action='/today/sticky/update' class='tform'>"
                f"<input type='hidden' name='sticky_id' value='{sid}'>"
                f"<select name='priority' title='Priority'>{pri_sel}</select>"
                f"<select name='color' title='Color'>{col_sel}</select>"
                f"<button title='Apply priority/color'>Set</button></form> "
                f"<form method='post' action='/today/sticky/update' class='tform'>"
                f"<input type='hidden' name='sticky_id' value='{sid}'>"
                f"<input type='hidden' name='snooze' value='minutes'>"
                f"<span class='tiny' style='margin:0 2px'>Snooze:</span>"
                f"<span class='stepper'><button type='button' data-step='-15' title='15 minutes less'>&minus;</button>"
                f"<input type='number' name='minutes' value='{_std_minutes}' min='1' max='10080' step='1' title='Snooze minutes'>m"
                f"<button type='button' data-step='15' title='15 minutes more'>+</button></span>"
                f"<button title='Snooze this note'>Snooze</button></form> "
                f"<form method='post' action='/today/sticky/update' class='tform'>"
                f"<input type='hidden' name='sticky_id' value='{sid}'>"
                f"<input type='hidden' name='snooze' value='pick'>"
                f"<input type='datetime-local' name='snooze_until' title='Pick a day and time'>"
                f"<button title='Snooze until then'>Pick day</button></form> "
                f"<a class='tiny' href='/?sticky_edit={sid}'>edit</a> "
                f"<form method='post' action='/today/sticky/remove' class='tform'>"
                f"<input type='hidden' name='sticky_id' value='{sid}'>"
                f"<button class='tiny' title='No done entry'>Peel off</button></form>"
                f"</div>")
            else:
                toggle = f"<a class='tiny' href='/?sticky_ctl={sid}'>\u2022\u2022\u2022</a>"
                ctl = ""
            rows += (
                f"<div class='sticky' style='background:{bg}'>"
                f"<div>{body}</div>"
                f"<div class='sticky-face'>"
                f"<form method='post' action='/today/sticky/done' class='tform'>"
                f"<input type='hidden' name='sticky_id' value='{sid}'>"
                f"<button class='mini'>Done</button></form> "
                f"<form method='post' action='/today/sticky/update' class='tform'>"
                f"<input type='hidden' name='sticky_id' value='{sid}'>"
                f"<input type='hidden' name='pinned' value='{'0' if s['pinned'] else '1'}'>"
                f"<button class='tiny' title='Pin to top'>{'Unpin' if s['pinned'] else 'Pin'}</button></form> "
                f"{toggle}"
                f"</div>{ctl}</div>")
        return f"""
        <h3>Sticky notes</h3>
        {rows}
        <form method="post" action="/today/sticky/add" class="tform">
        <input name="text" placeholder="New sticky note&hellip;" size="40" maxlength="500">
        <button>Add</button></form>
        """

    def _empty_action(self, title, detail, href, label):
        return (f"<div class='empty-action'><strong>{html.escape(title)}</strong>"
                f"<p>{html.escape(detail)}</p><a class='btn' href='{html.escape(href, quote=True)}'>{html.escape(label)} →</a></div>")

    def _onboarding_card(self, con):
        # The Today onboarding card names the chain steps with their
        # marks (Batch 3 #3) — never a bare count. It retires when the
        # chain is Finished.
        if setup_finished(con):
            return ""
        chain = setup_chain(con)
        if all(s["done"] for s in chain if not s["optional"]):
            return ""
        rows = []
        for s in chain:
            label = (f"Step {s['n']} \u2014 {s['name']}"
                     + (" (optional)" if s["optional"] else ""))
            if s["done"]:
                rows.append(f"<div class='setupstep done'><span>\u2713</span><span>{html.escape(label)}</span></div>")
            else:
                rows.append(f"<div class='setupstep'><span>\u25cb</span><a href='{s['editor']}'>{html.escape(label)} \u2192</a></div>")
        first = next(s for s in chain if not s["done"] and not s["optional"])
        return f"""<section class='onboarding card'>
          <div><span class='eyebrow'>SETUP STATUS</span><h2 style='margin:0'>Complete FleetSheet setup</h2></div>
          <p class='mute' style='margin:4px 0'>Setup runs in the order below. Continue with the first unfinished step; finished steps stay saved.</p>
          <div class='setupsteps'>{''.join(rows)}</div>
          <p class='actions'><a class='btn' href='{first['editor']}'>Continue setup \u2192</a></p>
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
            for i, it in enumerate(items[:DASH_CAP * 2]):
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
                if it.get("nudge"):
                    # The discovery nudge's Dismiss is permanent
                    # (perm=1 through the ack machinery).
                    done_btn += (
                        f" <form method='post' action='/alert/ack' style='display:inline'>"
                        f"<input type='hidden' name='key' value='{html.escape(it.get('key') or '', quote=True)}'>"
                        f"<input type='hidden' name='perm' value='1'>"
                        f"<input type='hidden' name='next' value='/'>"
                        f"<button class='mini' type='submit' name='action' value='dismiss'>Dismiss</button></form>")
                rows += f"<div class='todo tier-{tier}{' extra' if i >= DASH_CAP else ''}'>{link}{done_btn}</div>"
            rows += more_link(len(items), min(len(items), DASH_CAP), "/today/all", "Everything — Today")
            return rows

        # Calm state: nothing must-do today — offer tomorrow's work, no red flashing.
        if not must:
            tomorrow = engine.today_tomorrow(con)
            calm = ("<div class='calm'><b>Nothing due today.</b> "
                    "Tomorrow:</div>" + stack(tomorrow, "must"))
        else:
            calm = ""

        # Working-style order (2026-10-17, Jason): some operators tackle
        # the big things first and work down; others knock out the quick
        # wins first. Both are right \u2014 and the choice is NOT in the
        # user's face: the desk LEARNS it underneath from what he
        # actually completes (see the /today/task/done handler), and
        # today_order follows the evidence. Default is big-first.
        # Tiers keep their styling (gold bar = must-do) wherever they sit.
        order = engine.get_option(con, "today_order", "big")
        must_block = stack(must, "must") + calm
        can_block = stack(can, "can")
        later_block = stack(later, "later")
        if order == "quick":
            stacks_html = can_block + must_block + later_block
        else:
            stacks_html = must_block + can_block + later_block
        today_card = f"""
        <section class="dcard today" data-card="today">
        <h2 class="cardtitle">Today</h2>
        {stacks_html}
        <div class="card-resize" title="Drag to resize"></div>
        </section>"""
        # The standalone Add-a-task element is gone (tweak round
        # 2026-10-20, Jason): the desk already carries tasks on every
        # card and ticker. Sticky notes stay, exactly as they were —
        # this card is theirs now. (The /today/task/add endpoint and
        # the Today work lists are untouched.)
        task_card = f"""
        <section class="dcard" data-card="task">
        {self._sticky_notes(con, q or {})}
        <div class="card-resize" title="Drag to resize"></div>
        </section>"""

        # Billing OFF (shop flow, Jason 2026-10-21): the dashboard's
        # Billing card is a module-fed card — it steps aside whole,
        # pbox included, like the compliance-fed cards do.
        money_pbox = ("" if not engine.module_on(con, "billing") else
                      f'<div class="pbox" data-title="Billing" data-pkey="dashgrid">'
                      f'<div class="card-col">{self._dash_money_card(con)}</div></div>')
        return f"""
        
        {self._onboarding_card(con)}
        {self._pin_nag(con)}
        {_snoozed_section(con)}
        <div class="dashgrid">
        <div class="pbox" data-title="Today" data-pkey="dashgrid"><div class="card-col">{today_card}{task_card}</div></div>
        {money_pbox}
        <div class="pbox" data-title="Assets" data-pkey="dashgrid"><div class="card-col">{self._dash_assets_card(con)}{self._dash_reports_card(con)}</div></div>
        </div>
        {self._done_box(con, "/")}
        {DASH_RESIZE_JS}
        """

    def _dash_money_card(self, con):
        """Dashboard summary: biggest open balances + the four money groups."""
        d = engine.dashboard(con)
        open_inv = sorted(engine.list_open_invoices(con),
                          key=lambda r: r["balance"], reverse=True)
        rows = ""
        for i, r in enumerate(open_inv[:DASH_CAP * 2]):
            rows += (f"<div class='todo{' extra' if i >= DASH_CAP else ''}'><a href='/invoice/{html.escape(r['invoice_no'], quote=True)}'>"
                     f"{html.escape(r['invoice_no'])} — {html.escape(r['account_name'])}</a> "
                     f"<span class='mute'>${r['balance']:,.2f}</span></div>")
        rows += more_link(len(open_inv), min(len(open_inv), DASH_CAP), "/money/audit", "All money — audit")
        return f"""
        <section class="dcard hidephone" data-card="billing">
        <h2 class="cardtitle">Billing <a class="full" href="/money">view →</a></h2>
        <div class="mstat"><span>Open AR</span><b>${d['open_ar']:,.2f}</b></div>
        <p class="hint">ready to bill ${d['ready_amt']:,.2f}</p>
        {rows or "<p class='mute'>Nothing outstanding.</p>"}
        <div class="card-resize" title="Drag to resize"></div>
        </section>"""

    def _dash_assets_card(self, con):
        """Dashboard summary: what needs paper — glimpse form (2026-10-17):
        the single worst item as a line, the rest behind the link; the
        count never headlines. (Idle iron lives on the Assets tab.)"""
        paper, _idle, _idle_day, _idle_other = self._asset_lists(con)
        if not engine.module_on(con, "compliance"):
            # Compliance OFF (shop-flow, Jason 2026-10-21): the paperwork
            # section steps aside; the card falls back to a plain units
            # summary — the fleet is still the fleet.
            _total = con.execute(
                "SELECT COUNT(*) FROM assets WHERE active=1").fetchone()[0]
            return f"""
        <section class="dcard hidephone" data-card="assets">
        <h2 class="cardtitle">Assets <a class="full" href="/assets">view \u2192</a></h2>
        <p>{_total} active unit{'s' if _total != 1 else ''} · {len(_idle)} idle</p>
        <div class="card-resize" title="Drag to resize"></div>
        </section>"""
        worst = ""
        if paper:
            p0 = paper[0]
            worst = (f"<div class='todo'><a href='{html.escape(p0['h'], quote=True)}'>"
                     f"{html.escape(p0['t'])}</a></div>")
            worst += more_link(len(paper), 1, "/assets/all", "All assets")
        return f"""
        <section class="dcard hidephone" data-card="assets">
        <h2 class="cardtitle">Assets <a class="full" href="/assets">view \u2192</a></h2>
        <h3>Needs paperwork</h3>
        {worst or "<p class='mute'>Nothing due.</p>"}
        <div class="card-resize" title="Drag to resize"></div>
        </section>"""

    def _dash_reports_card(self, con):
        """Dashboard summary: compliance is a one-line pointer now
        (Batch 3 #18) \u2014 the grouped count and the worst unit,
        linking to Compliance. No per-row echoes: the ticker and the
        Compliance page carry the items."""
        if not engine.module_on(con, "compliance"):
            return ""
        groups = engine.compliance_groups(con)
        pointer = ""
        if groups:
            total = sum(g["total"] for g in groups)
            w0 = groups[0]
            pointer = (f"<div class='todo'><a href='/compliance'>"
                       f"{len(groups)} unit{'s' if len(groups) != 1 else ''} \u00b7 "
                       f"{total} item{'s' if total != 1 else ''} \u2014 worst "
                       f"{html.escape(w0['unit_no'])}</a></div>")
        return f"""
        <section class="dcard hidephone" data-card="compliance">
        <h2 class="cardtitle">Compliance <a class="full" href="/compliance">view \u2192</a></h2>
        {pointer or "<p class='mute'>Nothing due.</p>"}
        <div class="card-resize" title="Drag to resize"></div>
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
        <p class="hint"><a href="/">Back to Today</a>.</p>
        <p class="hint"><input id="auditq" placeholder="Filter" size="30"
        oninput="var q=this.value.toLowerCase();document.querySelectorAll('div.todo').forEach(function(d){{d.style.display=d.textContent.toLowerCase().indexOf(q)>=0?'':'none';}})"></p>
        {body or "<p class='mute'>Nothing open.</p>"}
        """

    def _print_menu(self, screen=None, pdf=None, page=False, compact=False,
                    docs=None):
        """The Print button, globally (Jason 2026-10-18): one button, three
        choices — Print to Screen (the document on screen), Print to
        Location (filed into the operator's print folder), PRINT (the
        printer of their choice, via the browser's print dialog).
        page=True for form pages: the choices act on the current page,
        live values included. Otherwise screen/pdf are /print/ paths.
        docs=[(label, screen, pdf), ...] (build 'aa', 2026-10-26,
        JC-AA1): a kind whose printable papers are several documents
        (the Rental's Work Ticket and Delivery Ticket) gets ONE Print
        control whose menu carries one three-choice entry per
        document — never a standalone print link per paper."""
        sumcls = "pmenu-link" if compact else "pmenu-sum"
        if docs:
            groups = ""
            for _lab, _scr, _pdf in docs:
                _sep = "&" if "?" in (_scr or "") else "?"
                groups += (
                    f'<span class="hint" style="display:block">'
                    f'{html.escape(_lab)}</span>'
                    f'<a href="{html.escape(_scr or "", quote=True)}" target="_blank" rel="noopener">Print to Screen</a>'
                    f'<a href="{html.escape(_scr or "", quote=True)}{_sep}autoprint=1" target="_blank" rel="noopener">PRINT</a>'
                    f'<button type=button data-doc="{html.escape(_pdf or _scr or "", quote=True)}" onclick="fsSaveLoc(this)">Print to Location</button>')
            return (f'<details class="pmenu"><summary class="{sumcls}">Print</summary>'
                    f'<div class="popts">{groups}<span class="pstat"></span></div></details>')
        if page:
            opts = ('<button type=button onclick="fsPrintScreen()">Print to Screen</button>'
                    '<button type=button onclick="window.print()">PRINT</button>'
                    '<button type=button onclick="fsSavePage(this)">Print to Location</button>')
        else:
            sep = "&" if "?" in (screen or "") else "?"
            opts = (f'<a href="{html.escape(screen or "", quote=True)}" target="_blank" rel="noopener">Print to Screen</a>'
                    f'<a href="{html.escape(screen or "", quote=True)}{sep}autoprint=1" target="_blank" rel="noopener">PRINT</a>'
                    f'<button type=button data-doc="{html.escape(pdf or screen or "", quote=True)}" onclick="fsSaveLoc(this)">Print to Location</button>')
        return (f'<details class="pmenu"><summary class="{sumcls}">Print</summary>'
                f'<div class="popts">{opts}<span class="pstat"></span></div></details>')

    def _company_band(self, con):
        """The company block in the printed invoice's format, for editor
        screens (laptop-pass fix round, 2026-10-20): 'Remit To:' over the
        company name, then street / optional line 2 / City, ST ZIP /
        phone / email, one per line — the same lines the invoice prints,
        from the same company record (split addr_* columns, legacy
        single-address fallback). Editor headers pair this block (left)
        with the form's number + date (right) so every form's screen
        opens the way the invoice does."""
        co = self.company(con)
        def g(k):
            try:
                v = co[k]
            except Exception:
                v = ""
            return str(v or "").strip()
        lines = []
        street = g("addr_street")
        street2 = g("addr_street2")
        cityline = ", ".join(x for x in (
            g("addr_city"),
            " ".join(y for y in (g("addr_state"), g("addr_zip")) if y)) if x)
        if street or street2 or cityline:
            lines = [x for x in (street, street2, cityline) if x]
        elif g("address"):
            lines = [g("address")]
        lines += [x for x in (g("phone"), g("billing_email")) if x]
        body = "<br>".join(html.escape(x) for x in lines)
        return (
            "<div style='min-width:220px'>"
            "<div style='font-size:10px;color:#5C6B7A;text-transform:uppercase'>Remit To:</div>"
            f"<div style='font-weight:700;color:var(--frame)'>{html.escape(g('name'))}</div>"
            f"<div style='font-size:12px'>{body}</div></div>")

    def _btn_row(self, save_label="Save", jobpop=None, add_item=False, extra="",
                 submit_name="", submit_value="", print_menu=None,
                 edit_pop=None):
        """The universal form row (Jason 2026-10-26, void-and-revise
        ruling): ONE row, split — LEFT cluster, the content doors
        (Add Item, Job Info, Edit); RIGHT cluster, the action doors
        (Print, Save). Edit stands only in the locked-open state of
        a posted document's form and opens the revision prompt
        (edit_pop names the prompt's element); new/draft forms
        carry no Edit. The split governs placement, not which
        doors a form has: a form whose row never carried Add Item
        still lacks it.
        save_label=None in the locked-open state (edit_pop set)
        renders Save disabled — present per the template, inert
        while locked (build 'am', Jason 2026-10-28); without
        edit_pop it omits Save (forms whose commit is their own,
        carried in extra by the form).
        submit_name/submit_value put a discriminator on the Save
        submit. print_menu overrides the row's Print menu HTML —
        the invoice editor passes the DOCUMENT menu in edit mode;
        everywhere else the row's Print acts on the current page,
        live values included."""
        left = []
        if add_item:
            left.append('<button type=button>Add Item</button>')
        if jobpop:
            left.append(f'<button type=button onclick="document.getElementById(\'{jobpop}\').style.display=\'block\'">Job Info</button>')
        if edit_pop:
            left.append(f'<button type=button onclick="document.getElementById(\'{edit_pop}\').style.display=\'block\'">Edit</button>')
        right = []
        right.append(print_menu if print_menu is not None else self._print_menu(page=True))
        if save_label is None and edit_pop:
            # Build 'am' (Jason 2026-10-28): Save stands on the
            # locked form too — the universal row carries it in
            # every state. Locked, it is inert (disabled): the
            # record stands until Edit opens the revision, whose
            # form carries the live Save. Presence is the template;
            # the state governs whether it acts.
            right.append('<button type=button disabled>Save</button>')
        if save_label is not None:
            attrs = (f' name="{submit_name}" value="{submit_value}"'
                     if submit_name else '')
            right.append(f'<button type=submit{attrs}>{save_label}</button>')
        # Build 'ac' (Jason 2026-10-27, defect C-5): the two cluster
        # spans carry the row's own text context (14px, no transform)
        # inline. A row standing inside a .card — the Petty cards —
        # otherwise inherits .card span's 12px uppercase context and
        # its buttons render small; the row's size is the row's own,
        # wherever the row stands.
        # Build 'af' (Jason 2026-10-28): one gap standard — the tab
        # strips' flex gap:8px — between the buttons WITHIN each
        # cluster too (the clusters were single-space joins and
        # `extra` rode glued to the last button): each cluster is an
        # inline-flex row with gap:8px, and extra joins the right
        # cluster as its last item.
        _right = "".join(right) + extra
        return (f'<div style="display:flex;justify-content:space-between;'
                f'align-items:center;gap:8px">'
                f'<span style="display:inline-flex;gap:8px;align-items:center;'
                f'font-size:14px;text-transform:none">{"".join(left)}</span>'
                f'<span style="display:inline-flex;gap:8px;align-items:center;'
                f'text-align:right;font-size:14px;text-transform:none">{_right}</span></div>')

    # The locked-open revision model (Jason 2026-10-26, build 'ab'):
    # a form opened on an existing posted/issued document renders
    # LOCKED — the record: viewable, printable — and its Edit door
    # opens the revision prompt; confirming voids the original and
    # lands the operator on the revision's own form, unlocked,
    # under the engine's session marker. The POST layer is the real
    # lock: no in-place save of an existing document lands without
    # that marker.
    _LOCK_JS = (
        "<script>(function(){var f=document.currentScript.closest('form')"
        "||document.querySelector('form');if(!f)return;"
        # Build 'al' (Jason 2026-10-28): the locked form SAYS it is
        # locked — a red Locked box stands at the form's head
        # (screen only; the print CSS removes .lockbanner). The
        # banner is this script's furniture, like the disabling
        # below: one seat, every locked form.
        "if(!f.querySelector('.lockbanner')){var b=document.createElement('div');"
        "b.className='lockbanner';b.textContent='LOCKED';"
        "f.insertBefore(b,f.firstChild);}"
        "f.querySelectorAll('input,select,textarea').forEach(function(el){"
        "if(el.type==='hidden')return;"
        "if(el.closest('.wpop'))return;"
        "el.disabled=true;});})();</script>")

    def _revto_line(self, con, kind, row):
        """Build 'al' (Jason 2026-10-28): the voided original's
        top line — *Revised to: <the revision's number> — for its
        summary (the review surface). The printed document carries
        the same line from printpack. Empty for a document that
        was not revised away."""
        if row is None:
            return ""
        try:
            info = engine.revision_info(con, kind, row)
        except Exception:
            return ""
        if not info.get("revised_by"):
            return ""
        return (f'<div class="revto">*Revised to: '
                f'{html.escape(str(info["revised_by"]))}</div>')

    def _revise_popup(self, con, kind, ref):
        """The revision prompt (a form popup under the popup law):
        Reason (required) and the operator's Name (required,
        prefilled with the desk user). Its Confirm posts the host
        form to /revise — in the locked render the only enabled
        fields are the hidden kind/ref and these two, so the post
        carries exactly the act. Confirming voids the original and
        creates the revision (JC-AB0)."""
        inner = (
            f'<input type=hidden name=rev_kind value="{html.escape(kind, quote=True)}">'
            f'<input type=hidden name=rev_ref value="{html.escape(str(ref), quote=True)}">'
            f'<div><label>Reason</label>'
            f'<input name=rev_reason style="width:100%" required></div>'
            f'<div><label>Name</label>'
            f'<input name=rev_name value="{html.escape(self.desk(con), quote=True)}" required></div>'
            f'<p>Save voids this document and opens its revision. '
            f'The record keeps the void, the reason, and the name.</p>'
            f'<button type=submit formaction="/revise" formmethod="post">'
            f'Save</button>')
        return self._pop_wrap("revpop", f"Revise {ref}", inner)

    def _chain_facts(self, con, kind, row, summary_url):
        """The revision chain stated in a summary's fact table
        (Jason 2026-10-26): a voided document shows Revised by +
        the signed void (Reason, By); a revision shows Revision of
        + the reason and name it was created with. summary_url maps
        a document number to its summary URL for this kind."""
        info = engine.revision_info(con, kind, row)
        facts = []
        if info["revised_by"]:
            facts.append(("Status", "Void"))
            facts.append(("Revised by",
                          f'<a href="{summary_url(info["revised_by"])}">'
                          f'{html.escape(info["revised_by"])}</a>'))
        if info["revision_of"]:
            facts.append(("Revision of",
                          f'<a href="{summary_url(info["revision_of"])}">'
                          f'{html.escape(info["revision_of"])}</a>'))
        if info["revised_by"] or info["revision_of"]:
            facts.append(("Reason", html.escape(info["reason"] or "")))
            byline = info["by"] or ""
            if info["at"]:
                byline = (byline + " · " if byline else "") + info["at"]
            facts.append(("By", html.escape(byline)))
        return facts

    def _top_commit(self, label, name="", value=""):
        """The form's commit/finish button, up top (Jason 2026-10-21):
        one placement pattern everywhere a top commit appears — a
        right-aligned bar at the top of the form body, just under the
        company band / form-# band. name/value carry the discriminator
        when the same form also has a row Save (Invoice)."""
        attrs = f' name="{name}" value="{value}"' if name else ''
        return (f'<div style="text-align:right;margin:2px 0 6px">'
                f'<button type=submit{attrs}>{label}</button></div>')

    def _line_head(self, last="Rate $"):
        """The one header band above the first line-item row (tweak
        round 2026-10-20, Jason): the change-order table's header-bar
        coloring (#e8eef4), placed ONCE per line editor — never per
        row. Add Item clones rows only, so adding rows adds no bands.
        Grid editors share the rows' six-column template."""
        labels = ("Type", "Item", "Description", "Qty", "Unit", last)
        spans = "".join(f"<span>{l}</span>" for l in labels)
        return f'<div class="linehead" aria-hidden="true">{spans}</div>'

    def _job_info_popup(self, pid, vals=None, extra=""):
        """Universal job info popup with all 9 fields (Jason 2026-10-07).
        Identical on Sales Ticket, Rental, Quote, Invoice, Credit Memo.
        `extra` (build 'r', Jason 2026-10-25): the host form's own
        fields that used to stand above the line items — required
        fields especially — rendered at the top of the popup, inside
        the same form, with their names and mechanics unchanged, so
        they save with the form exactly as before."""
        v = vals or {}
        def g(k): return html.escape(str(v.get(k) or ''), quote=True)
        _furn = self._pop_furniture(pid, f"refreshJobInfo('{pid}')")
        return f"""
          <div id="{pid}" class="wpop" style="display:none;position:fixed;top:8%;left:8%;right:8%;background:white;border:2px solid #333;padding:18px;z-index:1000;max-height:84%;overflow:auto">
            <h3 class="wpop-h" style="margin-top:0">Job info {_furn}</h3>
            {extra}
            <div class="row"><div><label>Job Name</label><input name=job_name value="{g('job_name')}"></div><div><label>Job Location</label><input name=job_location value="{g('job_location')}"></div></div>
            <div class="row3"><div><label>PO #</label><input name=po value="{g('po')}" class=w-sm></div><div><label>Well #</label><input name=well_no value="{g('well_no')}" class=w-sm></div><div><label>AFE #</label><input name=afe value="{g('afe')}" class=w-sm></div></div>
            <div class="row3"><div><label>Contact Name</label><input name=contact_name value="{g('contact_name')}"></div><div><label>Phone</label><input name=contact_phone value="{g('contact_phone')}" class=w-sm></div><div><label>Email</label><input name=contact_email value="{g('contact_email')}"></div></div>
            <div class="row"><div><label>Cost Code</label><input name=cost_code value="{g('cost_code')}" class=w-sm></div><div><label>Reference Ticket #</label><input name=ticket_ref value="{g('ticket_ref')}" class=w-sm></div></div>
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

    def view_ticker_panel(self, con, q):
        """Popup controls (Jason 2026-10-23): the ticker filter
        popover's refresh endpoint — serves ONLY the popover (the
        client fetches it with frag=1 and swaps the panel in place),
        with the saved category set as it stands right now."""
        q = q or {}
        try:
            cats = engine.get_ticker_cats(con)
        except Exception:
            cats = None
        return tickf_html(cats, q.get("next") or "/")

    def view_setup(self, con, q):
        c = self.company(con)
        if (q.get("edit") or "") == "1":
            return self._setup_form(con, c)
        # Setup chain (Batch 3 #3): during a setup run, clicking Setup
        # lands directly on the Company form (step 1) — no summary
        # landing first. After Finished, the summary.
        try:
            if setup_chain_active(con):
                return self._setup_form(con, c)
        except Exception:
            pass
        return self._setup_summary(con, c)

    def view_setup_vendors(self, con, q=None):
        q = q or {}
        msg = (q.get("msg") or "").strip()
        banner = f"<p class='ok'>{html.escape(msg)}</p>" if msg else ""
        return tabs_admin("/setup/vendors", con=con) + banner + self._vendor_block(con, q)

    def view_setup_billing(self, con, q=None):
        c = self.company(con)
        def g(k, default=""):
            try:
                v = c[k]
                return default if v is None else str(v)
            except Exception:
                return default
        _jb_raw = engine.get_option(con, "inv_jobinfo_fields", "po,job,well,location,taxexempt") or ""
        _jb_fields = {t.strip() for t in _jb_raw.split(",") if t.strip()}
        # Spec 7 curation panels: the FULL master list per kind, each
        # value checked iff it is in the book's enabled set, plus an
        # "Add your own" input per panel (saved by _post_setup_billing
        # into the master list AND the enabled set). Item 6
        # (2026-10-20): each entry also carries a small ✕ delete
        # button and each panel a "Restore factory list" button; both
        # are submit buttons with a formaction override (the panels
        # live inside the billing form, so no nested forms) posting
        # to their own routes in post_core.
        def _en_panel(kind, legend, new_name):
            master = engine.lookups(con, kind)
            en = set(enabled_values(con, kind))
            boxes = "".join(
                f'<span class="en-item">'
                f'<label><input type=checkbox name=en_{kind}_{i} '
                f'value="{html.escape(vv, quote=True)}"'
                f'{" checked" if vv in en else ""}><span class="en-txt">{html.escape(vv)}</span></label>'
                f'<button type=submit name=del_{kind} '
                f'value="{html.escape(vv, quote=True)}" '
                f'formaction="/setup/billing/lookup/del" formmethod=post '
                f'title="Delete this entry from the master list" '
                f'aria-label="Delete {html.escape(vv, quote=True)} from the master list" '
                f'onclick="return confirm(\'Delete this entry from the master list? Documents that already use it keep it as written.\')" '
                f'style="background:none;border:0;color:var(--bad);cursor:pointer;font-weight:700;padding:0 3px">&#10005;</button></span>'
                for i, vv in enumerate(master))
            return (
                f'<fieldset style="margin-top:12px;padding:8px 12px 10px">'
                f'<input type=hidden name=panel_{kind} value=1>'
                f'<legend>{legend}</legend>'
                f'<div style="margin-bottom:6px;display:flex;gap:14px;align-items:end;flex-wrap:wrap">'
                f'<div><label>Add your own</label>'
                f'<input name={new_name} class="w-md en-new" placeholder="New entry"></div>'
                f'<div><button type=submit class=secondary name=add_{kind} value=1 '
                f'title="Add to this list, switched on">Add</button></div>'
                f'<div><button type=submit class=secondary name=restore_kind value={kind} '
                f'formaction="/setup/billing/lookup/restore" formmethod=post '
                f'onclick="return confirm(\'Restore the factory list? Factory entries come back, the factory-on set is restored, and your added entries stay.\')">Restore All</button></div>'
                f'</div>'
                f'<div class="jb-grid" style="max-height:7.5em;overflow-y:auto">{boxes}</div>'
                f'</fieldset>')
        # Billing switch split (shop flow, Jason 2026-10-21): this page
        # mixes money-only settings with shared line vocabulary. Billing
        # OFF hides ONLY the money-only parts — invoice prefix, billing
        # email, default payment terms, the rental-billing-day defaults
        # (minimum days, bill-both-dates), the printed-invoice Job Info
        # fieldset, and the Payment terms curation panel. What STAYS:
        # default quote validity (quotes vocabulary) and the Units,
        # Items, and Compliance documents panels — units/items are the
        # shared line vocabulary for tickets and work orders too.
        _billing_on = engine.module_on(con, "billing")
        # Five columns (Jason 2026-10-25, build 'r', facelift item 5):
        # one column per option group, options straight down, each
        # column scrollable — the page no longer scrolls long. The
        # census found SIX groups; the printed-invoice Job Info
        # fieldset rides in column 1 with the billing defaults (it is
        # an invoice-print setting; its POST names are unchanged).
        _p_terms = (_en_panel("terms", "Payment Terms", "new_terms")
                    if _billing_on else "")
        _p_uom = _en_panel("inv_uom", "Line Units", "new_inv_uom")
        _p_item = _en_panel("inv_item", "Line Items", "new_inv_item")
        _p_comp = _en_panel("comp_doc", "Compliance Documents", "new_comp_doc")
        # Build 'af' (Jason 2026-10-28): every document kind's number
        # stem stands in this card beside the invoice prefix — the
        # invoice stem lives on the company record; the rest are
        # options (prefix_<kind>) read at mint time by
        # engine.doc_prefix, the field showing the effective stem.
        _pfx = {k: engine.doc_prefix(con, k) for k in
                ("quote", "wo", "sale", "ticket", "change", "cm",
                 "pay", "batch", "cash", "petty")}
        # Build 'r': the defaults stack straight down their column —
        # class "brow", not the grid class "row" (a two-cell grid row
        # in a narrow column strands its second field alone).
        _money_rows = (f"""
          <div class="brow">
            <div><label>Invoice Number Prefix</label><input name=invoice_prefix class=w-xs maxlength=6 value="{html.escape(g('invoice_prefix'))}"></div>
            <div><label>Billing Email</label><input name=billing_email type=email class=w-md value="{html.escape(g('billing_email'))}"></div>
          </div>
          <div class="brow">
            <div><label>Quote Number Prefix</label><input name=prefix_quote class=w-xs maxlength=6 value="{html.escape(_pfx['quote'])}"></div>
            <div><label>Work Order Number Prefix</label><input name=prefix_wo class=w-xs maxlength=6 value="{html.escape(_pfx['wo'])}"></div>
          </div>
          <div class="brow">
            <div><label>Sale Number Prefix</label><input name=prefix_sale class=w-xs maxlength=6 value="{html.escape(_pfx['sale'])}"></div>
            <div><label>Rental Ticket Number Prefix</label><input name=prefix_ticket class=w-xs maxlength=6 value="{html.escape(_pfx['ticket'])}"></div>
          </div>
          <div class="brow">
            <div><label>Change Order Number Prefix</label><input name=prefix_change class=w-xs maxlength=6 value="{html.escape(_pfx['change'])}"></div>
            <div><label>Credit Memo Number Prefix</label><input name=prefix_cm class=w-xs maxlength=6 value="{html.escape(_pfx['cm'])}"></div>
          </div>
          <div class="brow">
            <div><label>Payment Number Prefix</label><input name=prefix_pay class=w-xs maxlength=6 value="{html.escape(_pfx['pay'])}"></div>
            <div><label>Payment Batch Number Prefix</label><input name=prefix_batch class=w-xs maxlength=6 value="{html.escape(_pfx['batch'])}"></div>
          </div>
          <div class="brow">
            <div><label>Cash Entry Number Prefix</label><input name=prefix_cash class=w-xs maxlength=6 value="{html.escape(_pfx['cash'])}"></div>
            <div><label>Petty Cash Entry Number Prefix</label><input name=prefix_petty class=w-xs maxlength=6 value="{html.escape(_pfx['petty'])}"></div>
          </div>
          <div class="brow">
            <div><label>Default Payment Terms</label>{lookup_select(con, "terms", "default_terms", current=g('default_terms','Net 30'))}</div>
            <div><label>Minimum Rental Billing Days</label><input name=min_days type=number min=1 class=w-xs value="{html.escape(g('min_days','1'))}"></div>
          </div>""" if _billing_on else "")
        _both_dates = (f"""
            <div style="align-self:end;padding-bottom:2px"><label><input type=checkbox name=bill_both_dates value=1 {"checked" if g('bill_both_dates','0') in ('1','True') else ""}> Bill both the on-rent and off-rent dates</label></div>""" if _billing_on else "")
        _jobinfo = (f"""
          <fieldset style="margin-top:12px;padding:8px 12px 10px">
            <legend>Job Info box on printed invoices</legend>
            <p class="hint" style="margin:2px 0 6px">Prints on the invoice. Maximum 7. Checked prints even when blank; none checked, no box.</p>
            <div class="jb-grid">{"".join(f'<label><input type=checkbox name=jb_{k} value=1 {"checked" if k in _jb_fields else ""}> {label}</label>' for k, label in (("po", "PO #"), ("well", "Well #"), ("afe", "AFE #"), ("cost_code", "Cost Code"), ("job", "Job Name"), ("contact_name", "Contact Name"), ("contact_phone", "Phone"), ("contact_email", "Email"), ("ticket_ref", "Reference Ticket #"), ("job_notes", "Notes"), ("location", "Job Location"), ("taxexempt", "Tax-exempt")))}</div>
            <!-- Attach File is not in this list: it is an upload, not a printable line — its documents already ride with the invoice as attached paperwork. Maximum 7: at most seven checked fields print, in the fixed Job Info print order (follow-up, 2026-10-20: PO # top, Tax-exempt bottom). -->
          </fieldset>
          <script>
          /* Job Info cap (polish round, 2026-10-20): Maximum 7 — when
             seven boxes are checked, the remaining unchecked boxes are
             disabled; unchecking one re-enables them. The server also
             caps the stored set at seven, so this is a convenience,
             not the guarantee. */
          (function(){{
            var boxes = Array.prototype.slice.call(document.querySelectorAll('input[type="checkbox"][name^="jb_"]'));
            if (!boxes.length) return;
            function sync(){{
              var checked = boxes.filter(function(b){{ return b.checked; }}).length;
              boxes.forEach(function(b){{ b.disabled = !b.checked && checked >= 7; }});
            }}
            boxes.forEach(function(b){{ b.addEventListener("change", sync); }});
            sync();
          }})();
          </script>""" if _billing_on else "")
        _banner = chain_banner(con, "billing")
        # Jurisdictions pointer (Jason, Oct 23): on the Billing setup
        # page permanently, not only during the chain. Jurisdictions
        # are chosen per Job Site and per ticket — this says where, in
        # plain words, with one notice: the selection is the
        # operator's responsibility. No advice, no recommendation of
        # any jurisdiction or rate.
        _jur = ("<section class='card'><p style='margin:0'>"
                "Tax jurisdiction: chosen per Job Site (Tax location) "
                "and per Rental Ticket. FleetSheet never picks one. The "
                "selection is the operator's responsibility."
                "</p></section>")
        # The defaults explanation lives in the manual (pack 'm',
        # Fix 5: explanations off the page, military style on it).
        return tabs_admin("/setup/billing") + _banner + _jur + f"""
        <form method=post action="/setup/billing">
          <p class="hint" style="margin:2px 0 8px">Ticked = offered in pickers. &#10005; removes from the master list; documents keep entries as written.</p>
          <div class="billgrid">
            <div class="billcol"><fieldset style="padding:8px 12px 10px"><legend>Billing Defaults</legend>{_money_rows}
              <div class="brow">
                <div><label>Default quote validity (days)</label><input name=quote_valid_days type=number min=1 class=w-xs value="{html.escape(engine.get_option(con, 'quote_valid_days', '30'))}"></div>{_both_dates}
              </div></fieldset>{_jobinfo}</div>
            <div class="billcol">{_p_terms}</div>
            <div class="billcol">{_p_uom}</div>
            <div class="billcol">{_p_item}</div>
            <div class="billcol">{_p_comp}</div>
          </div>
          <script>
          /* Add-your-own Enter key (laptop-pass fix round, 2026-10-20):
             Enter inside a panel's new-entry input clicks THAT panel's
             Add button. Without this, implicit submission fires the
             form's first submit button — an entry's delete ✕. */
          (function(){{
            document.querySelectorAll('input.en-new').forEach(function(inp){{
              inp.addEventListener('keydown', function(e){{
                if (e.key !== 'Enter') return;
                e.preventDefault();
                var fs = inp.closest('fieldset');
                var btn = fs && fs.querySelector('button[name^="add_"]');
                if (btn) btn.click();
              }});
            }});
          }})();
          </script>
          <p class=actions style="justify-content:flex-end"><button>Save</button></p>
        </form>
        """

    def view_setup_admin(self, con, q=None):
        b = engine.backup_status(con)
        last = html.escape(fmt_datetime(b.get("last"), "never"))
        status = "Overdue — older than 7 days" if b.get("stale") else "Up to date"
        _updater_on = (updater_winsparkle is not None
                       and updater_winsparkle.available())
        # Menu-only updates (decision B): the check runs only when the
        # operator clicks the button below — never on its own.
        # Update folded into Version (Jason 2026-10-21), and build
        # 'ac' (Jason 2026-10-27): the standalone Version card is
        # gone too — the version line and the check control stand in
        # the System Administration card's lower area, right of
        # Backup Settings (below), behavior intact.
        updates_inner = """
          <form method=post action="/updater/check"><p class=actions><button>Check for Updates…</button></p></form>""" if _updater_on else """
          <p class='hint'>Update checks are not available in this install.</p>"""

        try:
            _ver = (Path(__file__).resolve().parent / "VERSION").read_text(
                encoding="ascii").strip() or "dev"
        except OSError:
            _ver = "dev"
        # Readouts show the prose form (Item H renumber): the VERSION
        # stamp is the three-number machinery form (1.1.1); the
        # display reads "1.1". Non-numeric stamps ("dev") pass through.
        _ver_parts = _ver.split(".")
        if len(_ver_parts) == 3 and _ver_parts[2] == "0":
            _ver = ".".join(_ver_parts[:2])
        _pf = engine.get_option(con, "print_folder", "") or ""
        _bdir = con.execute("SELECT backup_dir FROM company WHERE id=1").fetchone()
        _bdir = (_bdir["backup_dir"] if _bdir else "") or ""
        # Chain step 7 save (Batch 3 #3): the layout toggles are
        # client-side, so while the layout stop is the chain stop in
        # play the card carries the step's save form. It renders only
        # then — outside the chain it would be a useless button.
        _layout_save = ""
        if chain_layout_current(con, q):
            _layout_save = f"""
          <form method=post action="/setup/admin">
            <input type=hidden name=backup_dir value="{html.escape(_bdir, quote=True)}">
            <input type=hidden name=chain_step value="layout">
            <p class=actions><button>Save</button></p>
          </form>"""
        # Build 'ac' (Jason 2026-10-27, Administration squeeze):
        # the Layout and Collapsible Headers blocks merge into one
        # compact control-row set under one one-line hint — every
        # control keeps, the second block heading goes.
        layout_card = f"""
        <section class=card id="layout">
          <h2>Page Layout</h2>
          <p class=mute>Two layouts: Main and Alternate — each saves its own arrangement and locks on its own.</p>
          <p>Layout: <b data-layout-slot>Main</b> <b data-layout-state>Locked</b>.
          <button type=button class="secondary" onclick="window.FSLayoutSlotSet&&window.FSLayoutSlotSet('Main')">Main</button>
          <button type=button class="secondary" onclick="window.FSLayoutSlotSet&&window.FSLayoutSlotSet('Alternate')">Alternate</button>
          <button type=button class="secondary" onclick="window.FSLayoutToggle&&window.FSLayoutToggle()">Lock / unlock layout</button></p>
          <script>try{{var _s=localStorage.getItem('fs-layout-slot');var _slot=(_s==='Alternate')?'Alternate':'Main';var _l=localStorage.getItem('fs-layout-locked:'+_slot);if(_l===null)_l=localStorage.getItem('fs-layout-locked');document.querySelectorAll('[data-layout-slot]').forEach(function(el){{el.textContent=_slot;}});document.querySelectorAll('[data-layout-state]').forEach(function(el){{el.textContent=(_l==='0')?'Unlocked':'Locked';}});}}catch(e){{}}</script>
          <p>Collapsed headers: <b data-collapse-state>Unlocked</b>.
          <button type=button class="secondary" onclick="window.FSCollapseToggle&&window.FSCollapseToggle()">Lock / unlock collapsed headers</button></p>
          <script>try{{var _c=localStorage.getItem('fs-collapse-locked');document.querySelectorAll('[data-collapse-state]').forEach(function(el){{el.textContent=(_c==='1')?'Locked':'Unlocked';}});}}catch(e){{}}</script>
          {_layout_save}
        </section>"""
        # "What your shop does" (shop-flow, Jason 2026-10-21): the module
        # switches. Factory = everything on, a rental shop run the full
        # way; an off switch hides that work's surfaces only — records
        # are never touched, and flipping it back restores every surface.
        def _mchk(name):
            return " checked" if engine.module_on(con, name) else ""
        # Switch labels are formal noun phrases (Batch 3 #11); the
        # module KEYS (name=mod_<key>) are unchanged.
        shop_card = f"""
        <section class=card>
          <h2>What your shop does</h2>
          <p class=mute>One switch per kind of work; off hides that work's pages and tabs. Records are never touched.</p>
          <form method=post action="/setup/admin">
            <input type=hidden name=backup_dir value="{html.escape(_bdir, quote=True)}">
            <input type=hidden name=modules value=1>
            <input type=hidden name=chain_step value="layout">
            <p><label><input type=checkbox name=mod_rentals value=1{_mchk("rentals")}> Rentals</label></p>
            <p><label><input type=checkbox name=mod_work_orders value=1{_mchk("work_orders")}> Repair and service jobs</label></p>
            <p><label><input type=checkbox name=mod_compliance value=1{_mchk("compliance")}> Certificates, inspections, due dates</label></p>
            <p><label><input type=checkbox name=mod_quotes value=1{_mchk("quotes")}> Quotes</label></p>
            <p><label><input type=checkbox name=mod_condition value=1{_mchk("condition")}> Condition records</label></p>
            <p><label><input type=checkbox name=mod_billing value=1{_mchk("billing")}> Billing</label></p>
            <p class=actions><button class="secondary">Save</button></p>
          </form>
        </section>"""
        printing_card = f"""
        <section class=card>
          <h2>Printing</h2>
          <p class=mute>Print to Location files documents into this folder.</p>
          <form method=post action="/setup/admin">
            <input type=hidden name=backup_dir value="{html.escape(_bdir, quote=True)}">
            <input type=hidden name=chain_step value="admin">
            <div class="frow">
              <div><label>Print-to-location folder</label>
              {folder_field("print", _pf)}</div>
              <div style="align-self:end"><button class="secondary">Save</button></div>
            </div>
          </form>
        </section>"""
        _ts = engine.get_option(con, "ui_text_size", "standard")
        if _ts not in ("standard", "large", "xlarge"):
            _ts = "standard"
        def _tsel(v):
            return " selected" if _ts == v else ""
        zoom_card = f"""
        <section class=card>
          <h2>Zoom</h2>
          <p class=mute>Zoom scales every page up or down; the setting stays in place.</p>
          <form method=post action="/setup/admin">
            <input type=hidden name=backup_dir value="{html.escape(_bdir, quote=True)}">
            <input type=hidden name=chain_step value="layout">
            <div class="frow">
              <div><label>Zoom</label>
              <select name=text_size class=w-sm>
                <option value="standard"{_tsel("standard")}>Standard</option>
                <option value="large"{_tsel("large")}>Large</option>
                <option value="xlarge"{_tsel("xlarge")}>Extra large</option>
              </select></div>
              <div style="align-self:end"><button class="secondary">Save</button></div>
            </div>
          </form>
        </section>"""
        # Tightened layout (laptop-pass fix round, 2026-10-20, Jason):
        # the cards pair up in two columns instead of seven full-width
        # strips with their right halves empty. CSS columns, not a
        # grid (look-see batch 2, 2026-10-21): a grid couples the
        # columns through shared rows, so a short card left dead
        # space under it before the next card in its column; columns
        # pack each side independently, cards at natural height.
        # Administration order (Batch 3 #10): System Administration
        # at the top with Backups folded into it (no standalone backup
        # card), "What your shop does" up top with it, then the rest.
        # Petty cash lives here (Jason 2026-10-24): sealed from the
        # money system, its one door is the Petty Cash button in this
        # page's Admin tab row (build 'w', Jason 2026-10-25 — same
        # row as the tab buttons, same size, right-justified;
        # supersedes pack 'm''s standalone button below the row),
        # opening the drawer in the standard popup. The working
        # money tabs carry no trace of it.
        # Build 'ac' (Jason 2026-10-27): the Administration squeeze —
        # page-local tighter card padding/margins (the global card
        # CSS is untouched), and the Version card folded into System
        # Administration: one card answers for the book's machinery,
        # its lower area two-part — Backup Settings left,
        # Version/Update right.
        return tabs_admin("/setup/admin", petty_door=True) + chain_banner_admin(con, q) + f"""
        <style>.admincols{{columns:2 340px;column-gap:10px}}.admincols>section{{break-inside:avoid;margin-bottom:10px;padding:10px 14px}}.admincols h2{{margin:0 0 6px}}.admincols h3{{margin:8px 0 4px}}.admincols p{{margin:4px 0}}</style>
        <div class="admincols">
        <section class=card>
          <h2>System Administration</h2>
          <p class=mute>Data Health checks the book for record problems. The Operation Manual is the complete reference.</p>
          <p class=actions><a class="btn secondary" href="/setup/devices">Manage devices</a> <a class="btn secondary" href="/setup/health">Data Health</a> <a class="btn secondary" href="/manual" target="_blank">Operation Manual (PDF)</a></p>
          <div style="display:flex;flex-wrap:wrap;gap:6px 24px;align-items:flex-start">
            <div style="flex:1 1 220px;min-width:200px">
              <h3>Backup Settings</h3>
              <p>Backup status: <b>{status}</b>. Last backup: <b>{last}</b>.</p>
              <p class=actions><a class="btn secondary" href="/backup">Manage backups →</a></p>
            </div>
            <div style="flex:1 1 220px;min-width:200px">
              <h3>Version</h3>
              <p>FleetSheet version <b>{html.escape(_ver)}</b>.</p>
              <p class=mute>Update checks run only when the button is used.</p>
              {updates_inner}
            </div>
          </div>
        </section>
        {shop_card}
        {self._setup_rerun_card(con)}
        {layout_card}
        {zoom_card}
        {printing_card}
        </div>
        """

    def _setup_rerun_card(self, con):
        """Admin entry point for re-running the setup walk-through over
        existing settings (Batch 3 #3). A review/change pass only: it
        sets one flag — it never deletes the database and never
        creates one; every step opens with current values in place."""
        try:
            if setup_rerun(con):
                return ("<section class=card><h2>Setup Walk-Through</h2>"
                        "<p class='hint'>Setup review in progress. Each step "
                        "opens with its current settings in place, and the "
                        "review can be ended from the banner on any "
                        "step.</p></section>")
            if not setup_finished(con):
                return ""
        except Exception:
            return ""
        return ("<section class=card><h2>Setup Walk-Through</h2>"
                "<p class=mute>A guided review of the current settings, "
                "step by step. Existing values stay in place — nothing "
                "is deleted or recreated.</p>"
                "<form method=post action=\"/setup/rerun\">"
                "<p class=actions><button>Run setup again</button></p>"
                "</form></section>")

    def _setup_summary(self, con, c):
        main = engine.main_company_phone(con)
        main_txt = format_phone(main['number']) if main else "—"
        city = ", ".join(
            x for x in (self._g(c, "addr_city"), self._g(c, "addr_state")) if x
        )
        chain = setup_chain(con)
        named = " \u00b7 ".join(
            f"{s['n']} {s['name']}{' (optional)' if s['optional'] else ''} "
            f"{'\u2713' if s['done'] else '\u25cb'}" for s in chain)
        status = f"<div class='hint'>Setup: {named}</div>"
        return tabs_admin("/setup", con=con) + f"""
        <div class="card" style="max-width:560px">
          <span>Company setup is saved.</span>
          <b style="font-size:20px">{html.escape(c["name"] or "—")}</b>
          <p class="hint">{html.escape(self._g(c, "dba") or "")}</p>
          <p>{html.escape(main_txt)}<br>{html.escape(city)}</p>
          {status}
          <p class="actions"><a class="btn" href="/setup?edit=1">Edit company setup</a></p>
        </div>
        """

    def _setup_form(self, con, c):
        # Example company name clears on focus (Jason 2026-10-08): if the name
        # is still the seeded example, mark it so the footer JS wipes it.
        _cname = html.escape(c['name'])
        _cex = ' data-example="YOUR COMPANY LLC"' if (c['name'] or '').strip().upper() == "YOUR COMPANY LLC" else ""
        return tabs_admin("/setup", con=con) + chain_banner(con, "company") + """
        <p class="mute" style="max-width:70ch">DBA is an optional trade name; printed documents use it where a trade name applies, otherwise the legal name. County is collected for tax only, not for mailing. The company logo is optional and prints on documents.</p>
        """ + f"""
        <form method=post action="/setup" id="setup-form" enctype="multipart/form-data">
        <div class="fgrid">
          <div>
            <div><label>Legal Company Name</label><input name=name value="{_cname}" required{_cex}></div>
            <div><label>Billing Address</label><input name=addr_street id="bill_street" value="{html.escape(self._g(c, 'addr_street'))}"></div>
            <div><label>Address line 2 <span class="hint">(optional)</span></label>
            <input name=addr_street2 value="{html.escape(self._g(c, 'addr_street2'))}" placeholder="Apt, suite, c/o Accounts Payable&hellip;"></div>
            <div class="row3">
              <div><label>City</label><input name=addr_city id="bill_city" value="{html.escape(self._g(c, 'addr_city'))}"></div>
              <div><label>State</label>{state_field("addr_state", self._g(c, 'addr_state'), 'id="bill_state" class=w-xs maxlength=20')}</div>
              <div><label>ZIP</label><input name=addr_zip id="bill_zip" class=w-xs value="{html.escape(self._g(c, 'addr_zip'))}" maxlength=12></div>
            </div>
          </div>
          <div>
            <div><label>DBA / trade name <span class="hint">(optional)</span></label><input name=dba value="{html.escape(self._g(c, 'dba'))}"></div>
            <div><label>Physical address <span class="hint"><label style="display:inline;margin:0"><input type=checkbox id="phys_same" style="width:auto"> same as billing</label></span></label><input name=phys_street id="phys_street" value="{html.escape(self._g(c, 'phys_street'))}"></div>
            <div class="row3">
              <div><label>City</label><input name=phys_city id="phys_city" value="{html.escape(self._g(c, 'phys_city'))}"></div>
              <div><label>State</label>{state_field("phys_state", self._g(c, 'phys_state'), 'id="phys_state" class=w-xs maxlength=20')}</div>
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
        <p style="margin-top:8px"><button form="setup-form" class="big">Save</button></p>
        """

    def _phone_block(self, con):
        phones = engine.list_company_phones(con)
        if phones:
            def _phone_row(p):
                # Batch 3 #5: the operator's label stands alone — no
                # inferred "(main)" suffix. The main number carries a
                # plain "Main" tag only because the operator picked it
                # (Make main, below); every other row offers the pick.
                tag = (" <span class='hint' style='border:1px solid #c8cfd8;"
                       "border-radius:3px;padding:0 4px'>Main</span>"
                       if p['is_main'] else "")
                pick = ("" if p['is_main'] else
                        f"<form method=post action='/setup/phones/main' style='display:inline;margin:0'>"
                        f"<input type=hidden name=phone_id value='{p['phone_id']}'>"
                        f"<button class='secondary' type=submit style='padding:2px 8px;font-size:12px'>Make main</button></form> ")
                return (
                    f"<div style='display:flex;justify-content:space-between;align-items:center;gap:8px;padding:2px 0;border-bottom:1px solid #eef0f3'>"
                    f"<span style='white-space:nowrap'><b>{html.escape(p['label'])}</b>{tag} &mdash; "
                    f"{html.escape(format_phone(p['number']))}</span>"
                    f"<span style='flex-shrink:0;white-space:nowrap'>{pick}"
                    f"<form method=post action='/setup/phones/del' style='display:inline;margin:0'>"
                    f"<input type=hidden name=phone_id value='{p['phone_id']}'>"
                    f"<button class='secondary' type=submit style='padding:2px 8px;font-size:12px'>Remove</button></form></span></div>")
            items = "".join(_phone_row(p) for p in phones)
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

    def _vendor_block(self, con, q=None):
        # No inline index list (Jason 2026-10-21, look-see batch 2 —
        # the universal form rule): Done Today is the recent list and
        # the full list lives behind View (/setup/vendors/all). The
        # Remove control that used to ride the inline rows moved into
        # the View list's rows, so no function was lost with the list.
        # Batch 3 #9: no Kind field (crew is not added here); Contact
        # (person to ask for) and Notes fields; ?edit=<id> opens this
        # same form as the vendor editor (rows in the View list link
        # here), prefilled, saving back to the same record.
        edit = None
        try:
            _eid = int((q or {}).get("edit") or 0)
        except (TypeError, ValueError):
            _eid = 0
        if _eid:
            edit = next((v for v in engine.list_vendors(con)
                         if v["vendor_id"] == _eid), None)
        def _ev(k):
            if not edit:
                return ""
            try:
                return html.escape(edit[k] or "", quote=True)
            except Exception:
                return ""
        if edit:
            head = "<p style='margin:0 0 8px'><b>Edit vendor</b></p>"
            form_open = "<div id=\"vendform\">"
            hid = (f"<input type=hidden name=vendor_id "
                   f"value='{edit['vendor_id']}'>")
        else:
            # Build 'ae' rebuild (Phase 2): the new-vendor form stands
            # open blank, like every other master editor — the
            # display:none toggle door is gone. The explanation
            # paragraph is gone with it (page copy rule; the Setup
            # tab caption above the block carries the register).
            head = ""
            form_open = "<div id=\"vendform\">"
            hid = ""
        _vrow = self._btn_row(
            "Save",
            extra='<a class="btn secondary" href="/setup/vendors">Close</a>')
        return head + f"""
        {form_open}
        <form method=post action="/setup/vendors" style="margin-top:8px" class="card">
          {hid}
          <div class="frow">
            <div style="flex:1 1 160px"><label>Name</label><input name=name maxlength=80 required placeholder="Acme Load Testing" value="{_ev('name')}"></div>
            <div><label>Contact</label><input name=contact maxlength=80 value="{_ev('contact')}"></div>
            <div><label>Phone</label><input name=phone maxlength=40 placeholder="+1 (337) 555-0100" style="max-width:26ch" value="{_ev('phone')}"></div>
          </div>
          <div class="frow">
            <div style="flex:1 1 160px"><label>Email</label><input name=email maxlength=80 value="{_ev('email')}"></div>
            <div style="flex:2 1 200px"><label>What For</label><input name=specialties maxlength=120 placeholder="load tests, sling inspections" value="{_ev('specialties')}"></div>
            <div style="flex:2 1 200px"><label>Notes</label><input name=notes maxlength=200 value="{_ev('notes')}"></div>
          </div>
          {_vrow}
        </form>
        </div>
        """ + self._view_door("/setup/vendors/all", "Vendors — all")

    def view_vendors_all(self, con):
        """Every vendor — filterable, sortable audit popup. A row opens
        the vendor editor (Batch 3 #9e); Edit sits alongside Remove."""
        rows = engine.list_vendors(con)
        def _vc(v, k):
            try:
                return v[k] or ""
            except Exception:
                return ""
        body = "".join(
            f"<tr><td><a href='/setup/vendors?edit={v['vendor_id']}'><b>{html.escape(v['name'])}</b></a></td>"
            f"<td>{html.escape(_vc(v, 'contact'))}</td>"
            f"<td>{html.escape(format_phone(v['phone'] or ''))}</td>"
            f"<td>{html.escape(v['email'] or '')}</td>"
            f"<td>{html.escape(v['specialties'] or '')}</td>"
            f"<td>{html.escape(_vc(v, 'notes'))}</td>"
            f"<td style='text-align:right;white-space:nowrap'>"
            f"<a class='btn secondary' style='padding:2px 8px' href='/setup/vendors?edit={v['vendor_id']}'>Edit</a> "
            f"<form method=post action='/setup/vendors/del' style='display:inline;margin:0'>"
            f"<input type=hidden name=vendor_id value='{v['vendor_id']}'>"
            f"<button type=submit class='secondary' style='padding:2px 8px'>Remove</button></form></td></tr>"
            for v in rows)
        return f"""
        <p class="hint"><input id="auditq" placeholder="Filter" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))"></p>
        <table class="audit"><tr><th>Name</th><th>Contact</th><th>Phone</th><th>Email</th><th>What for</th><th>Notes</th><th></th></tr>
        {body or '<tr><td colspan=7>No vendors.</td></tr>'}</table>
        """ + AUDIT_TABLE_JS

    # --- Compliance packs ---------------------------------------------------

    def _send_print(self, html_doc):
        # Print pages are full HTML docs rendered outside page(): give them
        # the heartbeat too — an open print tab counts as "FleetSheet is open".
        if "</body>" in html_doc:
            html_doc = html_doc.replace("</body>", "<script>window.FS_IDLE_MINS=%d;window.FS_LOCK_MINS=%d;</script>" % (IDLE_MINS, LOCK_MINS) + HEARTBEAT_JS + "</body>", 1)
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
        if raw == "petty":
            # Petty register has no document id either (Jason
            # 2026-10-24: the drawer is printable). The kind branch
            # below is unreachable for a bare /print/petty — the
            # two-part check 404s first — so it is answered here.
            self._log_print(con, raw, as_pdf)
            self._send_print(printpack.html_petty(con))
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
            # Attachment selection (Invoice Round Part B): ?docs= is a
            # comma-joined list of attachment aids. Present -> pass the
            # parsed list (blank entries stripped; an empty value is an
            # empty selection, not "all"); absent -> selected=None (all).
            _docs_raw = q.get("docs")
            _selected = None
            if _docs_raw is not None:
                _selected = [a.strip() for a in str(_docs_raw).split(",") if a.strip()]
            pack = printpack.invoice_pack(con, doc, selected=_selected)
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
                self._send(page("Print", "<p>Unknown Rental Ticket.</p>"), 404)
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
                # Certification records ride the same selection
                # (build 'o', the unit paperwork print): r= carries
                # ticked cert ids. Callers that send no r get an
                # empty cert selection, as selective prints always did.
                pick_r = _ids(q.get("r"))
                if not pick_c and not pick_d and not pick_r:
                    self._send(page("Print", "<p>Select at least one check, certification, or document first.</p>"), 400)
                    return
                pack = printpack.compliance_pack(con, aid, pick_c, pick_d, pick_r)
                nothing = (not pack or not (pack["items"] or pack["docs"] or pack["certs"])
                           or (pick_c and not pack["items"] and not pick_d and not pick_r)
                           or (pick_d and not pack["docs"] and not pick_c and not pick_r)
                           or (pick_r and not pack["certs"] and not pick_c and not pick_d))
                if nothing:
                    self._send(page("Print", "<p>Select at least one check, certification, or document first.</p>"), 400)
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
                    when_txt = f'{fmt_date(s["from_date"])} to {fmt_date(s["to_date"])}' 
                desc = f'{what_label.get(s["what"], s["what"])} · {when_txt} · {how_label.get(s["how"], s["how"])}'
                rows.append(f"""
                <tr>
                  <td><strong>{html.escape(s['label'])}</strong><div class="hint">{html.escape(desc)}</div></td>
                  <td style="text-align:right;white-space:nowrap">
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
            <div><label>From <span class="hint">(blank = no floor)</span></label><input type=date name=cfrom class=w-sm></div>
            <div><label>To <span class="hint">(blank = no ceiling)</span></label><input type=date name=cto class=w-sm></div>
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
              <select name=cdir class=w-sm><option value=asc>Ascending</option><option value=desc>Descending</option></select></div>
          </div>
          <p class="actions">
            <button type=submit formmethod=get formaction="/export/custom/run" >Download</button>
          </p>
          <div class="row" style="align-items:end">
            <div><label>Save this build <span class="hint">(name it to reuse later)</span></label>
              <input name=label maxlength=60 placeholder="e.g. Open Rental Tickets for the Monday meeting"></div>
            <div><button type=submit formmethod=post formaction="/export/custom/save" class="secondary">Save</button></div>
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
                    bits.append(f"{fmt_date(c['from_date']) or '…'} to {fmt_date(c['to_date']) or '…'}")
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

        return tabs_reports("/export", con) + weekly_tabs("", con) + f"""
        <h2 style="font-size:16px;color:var(--frame)">New Export</h2>
        <form>
          <div class="row">
            <div>{what_combo}</div>
            <div><label>When</label><select name=when class=w-sm>{when_opts}</select></div>
          </div>
          <div class="row">
            <div><label>From <span class="hint">(Custom range only)</span></label><input type=date name=from class=w-sm value="{today}"></div>
            <div><label>To <span class="hint">(Custom range only)</span></label><input type=date name=to class=w-sm value="{today}"></div>
          </div>
          <div class="row">
            <div><label>How</label><select name=how>{how_opts}</select></div>
            <div></div>
          </div>
          <p class="hint">Where</p>
          <p class="actions">
            <button type=submit formmethod=get formaction="/export/run" >Download</button>
            <button type=submit formmethod=post formaction="/export/run" class="secondary" >Save</button>
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
        <p class="hint">Month columns: YYYY-MM.</p>
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
            elif base == "mixed":
                kinds = [k for k, _, _ in engine.MIXED_KINDS
                         if q.get("kind_" + k)]
                time_mode = q.get("time_mode") or "once"
                rng_from, rng_to = engine.mixed_range(
                    time_mode, q.get("from") or "", q.get("to") or "",
                    q.get("month") or "")
                rows, _tot = engine.mixed_rows(con, kinds, rng_from, rng_to,
                                               q.get("customer") or "")
                headers = engine.MIXED_COLUMNS
                dicts = [{"Date": r["date"], "Type": r["type"],
                          "Ref": r["ref"], "Customer": r["customer"],
                          "Unit / Doc": r["unit"],
                          "Amount": round(r["amount"], 2),
                          "Status": r["status"]} for r in rows]
                fname = (f"mixed-{q.get('month')}" if time_mode == "monthly"
                         and q.get("month") else
                         f"mixed-{rng_from}_to_{rng_to}"
                         if rng_from or rng_to else "mixed-report")
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
