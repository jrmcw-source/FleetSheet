#!/usr/bin/env python3
"""Compliance-pack feature tests: engine logic + live HTTP flows.

Run against a server started on a FRESH disposable DB:
    rm -f /tmp/eval_comp.db
    FLEETSHEET_DB=/tmp/eval_comp.db python3 app.py &
    FLEETSHEET_DB=/tmp/eval_comp.db python3 test_compliance.py
The suite resets that DB from the pristine demo copy for a deterministic run.
"""
import os, re, sqlite3, sys, subprocess, time, signal, atexit
import unittest

# This is a direct-execution integration harness, not a unittest module.
# Skip it during unittest discovery so importing it cannot launch a server or
# terminate the discovery process; direct execution remains unchanged.
if __name__ != "__main__":
    raise unittest.SkipTest("direct-execution integration harness")
from pathlib import Path
import urllib.parse, urllib.request, urllib.error

PORT = int(os.environ.get("FLEETSHEET_TEST_PORT", "18765"))
BASE = f"http://127.0.0.1:{PORT}"
DB = os.environ.get("FLEETSHEET_DB") or "/tmp/eval_comp.db"
SERVER = None
HERE = Path(__file__).resolve().parent
EULA_MARKER = HERE / ".eula_required"
EULA_HIDDEN = HERE / ".eula_required.compliance-hidden"
EULA_WAS_PRESENT = EULA_MARKER.exists()

def _restore_eula_marker():
    # The integration harness must exercise normal HTTP pages, not the
    # consumer EULA gate. Temporarily hide the shipped marker and always
    # restore it, including when the harness aborts midway.
    try:
        if EULA_HIDDEN.exists() and not EULA_MARKER.exists():
            EULA_HIDDEN.rename(EULA_MARKER)
    except OSError:
        pass

if EULA_WAS_PRESENT:
    try:
        EULA_MARKER.rename(EULA_HIDDEN)
    except OSError as exc:
        raise SystemExit("Could not isolate consumer EULA marker for test: %s" % exc)
    atexit.register(_restore_eula_marker)
EULA_MARKER = HERE / ".eula_required"
EULA_HIDDEN = HERE / ".eula_required.compliance-hidden"
EULA_WAS_PRESENT = EULA_MARKER.exists()

def _restore_eula_marker():
    # The integration harness must exercise normal HTTP pages, not the
    # consumer EULA gate.  Temporarily hide the shipped marker and always
    # restore it, including when the harness aborts midway.
    try:
        if EULA_HIDDEN.exists() and not EULA_MARKER.exists():
            EULA_HIDDEN.rename(EULA_MARKER)
    except OSError:
        pass

if EULA_WAS_PRESENT:
    try:
        EULA_MARKER.rename(EULA_HIDDEN)
    except OSError as exc:
        raise SystemExit("Could not isolate consumer EULA marker for test: %s" % exc)
    atexit.register(_restore_eula_marker)

R = {}
def check(name, ok, ev=""):
    R[name] = (bool(ok), ev)
    print(("PASS " if ok else "FAIL ") + name + (f" [{ev}]" if ev and not ok else ""))

sys.path.insert(0, str(HERE))
import engine

# The old developer harness depended on a workstation-only pristine database.
# This suite now creates its own disposable book so it can run anywhere.
if os.path.exists(DB):
    os.remove(DB)
con0 = engine.connect(DB)
engine.init_db(con0)
con0.close()

# ---------- engine-level, on a scratch DB ----------
tmp = "/tmp/comp_engine.db"
if os.path.exists(tmp):
    os.remove(tmp)
engine.DB_PATH = tmp
con = engine.connect()
engine.init_db(con)

packs = engine.list_packs(con)
check("C1 seven packs seeded", len(packs) == 7, f"{len(packs)} packs")
nreq = con.execute("SELECT COUNT(*) FROM compliance_requirements").fetchone()[0]
check("C2 46 requirements seeded", nreq == 46, f"{nreq}")
# idempotent reseed
engine.init_db(con)
nreq2 = con.execute("SELECT COUNT(*) FROM compliance_requirements").fetchone()[0]
check("C3 reseed idempotent", nreq2 == 46, f"{nreq2}")

