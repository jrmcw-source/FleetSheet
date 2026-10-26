"""Demo database builder: a year of real-company life for FleetSheet.

Usage:  python3 demo_data.py /path/to/demo.db

Builds a deterministic (seeded) database that looks like a small rental
yard ran FleetSheet for a year: ~50 customers, ~44 units, ~130 tickets,
~160 quotes, ~500 invoices (paid, open, past-due, disputed, written off),
payments with realistic timing, compliance packs with due/overdue items,
work orders, petty cash, and open Today tasks.

Enough live data to light up everything: the Today money slot, the median
(big-fish) ranking, the alert strip, compliance watch, and the audit pages.
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta

sys.path.insert(0, ".")
import engine
import engine_accounting as acct
import engine_compliance as comp
import engine_today as today_engine

SEED = 20260930
TODAY = date.today()

# ---------------------------------------------------------------- names

PRE = ["Gulf", "Bayou", "Pelican", "Cypress", "Sabine", "Vermilion", "Acadiana",
       "Coteau", "Teche", "Evangeline", "Mermentau", "Calcasieu", "Lafourche",
       "Terrebonne", "Delta", "Magnolia", "Live Oak", "Red River", "Atchafalaya", "Cypremort"]
CORE = ["Ridge", "Energy", "Marine", "Construction", "Industrial", "Oilfield",
        "Rentals", "Services", "Pipeline", "Fabrication", "Wellhead", "Completions",
        "Production", "Environmental", "Logistics"]
SUF = ["LLC", "Inc", "Co.", "Services LLC", "Contractors Inc"]
CITIES = ["Lafayette, LA", "Broussard, LA", "New Iberia, LA", "Houma, LA",
          "Morgan City, LA", "Lake Charles, LA", "Abbeville, LA", "Crowley, LA",
          "Port Arthur, TX", "Beaumont, TX"]
CLERKS = ["J. Guidry", "M. Thibodeaux", "S. Broussard"]

UNITS = [  # (prefix, category, description, daily_rate)
    ("GEN", "Generator", "100 kW diesel generator", 185),
    ("LT", "Light Tower", "6 kW vertical-mast light tower", 65),
    ("AC", "Air Compressor", "185 CFM rotary screw compressor", 95),
    ("TP4", "Trash Pump", '4" trash pump', 75),
    ("TP6", "Trash Pump", '6" trash pump', 115),
    ("DWP", "De-watering Pump", "8\" electric submersible de-watering pump", 140),
    ("TK", "Tank", "500 bbl frac tank", 55),
    ("ML", "Manlift", "60' articulating manlift", 225),
    ("FL", "Forklift", "8k lb rough-terrain forklift", 165),
    ("PW", "Pressure Washer", "4 GPM hot-water pressure washer", 45),
    ("VC", "Vacuum Unit", "130 bbl vacuum truck unit", 310),
]
LINE_KINDS = [
    ("Rental", "Equipment rental — {desc}", "day"),
    ("Rental", "Equipment rental — {desc} (standby)", "day"),
    ("Labor", "Field technician labor", "hour"),
    ("Labor", "Rig-up / rig-down labor", "hour"),
    ("Transport", "Mobilization", "each"),
    ("Transport", "Demobilization", "each"),
    ("Parts", "Consumables and fittings", "lot"),
    ("Other", "Fuel surcharge", "each"),
]
METHODS = ["ACH", "ACH", "ACH", "Check", "Check", "Wire", "Card", "Cash"]


def iso(d: date) -> str:
    return d.isoformat()


class _Seed:
    """Deterministic demo-DB builder: one method per build step, run in order."""

    def __init__(self, db_path):
        self.db_path = db_path
        self.rng = random.Random(SEED)
        self.con = engine.init_db(engine.connect(db_path))

    def run(self):
        for _name, _step in _SEED_STEPS:
            _step(self)

    def seed_jurisdictions(self):
        # -- jurisdictions (sites need one)
        # NOTE 2026-10-06 (Jason): display names use "County" not "Parish" —
        # business software speaks county; 49 of 50 states do, and Louisianans
        # understand it fine. Outsiders should never have to ask "what's a parish?"
        for i, (county, rate) in enumerate(
            [("Lafayette County", 0.0925), ("Vermilion County", 0.0875),
             ("Iberia County", 0.09), ("Jefferson County TX", 0.0825)]):
            self.con.execute(
                """INSERT OR IGNORE INTO jurisdictions
                   (loc_id, loc_class, region, county, display_name, tax_rate, tax_name)
                   VALUES (?,?,?,?,?,?,?)""",
                (f"LOC-{i+1}", "county", "LA" if i < 3 else "TX", county,
                 county, rate, "Sales tax"),
            )
        self.locs = [f"LOC-{i+1}" for i in range(4)]


    def seed_customers(self):
        # -- customers
        self.cust_ids = []
        names = set()
        while len(names) < 50:
            names.add(f"{self.rng.choice(PRE)} {self.rng.choice(CORE)} {self.rng.choice(SUF)}")
        for n, name in enumerate(sorted(names), 1):
            cid = f"C-{n:03d}"
            self.con.execute(
                """INSERT INTO customers
                   (customer_id, account_name, short_name, bill_to, phone, email,
                    city_st, terms, tax_exempt, credit_limit, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (cid, name, " ".join(name.split()[:2]),
                 f"{self.rng.randint(100,9999)} {self.rng.choice(['Industrial Pkwy','Field Rd','Yard Ln'])}",
                 f"337-555-{self.rng.randint(1000,9999):04d}",
                 f"ap@{''.join(name.split()).lower()[:18]}.com",
                 self.rng.choice(CITIES),
                 self.rng.choice(["Net 15", "Net 30", "Net 30", "Net 30", "Net 45"]),
                 1 if self.rng.random() < 0.55 else 0,
                 self.rng.choice([25000, 50000, 75000, 100000]),
                 ""),
            )
            self.cust_ids.append(cid)


    def seed_sites(self):
        # -- sites
        self.site_ids = []
        for n, cid in enumerate(self.cust_ids, 1):
            sid = f"S-{n:03d}"
            self.con.execute(
                """INSERT INTO sites
                   (site_id, site_name, operator, rig_name, customer_id, loc_id, notes)
                   VALUES (?,?,?,?,?,?,?)""",
                (sid, f"{self.rng.choice(['North','South','East','West'])} {self.rng.choice(['Pad','Yard','Dock','Plant'])} {n}",
                 self.rng.choice(PRE) + " Operating", f"Rig {self.rng.randint(3,38)}",
                 cid, self.rng.choice(self.locs), ""),
            )
            self.site_ids.append(sid)


    def seed_assets(self):
        # -- assets
        self.asset_ids = []
        n = 0
        for prefix, cat, desc, rate in UNITS:
            for k in range(1, 5):
                n += 1
                aid = f"A-{n:03d}"
                spread = self.rng.randint(-200, 420)
                cert = iso(TODAY + timedelta(days=spread)) if self.rng.random() < 0.85 else None
                self.con.execute(
                    """INSERT INTO assets
                       (asset_id, unit_no, category, description, serial_no, yard,
                        daily_rate, weekly_rate, monthly_rate, cert_expire,
                        condition, notes, rate_unit, rate_value)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (aid, f"{prefix}-{100+k}", cat, desc,
                     f"SN{self.rng.randint(100000,999999)}", self.rng.choice(["Main", "North", "South"]),
                     rate, round(rate*5.5, 2), round(rate*18, 2), cert,
                     self.rng.choice(["Available", "Available", "Available", "On Rent", "In Shop"]),
                     "", "Day", rate),
                )
                self.asset_ids.append(aid)


    def seed_compliance(self):
        # -- compliance packs + completions
        packs = [r["pack_id"] for r in comp.list_packs(self.con)]
        eqc_total = 0
        for aid in self.asset_ids:
            for pid in self.rng.sample(packs, self.rng.randint(1, 3)):
                try:
                    comp.assign_pack(self.con, aid, pid)
                except ValueError:
                    pass
        for row in self.con.execute("SELECT eqc_id, trigger, interval_months, deployed_backstop_months FROM equipment_compliance"):
            eqc_total += 1
            # last_done spread so the fleet shows ok / due / overdue mix
            back = self.rng.choice([10, 30, 60, 90, 120, 200, 300, 420])
            done = TODAY - timedelta(days=back)
            try:
                comp.record_completion(
                    self.con, row["eqc_id"], iso(done),
                    result="fail" if self.rng.random() < 0.04 else "pass",
                    notes="", clerk=self.rng.choice(CLERKS))
            except ValueError:
                pass
        self.con.commit()


    def seed_vendors(self):
        # -- vendors: who does the certs & calibrations
        self.vendors = {}
        for name, kind, phone, spec in [
            ("Gulf Coast Load Testing", "vendor", "337-555-0100", "load tests, proof loading"),
            ("Bayou Rigging Supply", "vendor", "337-555-0117", "slings, rigging inspections"),
            ("Acadiana Fire & Safety", "vendor", "337-555-0123", "smoke detectors, extinguishers, alarms"),
            ("Precision Calibration Lab", "vendor", "337-555-0131", "gauge and meter calibration"),
            ("Billy Bob", "crew", "337-555-0142", "smoke detectors, yard checks"),
        ]:
            self.vendors[name] = comp.save_vendor(self.con, name, kind=kind, phone=phone, specialties=spec)
        who_map = [
            ("load", "Gulf Coast Load Testing"), ("proof", "Gulf Coast Load Testing"),
            ("sling", "Bayou Rigging Supply"), ("rigging", "Bayou Rigging Supply"),
            ("smoke", "Acadiana Fire & Safety"), ("fire", "Acadiana Fire & Safety"),
            ("extinguisher", "Acadiana Fire & Safety"), ("alarm", "Acadiana Fire & Safety"),
            ("calibrat", "Precision Calibration Lab"), ("gauge", "Precision Calibration Lab"),
            ("meter", "Precision Calibration Lab"),
        ]
        for row in self.con.execute(
                """SELECT e.eqc_id, COALESCE(r.name,'') AS req_name, e.custom_name
                   FROM equipment_compliance e
                   LEFT JOIN compliance_requirements r ON r.req_id = e.req_id"""):
            nm = f"{row['req_name']} {row['custom_name'] or ''}".lower()
            vid = None
            for key, vname in who_map:
                if key in nm:
                    vid = self.vendors[vname]
                    break
            if vid is None and self.rng.random() < 0.35:
                vid = self.vendors["Billy Bob"]  # crew handles it in the yard
            # else: None = the yard does it themselves
            if vid:
                comp.set_checklist_performer(self.con, row["eqc_id"], vid)

        # Make every demo asset fit for shipment. Compliance warning examples come from
        # checklist due/overdue records rather than making live rentals unshippable.
        comp.ensure_cert_tables(self.con)
        for idx, aid in enumerate(self.asset_ids):
            expiry = TODAY + timedelta(days=365)
            self.con.execute("UPDATE assets SET uscg_ok=1, dnv_ok=1, abs_ok=1, cert_expire=? WHERE asset_id=?", (iso(expiry), aid))
            comp.save_cert(self.con, aid, 'certification', 'Demo equipment certificate', issuer='FleetSheet Demo',
                           issued_date=iso(TODAY - timedelta(days=30)), expiry_date=iso(expiry), clerk='Demo')
        self.con.commit()


    def seed_tickets(self):
        # -- tickets
        # Build tickets through the real engine workflow.  The demo must never
        # manufacture impossible states (e.g. Billed without an invoice or a unit
        # simultaneously on two live tickets).  Historical reuse of an asset is
        # fine; live assets are assigned uniquely below.
        statuses = (['Ready to Bill'] * 18 + ['Off Rent'] * 12 + ['On Rent'] * 8
                    + ['Dispatched'] * 5 + ['Reserved'] * 3 + ['Quoted'] * 8
                    + ['Ready to Bill'] * 20 + ['Off Rent'] * 20 + ['On Rent'] * 8
                    + ['Dispatched'] * 5 + ['Reserved'] * 3 + ['Quoted'] * 8 + ['Ready to Bill'] * 6 + ['Off Rent'] * 6)
        self.rng.shuffle(statuses)
        self.ticket_ids = []
        sites_by_customer = {}
        for r in self.con.execute('SELECT site_id, customer_id FROM sites'):
            sites_by_customer.setdefault(r['customer_id'], []).append(r['site_id'])
        live_statuses = {'On Rent', 'Dispatched', 'Reserved'}
        live_asset_iter = iter(self.asset_ids[:32])
        history_asset_pool = self.asset_ids[32:]
        for n in range(1, 131):
            tid = f"T-{1000+n}"
            on = TODAY - timedelta(days=self.rng.randint(0, 365))
            st = statuses[n-1]
            if st in live_statuses:
                aid = next(live_asset_iter)
            else:
                aid = self.rng.choice(history_asset_pool)
            cid = self.rng.choice(self.cust_ids)
            sid = self.rng.choice(sites_by_customer[cid])
            rate = self.con.execute("SELECT rate_value FROM assets WHERE asset_id=?", (aid,)).fetchone()['rate_value']
            off = None
            if st in ('Ready to Bill', 'Off Rent'):
                off = on + timedelta(days=self.rng.randint(3, 90))
                if off > TODAY:
                    off = TODAY
            if st == 'Ready to Bill' and off is None:
                off = TODAY
            tid_created = engine.create_ticket(self.con, {
                'customer_id': cid, 'site_id': sid, 'asset_id': aid,
                'job_name': self.rng.choice(['Turnaround','Frac support','Plant maintenance','Pipeline tie-in']),
                'po': f"PO-{self.rng.randint(10000,99999)}", 'rate_type': 'Day',
                'rate_value': rate, 'on_rent': iso(on), 'off_rent': iso(off) if off else None,
                'mob': self.rng.choice([0, 250, 450, 650]), 'demob': self.rng.choice([0, 250, 450]),
                'fuel': round(self.rng.uniform(0, 400), 2), 'parts': round(self.rng.uniform(0, 600), 2),
                'haul_by': 'we', 'deliver_to': 'job_site', 'waiver_yn': True,
                'status': 'Reserved' if st in live_statuses and st != 'Quoted' else ('Quoted' if st == 'Quoted' else 'Reserved'),
            })
            self.ticket_ids.append(tid_created)
            if st in ('Dispatched', 'On Rent'):
                engine.save_ticket_condition(self.con, tid_created, 'out', {
                    'condition': 'Available', 'note': 'Demo checkout — clean',
                    'meter': '', 'hours': '', 'clerk': self.rng.choice(CLERKS), 'source': 'demo'
                })
                engine.set_status(self.con, tid_created, 'Dispatched', clerk=self.rng.choice(CLERKS))
                if st == 'On Rent':
                    engine.set_status(self.con, tid_created, 'On Rent', clerk=self.rng.choice(CLERKS))
            elif st in ('Off Rent', 'Ready to Bill'):
                engine.save_ticket_condition(self.con, tid_created, 'out', {
                    'condition': 'Available', 'note': 'Demo checkout — clean',
                    'meter': '', 'hours': '', 'clerk': self.rng.choice(CLERKS), 'source': 'demo'
                })
                engine.set_status(self.con, tid_created, 'Dispatched', clerk=self.rng.choice(CLERKS))
                engine.set_status(self.con, tid_created, 'On Rent', clerk=self.rng.choice(CLERKS))
                engine.save_ticket_condition(self.con, tid_created, 'in', {
                    'condition': self.rng.choice(['Available', 'Available', 'Repair — minor']),
                    'note': 'Demo check-in', 'meter': '', 'hours': '',
                    'clerk': self.rng.choice(CLERKS), 'source': 'demo'
                })
                engine.set_status(self.con, tid_created, 'Off Rent', off_rent=iso(off), clerk=self.rng.choice(CLERKS))
                if st == 'Ready to Bill':
                    engine.set_status(self.con, tid_created, 'Ready to Bill', clerk=self.rng.choice(CLERKS))
            elif st == 'Reserved':
                # Already created in Reserved state; it is a live hold.
                pass
            elif st == 'Quoted':
                # Already created as Quoted.
                pass

        # Twenty rental tickets are actually invoiced through the public accounting
        # path.  Half are then closed through the normal Billed -> Closed gate.
        ready_for_invoice = [r['ticket_id'] for r in self.con.execute(
            "SELECT ticket_id FROM tickets WHERE status IN ('Off Rent','Ready to Bill') ORDER BY ticket_id LIMIT 20")]
        ticket_invoice_nos = []
        for idx, tid in enumerate(ready_for_invoice):
            tr = self.con.execute('SELECT customer_id FROM tickets WHERE ticket_id=?', (tid,)).fetchone()
            ino = acct.create_invoice(self.con, tr['customer_id'], [tid], inv_date=TODAY.isoformat())
            ticket_invoice_nos.append(ino)
            if idx < 10:
                engine.set_status(self.con, tid, 'Closed', clerk=self.rng.choice(CLERKS))
        self.con.commit()


    def seed_quotes(self):
        # -- quotes
        q_status = (["Sent"] * 25 + ["Accepted"] * 15 + ["Converted"] * 15
                    + ["Expired"] * 15 + ["Declined"] * 10 + ["Draft"] * 12 + ["Void"] * 8)
        for n in range(1, 161):
            qno = f"Q-{26000+n}"
            qd = TODAY - timedelta(days=self.rng.randint(0, 300))
            st = self.rng.choice(q_status)
            vu = qd + timedelta(days=30)
            self.con.execute(
                """INSERT INTO quotes
                   (quote_no, quote_date, customer_id, site_id, job_name,
                    valid_until, status, clerk)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (qno, iso(qd), self.rng.choice(self.cust_ids), self.rng.choice(self.site_ids),
                 f"{self.rng.choice(['Generator package','Pump spread','Tank farm support'])}",
                 iso(vu), st, self.rng.choice(CLERKS)),
            )
            for _ in range(self.rng.randint(1, 4)):
                aid = self.rng.choice(self.asset_ids)
                rate = self.con.execute("SELECT daily_rate FROM assets WHERE asset_id=?", (aid,)).fetchone()["daily_rate"]
                qty = self.rng.randint(3, 30)
                self.con.execute(
                    """INSERT INTO quote_lines (quote_no, kind, asset_id, description, qty, rate, amount)
                       VALUES (?,?,?,?,?,?,?)""",
                    (qno, "rental", aid, f"{aid} rental", qty, rate, round(qty * rate, 2)),
                )


    def seed_invoices(self):
        # -- invoices
        self.inv_n = 0
        self.pay_n = 0
        whale_targets = {40, 120, 210, 330, 430, 490}  # invoice indexes -> big fish
        self.writeoffs: list = []

        def next_inv() -> str:
            self.inv_n += 1
            return f"INV-{2000+self.inv_n}"

        def add_payment(ino: str, amount: float, pdate: date, cid: str) -> None:
            self.pay_n += 1
            self.con.execute(
                """INSERT INTO collections
                   (pay_id, pay_date, invoice_no, method, amount, ref_no, kind,
                    clerk, applied_amount, unapplied_amount)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (f"P-{self.pay_n:06d}", iso(pdate), ino, self.rng.choice(METHODS), round(amount, 2),
                 f"{self.rng.choice(['CHK','ACH','WIRE'])}-{self.rng.randint(1000,9999)}",
                 "payment", self.rng.choice(CLERKS), round(amount, 2), 0.0),
            )

        for i in range(1, 481):
            ino = next_inv()
            cid = self.rng.choice(self.cust_ids)
            # heavier toward recent months
            age = int(abs(self.rng.gauss(120, 110)))
            age = min(age, 365)
            idate = TODAY - timedelta(days=age)
            terms = self.rng.choice(["Net 15", "Net 30", "Net 30", "Net 30", "Net 45"])
            tdays = {"Net 15": 15, "Net 30": 30, "Net 45": 45}[terms]
            due = idate + timedelta(days=tdays)

            self.con.execute(
                """INSERT INTO invoices
                   (invoice_no, invoice_date, customer_id, terms, po, status)
                   VALUES (?,?,?,?,?,?)""",
                (ino, iso(idate), cid, terms, f"PO-{self.rng.randint(10000,99999)}", "Sent"),
            )
            total = 0.0
            if i in whale_targets:
                # big fish: single fat line, still open
                amt = round(self.rng.uniform(25000, 75000), 2)
                self.con.execute(
                    """INSERT INTO invoice_lines
                       (invoice_no, category, description, qty, uom, rate, amount)
                       VALUES (?,?,?,?,?,?,?)""",
                    (ino, "Rental", "Vacuum unit + crew — 45 day turnaround support",
                     45, "day", round(amt / 45, 2), amt),
                )
                total = amt
            else:
                for _ in range(self.rng.randint(1, 4)):
                    cat, tmpl, uom = self.rng.choice(LINE_KINDS)
                    aid = self.rng.choice(self.asset_ids)
                    desc = tmpl.format(desc=aid)
                    if cat == "Labor":
                        qty, rate = self.rng.randint(4, 32), self.rng.choice([65, 75, 85, 95])
                    elif cat == "Rental":
                        rate = self.con.execute("SELECT daily_rate FROM assets WHERE asset_id=?", (aid,)).fetchone()["daily_rate"]
                        qty = self.rng.randint(2, 21)
                    elif "Mobilization" in desc:
                        qty, rate = 1, self.rng.choice([250, 450, 650])
                    elif "Demobilization" in desc:
                        qty, rate = 1, self.rng.choice([250, 450])
                    elif cat == "Parts":
                        qty, rate = 1, round(self.rng.uniform(40, 450), 2)
                    else:
                        qty, rate = 1, round(self.rng.uniform(75, 300), 2)
                    amt = round(qty * rate, 2)
                    total += amt
                    self.con.execute(
                        """INSERT INTO invoice_lines
                           (invoice_no, category, description, qty, uom, rate, amount)
                           VALUES (?,?,?,?,?,?,?)""",
                        (ino, cat, desc, qty, uom, rate, amt),
                    )

            roll = self.rng.random()
            if i in whale_targets:
                pass  # stays open: the big fish
            elif roll < 0.70:
                # paid — realistic timing around the due date
                lag = int(self.rng.gauss(2, 12))
                pdate = due + timedelta(days=lag)
                if pdate > TODAY:
                    pdate = TODAY
                if pdate < idate:
                    pdate = idate
                if self.rng.random() < 0.85:
                    add_payment(ino, total, pdate, cid)
                else:  # two-part payment
                    first = round(total * self.rng.uniform(0.4, 0.7), 2)
                    add_payment(ino, first, pdate, cid)
                    add_payment(ino, round(total - first, 2),
                                min(pdate + timedelta(days=self.rng.randint(1, 20)), TODAY), cid)
            elif roll < 0.80:
                # open, recent-ish (some past due)
                if self.rng.random() < 0.3:  # partial payment
                    add_payment(ino, round(total * self.rng.uniform(0.2, 0.6), 2),
                                min(idate + timedelta(days=self.rng.randint(5, 40)), TODAY), cid)
            elif roll < 0.85:
                self.con.execute("UPDATE invoices SET status='Disputed' WHERE invoice_no=?", (ino,))
            elif roll < 0.89:
                add_payment(ino, total, min(due + timedelta(days=self.rng.randint(0, 10)), TODAY), cid)
                self.writeoffs.append(ino)
            elif roll < 0.93:
                self.con.execute("UPDATE invoices SET status='Ready' WHERE invoice_no=?", (ino,))
            else:
                self.con.execute("UPDATE invoices SET status='Draft' WHERE invoice_no=?", (ino,))

        # The direct demo invoice generator uses INV-2001..INV-2480.  Keep the
        # live application counter ahead of every generated invoice.
        self.con.execute("UPDATE company SET next_invoice=? WHERE id=1", (2481,))

        # a few credit memos
        for n in range(1, 9):
            self.con.execute(
                """INSERT INTO credit_memos
                   (cm_no, cm_date, customer_id, face_amount, reason, notes, clerk)
                   VALUES (?,?,?,?,?,?,?)""",
                (f"CM-{n:04d}", iso(TODAY - timedelta(days=self.rng.randint(5, 200))),
                 self.rng.choice(self.cust_ids), round(self.rng.uniform(50, 900), 2),
                 self.rng.choice(["Overpayment on invoice", "Pricing adjustment", "Duplicate billing correction"]),
                 "", self.rng.choice(CLERKS)),
            )

        # refresh computed invoice statuses (Paid / Partial), preserving the rest
        for r in self.con.execute("SELECT invoice_no FROM invoices"):
            acct._refresh_invoice_status(self.con, r["invoice_no"])
        # write-offs were fully paid above; the refresh would flip them to Paid
        for ino in self.writeoffs:
            self.con.execute("UPDATE invoices SET status='Write-off' WHERE invoice_no=?", (ino,))
        self.con.commit()


    def seed_work_orders(self):
        # -- work orders
        for n in range(1, 31):
            wid = f"WO-{1000+n}"
            aid = self.rng.choice(self.asset_ids)
            odate = TODAY - timedelta(days=self.rng.randint(0, 300))
            st = self.rng.choice(["Open", "In progress", "Complete", "Complete", "Complete"])
            cdate = iso(odate + timedelta(days=self.rng.randint(2, 30))) if st == "Complete" else None
            self.con.execute(
                """INSERT INTO work_orders
                   (wo_id, asset_id, ticket_id, customer_id, charge_to, work_type,
                    description, open_date, close_date, labor, parts, status, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (wid, aid, self.rng.choice(self.ticket_ids) if self.rng.random() < 0.5 else None,
                 self.rng.choice(self.cust_ids) if self.rng.random() < 0.4 else None,
                 self.rng.choice(["internal", "internal", "customer"]),
                 self.rng.choice(["Preventive", "Repair", "Inspection", "Calibration"]),
                 self.rng.choice(["Annual service", "Bearing replacement", "Hose replacement",
                             "Calibration check", "Engine tune-up", "Paint and touch-up"]),
                 iso(odate), cdate, round(self.rng.uniform(80, 1200), 2),
                 round(self.rng.uniform(0, 800), 2), st, ""),
            )


    def seed_petty_cash(self):
        # -- petty cash
        self.con.execute(
            """INSERT INTO petty_cash (pc_id, txn_date, direction, amount, category, notes, clerk)
               VALUES ('PC-000001',?,?,?,?,?,?)""",
            (iso(TODAY - timedelta(days=330)), "in", 500.00, "Float", "Opening float", "J. Guidry"),
        )
        for n in range(2, 32):
            self.con.execute(
                """INSERT INTO petty_cash (pc_id, txn_date, direction, amount, category, payee, notes, clerk)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (f"PC-{n:06d}", iso(TODAY - timedelta(days=self.rng.randint(0, 320))),
                 "out" if self.rng.random() < 0.8 else "in",
                 round(self.rng.uniform(8, 180), 2),
                 self.rng.choice(["Fuel", "Parts", "Supplies", "Meals", "Postage"]),
                 self.rng.choice(["O'Reilly", "Fuel stop", "Hardware store", "Office supply"]),
                 "", self.rng.choice(CLERKS)),
            )


    def seed_today_tasks(self):
        # -- today tasks
        today_engine._ensure_task_tables(self.con)
        tasks = [
            ("must", "Call Gulf Coast outfit about the disputed invoice before lunch", ""),
            ("must", "Chase the two big past-dues — rent depends on it", ""),
            ("can", "Price out replacement hoses for TP6-103", ""),
            ("can", "File the new DNV paperwork when it lands", ""),
            ("later", "Reorganize the parts cage", ""),
            ("later", "Get quotes for a second vacuum unit", ""),
        ]
        for tier, text, _ in tasks:
            self.con.execute(
                "INSERT INTO today_tasks (text, tier, done, link) VALUES (?,?,0,'')",
                (text, tier),
            )
        # linked tasks
        sample_inv = self.con.execute(
            "SELECT invoice_no FROM invoices WHERE status='Sent' LIMIT 1").fetchone()["invoice_no"]
        sample_tkt = self.ticket_ids[0]
        sample_cust = self.cust_ids[0]
        for tier, text, link in [
            ("must", f"Collect {sample_inv} — 40+ days out", f"invoice:{sample_inv}"),
            ("can", f"Confirm off-rent on {sample_tkt}", f"ticket:{sample_tkt}"),
            ("later", "Send the new rate sheet", f"customer:{sample_cust}"),
        ]:
            self.con.execute("INSERT INTO today_tasks (text, tier, done, link) VALUES (?,?,0,?)",
                        (text, tier, link))
        for text in ["Ordered shop rags", "Called the accountant back"]:
            self.con.execute("INSERT INTO today_tasks (text, tier, done, link) VALUES (?,?,1,'')",
                        (text, "can"))

        self.con.commit()


    def seed_census(self):
        # -- census
        print(f"demo db: {self.db_path}")
        for t in ["customers", "sites", "assets", "equipment_compliance", "compliance_events",
                  "tickets", "quotes", "quote_lines", "invoices", "invoice_lines",
                  "collections", "credit_memos", "work_orders", "petty_cash", "today_tasks"]:
            c = self.con.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            print(f"  {t:22s} {c}")
        open_n = self.con.execute(
            "SELECT COUNT(*) c FROM invoices WHERE status NOT IN ('Paid','Write-off','Draft')").fetchone()["c"]
        fish = acct.big_fish_invoices(self.con)
        print(f"  open invoices: {open_n} | big-fish flags: {len(fish['invoice_nos'])}")
        self.con.close()


_SEED_STEPS = [
    ("jurisdictions (sites need one)", _Seed.seed_jurisdictions),
    ("customers", _Seed.seed_customers),
    ("sites", _Seed.seed_sites),
    ("assets", _Seed.seed_assets),
    ("compliance packs + completions", _Seed.seed_compliance),
    ("vendors: who does the certs & calibrations", _Seed.seed_vendors),
    ("tickets", _Seed.seed_tickets),
    ("quotes", _Seed.seed_quotes),
    ("invoices", _Seed.seed_invoices),
    ("work orders", _Seed.seed_work_orders),
    ("petty cash", _Seed.seed_petty_cash),
    ("today tasks", _Seed.seed_today_tasks),
    ("census", _Seed.seed_census),
]


def main(db_path: str) -> None:
    _Seed(db_path).run()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/demo.db")
