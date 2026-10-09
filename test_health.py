"""Portable tests for the read-only FleetSheet data-health auditor."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import engine


class DataHealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="fleetsheet-health-")
        self.db = Path(self.tmp.name) / "health.db"
        self.con = sqlite3.connect(self.db)
        self.con.row_factory = sqlite3.Row
        engine.init_db(self.con)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def _base_records(self):
        self.con.execute("INSERT INTO jurisdictions(loc_id,loc_class,display_name,tax_rate) VALUES ('Y','yard','Yard',0.08)")
        self.con.execute("UPDATE company SET yard_loc_id='Y', next_ticket=1001, next_invoice=1001, next_payment=1 WHERE id=1")
        self.con.execute("INSERT INTO customers(customer_id,account_name) VALUES ('C1','Customer')")
        self.con.execute("INSERT INTO sites(site_id,site_name,customer_id,loc_id) VALUES ('S1','Site','C1','Y')")
        self.con.execute("INSERT INTO assets(asset_id,unit_no,description,rate_unit,rate_value,active) VALUES ('A1','101','Unit','Day',100,1)")
        self.con.commit()

    def test_new_book_is_clean(self):
        r = engine.data_health(self.con)
        self.assertTrue(r['ok'], r)
        self.assertEqual(r['critical'], 0)

    def test_detects_live_conflict_and_billed_without_invoice(self):
        self._base_records()
        for tid in ('T-1001','T-1002','T-1003'):
            self.con.execute("""INSERT INTO tickets(ticket_id,customer_id,site_id,asset_id,rate_type,rate_value,on_rent,haul_by,deliver_to,status)
                               VALUES (?,?,?,?,?,?,?,?,?,?)""",
                             (tid,'C1','S1','A1','Day',100,'2026-10-01','we','job_site','On Rent'))
        self.con.execute("UPDATE tickets SET status='Billed' WHERE ticket_id='T-1003'")
        self.con.commit()
        r = engine.data_health(self.con)
        codes = {x['code'] for x in r['issues']}
        self.assertIn('LIVE_ASSET_CONFLICT', codes)
        self.assertIn('BILLED_WITHOUT_INVOICE', codes)
        self.assertNotIn('CLOSED_WITHOUT_INVOICE', codes)
        self.assertGreaterEqual(r['critical'], 2)

    def test_detects_missing_explicit_tax_jurisdiction(self):
        self._base_records()
        self.con.execute("""INSERT INTO tickets(ticket_id,customer_id,site_id,asset_id,rate_type,rate_value,on_rent,haul_by,deliver_to,status)
                           VALUES ('T-1001','C1','S1','A1','Day',100,'2026-10-01','we','dock','Quoted')""")
        self.con.commit()
        r = engine.data_health(self.con)
        codes = {x['code'] for x in r['issues']}
        self.assertIn('TAX_JURISDICTION_MISSING', codes)


if __name__ == '__main__':
    unittest.main(verbosity=2)