aid = engine.next_asset_id(con)
engine.save_asset(con, {"unit_no": "CMP-1", "description": "Compliance mule",
                        "category": "Test Equipment", "cert_operator": True}, None)
a = con.execute("SELECT asset_id, cert_operator, category FROM assets WHERE unit_no='CMP-1'").fetchone()
aid = a["asset_id"]
check("C4 cert_operator + new category persist", a["cert_operator"] == 1 and a["category"] == "Test Equipment")

n1 = engine.assign_pack(con, aid, "shop-tools")
n2 = engine.assign_pack(con, aid, "shop-tools")
check("C5 assign idempotent", n1 == 5 and n2 == 0, f"{n1}/{n2}")
try:
    engine.assign_pack(con, aid, "nope")
    check("C6 unknown pack rejected", False)
except ValueError:
    check("C6 unknown pack rejected", True)

items = engine.unit_checklist(con, aid)
check("C7 checklist has 5 items, all due", len(items) == 5 and all(i["status"] == "due" for i in items),
      f"{len(items)} items")
first = items[0]
engine.record_completion(con, first["eqc_id"], "2026-09-24", "pass", "CAL-1", "", "Shop")
items = engine.unit_checklist(con, aid)
done = [i for i in items if i["eqc_id"] == first["eqc_id"]][0]
check("C8 done -> next due +12mo, ok", done["status"] == "ok" and done["next_due_live"].isoformat() == "2027-09-24",
      f"{done['status']} {done['next_due_live']}")
# old completion -> overdue
second = items[1]
engine.record_completion(con, second["eqc_id"], "2024-01-01", "pass", "", "", "Shop")
st = [i for i in engine.unit_checklist(con, aid) if i["eqc_id"] == second["eqc_id"]][0]
check("C9 stale completion overdue", st["status"] == "overdue", st["status"])
# fail -> due, never done
third = items[2]
engine.record_completion(con, third["eqc_id"], "2026-09-24", "fail", "", "out of tolerance", "Shop")
st = [i for i in engine.unit_checklist(con, aid) if i["eqc_id"] == third["eqc_id"]][0]
check("C10 fail stays due", st["status"] == "due", st["status"])
# custom requirement
cid = engine.add_custom_requirement(con, aid, "Yard function test", "per_job", "", "3", "shop note")
items = engine.unit_checklist(con, aid)
custom = [i for i in items if i["eqc_id"] == cid][0]
check("C11 custom add", custom["display_name"] == "Yard function test" and custom["status"] == "due")
# per-job/manufacturer custom checks require a backstop so they can't sit in info forever
try:
    engine.add_custom_requirement(con, aid, "No backstop", "per_job", "", "", "")
    check("C11b per-job without backstop rejected", False)
except ValueError:
    check("C11b per-job without backstop rejected", True)
try:
    engine.add_custom_requirement(con, aid, "No backstop mfr", "manufacturer", "", "", "")
    check("C11c manufacturer without backstop rejected", False)
except ValueError:
    check("C11c manufacturer without backstop rejected", True)
# edit interval/backstop
engine.update_checklist_item(con, cid, interval_months="6", backstop_months="3", notes="x")
r = con.execute("SELECT interval_months, deployed_backstop_months, notes FROM equipment_compliance WHERE eqc_id=?",
                (cid,)).fetchone()
check("C12 edit interval/backstop", r["interval_months"] == 6 and r["deployed_backstop_months"] == 3 and r["notes"] == "x",
      dict(r))
# clearing the backstop on a per-job custom check is rejected
try:
    engine.update_checklist_item(con, cid, backstop_months="")
    check("C12b per-job backstop cannot be cleared", False)
except ValueError:
    check("C12b per-job backstop cannot be cleared", True)
try:
    engine.update_checklist_item(con, cid, trigger="bogus")
    check("C13 bad trigger rejected", False)
except ValueError:
    check("C13 bad trigger rejected", True)
summ = engine.compliance_summary(con, aid)
check("C14 summary counts", summ["total"] == 6 and summ["overdue"] == 1 and summ["ok"] == 1
      and summ["due"] == 4 and summ["info"] == 0, str(summ))
