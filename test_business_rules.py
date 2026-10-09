"""Portable regression tests for FleetSheet's transport/tax business rules.

These tests intentionally create their own temporary database.  They do not depend
on a developer workstation path or on demo.db contents.
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import engine


class TransportTaxRulesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="fleetsheet-rules-")
        self.db = Path(self.tmp.name) / "test.db"
        self.con = sqlite3.connect(self.db)
        self.con.row_factory = sqlite3.Row
        engine.init_db(self.con)
        self.con.execute("INSERT OR REPLACE INTO jurisdictions(loc_id, loc_class, display_name, tax_rate, tax_name) VALUES ('YARD','yard','Fleet yard',0.0825,'Yard tax')")
        self.con.execute("INSERT OR REPLACE INTO jurisdictions(loc_id, loc_class, display_name, tax_rate, tax_name) VALUES ('SITE','site','Job site',0.0900,'Site tax')")
        self.con.execute("INSERT OR REPLACE INTO jurisdictions(loc_id, loc_class, display_name, tax_rate, tax_name) VALUES ('CUSTY','customer','Customer yard',0.0700,'Customer yard tax')")
        self.con.execute("UPDATE company SET yard_loc_id='YARD', default_tax=0.0825 WHERE id=1")
        self.con.execute("INSERT INTO customers(customer_id,account_name,tax_exempt) VALUES ('C1','Customer One',0)")
        self.con.execute("INSERT INTO sites(site_id,site_name,customer_id,loc_id,tax_exempt) VALUES ('S1','Job Site','C1','SITE',0)")
        self.con.execute("INSERT INTO assets(asset_id,unit_no,description,rate_unit,rate_value,active) VALUES ('A1','101','Test unit','Day',100,1)")
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def _ticket(self, haul, dest, tax_loc_id=None):
        return engine.create_ticket(self.con, {
            'customer_id':'C1','site_id':'S1','asset_id':'A1',
            'rate_type':'Day','rate_value':'100','on_rent':'2026-10-01',
            'haul_by':haul,'deliver_to':dest,'tax_loc_id':tax_loc_id,
            'waiver_yn':False,'status':'Quoted'
        })

    def test_no_tax_jurisdiction_means_no_tax_computed(self):
        # Jason's rule 2026-10-04: the software never decides tax. No explicit
        # jurisdiction -> no tax computed, whatever the haul/destination.
        tid=self._ticket('customer','job_site')
        m=engine.ticket_money(self.con,tid)
        self.assertEqual(m['tax_loc'],'')
        self.assertAlmostEqual(m['tax_rate'],0.0)
        tid=self._ticket('we','job_site')
        m=engine.ticket_money(self.con,tid)
        self.assertEqual(m['tax_loc'],'')
        self.assertAlmostEqual(m['tax_rate'],0.0)

    def test_explicit_jurisdiction_drives_tax(self):
        tid=self._ticket('we','customer_yard','CUSTY')
        m=engine.ticket_money(self.con,tid)
        self.assertEqual(m['tax_loc'],'CUSTY')
        self.assertAlmostEqual(m['tax_rate'],0.07)

    def test_dock_with_explicit_jurisdiction(self):
        tid=self._ticket('third_party','dock','CUSTY')
        m=engine.ticket_money(self.con,tid)
        self.assertEqual(m['tax_loc'],'CUSTY')
        self.assertAlmostEqual(m['tax_rate'],0.07)

    def test_blank_jurisdiction_is_allowed_not_forced(self):
        # No autofill, no required selection: blank is the operator's call.
        tid=self._ticket('we','dock')
        m=engine.ticket_money(self.con,tid)
        self.assertAlmostEqual(m['tax_rate'],0.0)

    def test_invalid_tax_jurisdiction_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'does not exist'):
            self._ticket('we','dock','NO_SUCH_LOCATION')


if __name__ == '__main__':
    unittest.main(verbosity=2)