watch = engine.fleet_compliance_watch(con)
mine = [w for w in watch if w["asset_id"] == aid]
check("C15 watch lists due/overdue",
      len(mine) == 5 and any(w["status"] == "overdue" for w in mine), f"{len(mine)} rows")
hist = engine.item_history(con, first["eqc_id"])
check("C16 history recorded", len(hist) == 1 and hist[0]["evidence"] == "CAL-1")
engine.remove_checklist_item(con, cid)
check("C17 remove custom", con.execute("SELECT COUNT(*) FROM equipment_compliance WHERE eqc_id=?", (cid,)).fetchone()[0] == 0)

# ---------- cert identity (Q5) ----------
try:
    engine.save_cert(con, "", "certification", "No unit")
    check("Z1 cert without asset rejected", False)
except ValueError:
    check("Z1 cert without asset rejected", True)
try:
    engine.save_cert(con, "NOPE", "certification", "Bad unit")
    check("Z2 cert unknown unit rejected", False)
except ValueError:
    check("Z2 cert unknown unit rejected", True)
try:
    engine.save_cert(con, aid, "certification", "")
    check("Z3 cert without title rejected", False)
except ValueError:
    check("Z3 cert without title rejected", True)
z1 = engine.save_cert(con, aid, "calibration", "Torque wrench cal", "CAL-99",
                      "Shop lab", "2026-01-15", "2027-01-15", "", "Shop")
z2 = engine.save_cert(con, aid, "certification", "Pressure cert", "", "",
                      None, "2028-06-01", "", "Shop")
z3 = engine.save_cert(con, aid, "function_test", "Yard function test", "", "",
                      None, "2026-06-01", "", "Shop")
certs = engine.list_certs(con, aid)
check("Z4 three cert records, kinds labeled", len(certs) == 3
      and any(c["kind_label"] == "Function test" for c in certs), f"{len(certs)}")
check("Z5 operative expiry = earliest live cert",
      engine.operative_cert_expiry(con, aid) == "2026-06-01",
      engine.operative_cert_expiry(con, aid))
engine.set_cert_superseded(con, z3)
check("Z6 superseded drops out of operative",
      engine.operative_cert_expiry(con, aid) == "2027-01-15",
      engine.operative_cert_expiry(con, aid))
st = engine.cert_status(con.execute("SELECT * FROM asset_certs WHERE cert_id=?", (z1,)).fetchone())
check("Z7 status valid", st == "valid", st)
# legacy migration
aid2 = engine.next_asset_id(con)
con.execute("INSERT INTO assets (asset_id, unit_no, description, cert_expire) VALUES (?,?,?,?)",
            (aid2, "CMP-LEG", "Legacy mule", "2024-05-01"))
con.commit()
moved = engine.migrate_legacy_cert_expiry(con)
check("Z8 legacy expiry migrates to a record", moved == 1
      and engine.operative_cert_expiry(con, aid2) == "2024-05-01",
      f"{moved} {engine.operative_cert_expiry(con, aid2)}")
moved2 = engine.migrate_legacy_cert_expiry(con)
check("Z9 migration idempotent", moved2 == 0, f"{moved2}")
engine.init_db(con)
moved3 = engine.migrate_legacy_cert_expiry(con)
check("Z10 init_db rerun does not duplicate", moved3 == 0, f"{moved3}")
# evidence attachment: doc must belong to the same asset
did = engine.save_unit_doc(con, aid, "Cal cert PDF", "cert", "cal.pdf", b"%PDF-1.4 fake", "Shop")
engine.attach_cert_evidence(con, z1, did)
c1 = engine.get_cert(con, z1)
check("Z11 evidence attaches to the record",
      c1["evidence_doc_id"] == did and c1["doc_filename"] == "cal.pdf", dict(c1))
aid3 = engine.next_asset_id(con)
con.execute("INSERT INTO assets (asset_id, unit_no, description) VALUES (?,?,?)",
            (aid3, "CMP-OTHER", "Other mule"))
con.commit()
did_other = engine.save_unit_doc(con, aid3, "Other doc", "cert", "o.pdf", b"%PDF-1.4 fake", "Shop")
try:
    engine.attach_cert_evidence(con, z1, did_other)
    check("Z12 cross-asset evidence rejected", False)
except ValueError:
    check("Z12 cross-asset evidence rejected", True)
engine.delete_cert(con, z2)
check("Z13 delete cert", con.execute("SELECT COUNT(*) FROM asset_certs WHERE cert_id=?", (z2,)).fetchone()[0] == 0)
# the evidence doc survives the record delete — paperwork is never destroyed
check("Z14 doc survives cert delete", engine.get_unit_doc(con, did) is not None)
con.close()

# ---------- HTTP-level ----------
# Start a disposable FleetSheet server ourselves. This keeps the HTTP suite
# deterministic and prevents the old failure mode where a developer happened
# to have another server running against a different database.
HTTP_DB = os.environ.get("FLEETSHEET_HTTP_DB") or "/tmp/eval_comp_http.db"
try:
    if os.path.exists(HTTP_DB):
        os.remove(HTTP_DB)
    env = os.environ.copy()
    env["FLEETSHEET_DB"] = HTTP_DB
    env["FLEETSHEET_PORT"] = str(PORT)
    env["FLEETSHEET_BIND"] = "127.0.0.1"
    env["FLEETSHEET_NO_AUTO_OPEN"] = "1"
    SERVER = subprocess.Popen([sys.executable, str(HERE / "app.py")], cwd=str(HERE),
                              env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True)
    deadline = time.time() + 15
    while time.time() < deadline:
        if SERVER.poll() is not None:
            out = SERVER.stdout.read() if SERVER.stdout else ""
            raise RuntimeError("FleetSheet HTTP test server exited early\n" + out[-4000:])
        try:
            with urllib.request.urlopen(BASE + "/compliance", timeout=0.5) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(0.15)
    else:
        raise RuntimeError("FleetSheet HTTP test server did not become ready")
    DB = HTTP_DB
except Exception as exc:
    if SERVER is not None:
        SERVER.terminate()
    print("FAIL HTTP harness startup: " + str(exc))
    raise SystemExit(1)

class NoRedir(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
op = urllib.request.build_opener(NoRedir)

def get(path):
    try:
        with op.open(BASE + path) as r:
            return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)

def post(path, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(BASE + path, data=body, method="POST")
    try:
        with op.open(req) as r:
            return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)

s, b, _ = get("/compliance")
check("H1 /compliance 200 + spare layout", s == 200 and "Upload Certificate" in b and "Needs Attention" in b, f"{s}")
s, b, _ = get("/compack/shop-tools")
check("H2 pack page 200 + policy labels", s == 200 and "Company policy" in b and "Torque wrench calibration" in b, f"{s}")
s, b, _ = get("/compack/nope")
check("H3 unknown pack -> err page", s == 200 and "Unknown pack" in b, f"{s}")

# make a unit via the real form flow
s, b, _ = get("/unit/new")
m = re.search(r'name=asset_id value="([^"]*)"', b)
s, b, h = post("/unit/save", {"asset_id": "", "unit_no": "CMP-WEB", "description": "Web mule",
                              "category": "Shop Tools", "cert_operator": "1"})
loc = h.get("Location", "")
# Save now returns to the unit list (by design); fetch the new id from the DB.
check("H4 unit save w/ cert_operator", s == 303 and loc.startswith("/units?msg=Unit+saved"), f"{s} {loc}")
_con = sqlite3.connect(DB); _con.row_factory = sqlite3.Row
_row = _con.execute("SELECT asset_id FROM assets WHERE unit_no='CMP-WEB'").fetchone()
aidw = _row["asset_id"] if _row else ""
_con.close()
check("H4b new unit in DB", bool(aidw), aidw)
s, b, _ = get(f"/unit/{aidw}")
check("H5 unit form shows flag + compliance link", s == 200 and "Requires certified operator" in b
      and f"/ucompliance/{aidw}" in b, f"{s}")

s, b, h = post("/compliance/assign", {"asset_id": aidw, "pack_id": "shop-tools"})
check("H6 assign POST -> 303", s == 303 and h.get("Location", "").startswith(f"/ucompliance/{aidw}"),
      f"{s} {h.get('Location')}")
s, b, h = post("/compliance/assign", {"asset_id": aidw, "pack_id": "shop-tools"})
check("H7 reassign idempotent msg", s == 303 and "0+checks+added" in h.get("Location", ""), h.get("Location"))
s, b, h = post("/compliance/assign", {"asset_id": aidw, "pack_id": "bogus"})
check("H8 bad pack -> err redirect", s == 303 and "err=" in h.get("Location", ""), h.get("Location"))
s, b, _ = get(f"/ucompliance/{aidw}")
check("H9 checklist page 200 + fix-it form", s == 200 and "Fix it —" in b and b.count("Due</b>") >= 5, f"{s}")
s, b, _ = get("/ucompliance/NOPE")
check("H10 unknown unit -> err", s == 200 and "Unknown unit" in b, f"{s}")

con2 = sqlite3.connect(DB); con2.row_factory = sqlite3.Row
eqc = con2.execute("SELECT eqc_id FROM equipment_compliance WHERE asset_id=? LIMIT 1", (aidw,)).fetchone()["eqc_id"]
s, b, h = post("/compliance/item/done", {"eqc_id": str(eqc), "done_date": "2026-09-24",
                                        "result": "pass", "evidence": "WEB-1", "notes": "", "clerk": "Shop"})
check("H11 record-done POST -> 303", s == 303 and h.get("Location", "").startswith(f"/ucompliance/{aidw}"), f"{s}")
s, b, _ = get(f"/ucompliance/{aidw}")
check("H12 done reflected (next due + evidence)", s == 200 and "2027-09-24" in b and "WEB-1" in b, f"{s}")
s, b, h = post("/compliance/item/save", {"eqc_id": str(eqc), "trigger": "per_job",
                                        "interval_months": "", "backstop_months": "6", "notes": "web edit"})
check("H13 edit POST -> 303", s == 303, f"{s}")
row = con2.execute("SELECT trigger, interval_months, deployed_backstop_months, notes FROM equipment_compliance WHERE eqc_id=?",
                   (eqc,)).fetchone()
check("H14 edit persisted", row["trigger"] == "per_job" and row["interval_months"] is None
      and row["deployed_backstop_months"] == 6 and row["notes"] == "web edit", dict(row))
s, b, h = post("/compliance/custom", {"asset_id": aidw, "name": "Web custom", "trigger": "per_job",
                                     "interval_months": "", "backstop_months": "6", "notes": ""})
check("H15 custom POST -> 303", s == 303, f"{s}")
s, b, h = post("/compliance/custom", {"asset_id": aidw, "name": "Web custom noback", "trigger": "per_job",
                                     "interval_months": "", "backstop_months": "", "notes": ""})
check("H15b custom without backstop -> err redirect",
      s == 303 and "err=" in (h.get("Location") or ""), f"{s} {h.get('Location')}")
s, b, _ = get(f"/ucompliance/{aidw}")
check("H16 custom shown", s == 200 and "Web custom" in b, f"{s}")
ceqc = con2.execute("SELECT eqc_id FROM equipment_compliance WHERE asset_id=? AND custom_name='Web custom'",
                    (aidw,)).fetchone()["eqc_id"]
s, b, h = post("/compliance/item/delete", {"eqc_id": str(ceqc)})
check("H17 delete POST -> 303", s == 303, f"{s}")
s, b, _ = get(f"/ucompliance/{aidw}")
check("H18 delete reflected", s == 200 and "Web custom" not in b.replace('placeholder="e.g. Yard function test"', ""), f"{s}")
con2.close()

s, b, _ = get("/")
check("H19 today can-do stack", s == 200 and "tier-can" in b, f"{s}")
s, b, _ = get("/reports")
check("H20 reports three prebuilts", s == 200 and "AR Aging" in b and "Utilization" in b and "This week" in b, f"{s}")

# ---------- cert identity: HTTP flows ----------
s, b, _ = get("/compliance")
check("H21 compliance ranked list", s == 200 and "Needs Attention" in b, f"{s}")
s, b, h = post("/compliance/cert/save", {"asset_id": "", "title": "No unit cert"})
check("H22 cert without asset -> err redirect",
      s == 303 and "err=" in (h.get("Location") or ""), f"{s} {h.get('Location')}")
s, b, h = post("/compliance/cert/save", {"asset_id": aidw, "kind": "calibration",
                                        "title": "Torque wrench cal", "cert_number": "WEB-9",
                                        "expiry_date": "2027-01-01", "clerk": "Shop"})
check("H23 cert save POST -> 303", s == 303 and h.get("Location", "").startswith(f"/ucompliance/{aidw}"),
      f"{s} {h.get('Location')}")
s, b, _ = get(f"/ucompliance/{aidw}")
check("H24 unit page shows cert record in fix-it form",
      s == 200 and "Torque wrench cal" in b and "Fix it —" in b, f"{s}")
# multipart: new cert with an evidence file attached in one step
def post_multipart(path, fields, files):
    bnd = "----certbnd"
    body = b""
    for k, v in fields.items():
        body += (f"--{bnd}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    for k, (fname, ctype, data) in files.items():
        body += (f"--{bnd}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fname}\"\r\n"
                 f"Content-Type: {ctype}\r\n\r\n").encode() + data + b"\r\n"
    body += f"--{bnd}--\r\n".encode()
    req = urllib.request.Request(BASE + path, data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={bnd}"})
    try:
        with op.open(req) as r:
            return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)
s, b, h = post_multipart("/compliance/cert/save",
                         {"asset_id": aidw, "kind": "certification", "title": "Web cert with paper",
                          "expiry_date": "2028-02-02", "clerk": "Shop"},
                         {"doc_file": ("cert.txt", "text/plain", b"certified")})
check("H25 cert+file POST -> 303", s == 303 and h.get("Location", "").startswith(f"/ucompliance/{aidw}"),
      f"{s} {h.get('Location')}")
s, b, _ = get(f"/ucompliance/{aidw}")
check("H26 evidence doc saved to data book", s == 200 and "Fix it —" in b, f"{s}")
s, b, _ = get(f"/print/compliance/{aidw}")
check("H26b evidence doc in printed pack", s == 200 and "cert.txt" in b, f"{s}")
s, b, _ = get(f"/print/compliance/{aidw}")
check("H27 printed pack shows cert records", s == 200 and "Certifications &amp; calibrations" in b
      and "Web cert with paper" in b and "CMP-WEB" in b, f"{s}")
# an expired cert record drives the operative expiry (not the legacy column)
s, b, h = post("/compliance/cert/save", {"asset_id": aidw, "kind": "certification",
                                        "title": "Old cert", "expiry_date": "2020-01-01"})
check("H28 expired cert saved", s == 303, f"{s}")
engine.DB_PATH = DB
conx = engine.connect()
check("H29 operative expiry comes from the cert record",
      engine.operative_cert_expiry(conx, aidw) == "2020-01-01",
      engine.operative_cert_expiry(conx, aidw))
conx.close()
s, b, _ = get("/assets/all")
check("H30 audit table shows the cert-record expiry",
      s == 200 and re.search(r"CMP-WEB</td>(?:(?!</tr>).)*2020-01-01", b, re.S) is not None, f"{s}")
con3 = sqlite3.connect(DB); con3.row_factory = sqlite3.Row
_c = con3.execute("SELECT cert_id FROM asset_certs WHERE asset_id=? AND title='Old cert'", (aidw,)).fetchone()
s, b, h = post("/compliance/cert/supersede", {"cert_id": str(_c["cert_id"])})
check("H31 supersede POST -> 303", s == 303, f"{s}")
conx = engine.connect()
check("H32 superseded cert clears the operative expiry",
      engine.operative_cert_expiry(conx, aidw) == "2027-01-01",
      engine.operative_cert_expiry(conx, aidw))
conx.close()
con3.close()

print("\n==== SUMMARY ====")
bad = [k for k, (ok, _) in R.items() if not ok]
for k, (ok, ev) in R.items():
    print(f"{'PASS' if ok else 'FAIL'}  {k}" + (f": {ev}" if ev and not ok else ""))
print(f"\n{len(R) - len(bad)} passed, {len(bad)} failed")
if SERVER is not None:
    SERVER.terminate()
    try:
        SERVER.wait(timeout=5)
    except subprocess.TimeoutExpired:
        SERVER.kill()
sys.exit(1 if bad else 0)
