"""End-to-end rental workflow regression test.

Creates a temporary FleetSheet book and exercises the same domain operations
used by the UI: reserve -> dispatch -> on rent -> off rent -> ready to bill ->
invoice -> payment -> close. This deliberately does not depend on demo.db.
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import engine


class RentalWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="fleetsheet-e2e-")
        self.db = Path(self.tmp.name) / "test.db"
        self.con = sqlite3.connect(self.db)
        self.con.row_factory = sqlite3.Row
        engine.init_db(self.con)
        self.con.execute("INSERT INTO jurisdictions(loc_id,loc_class,display_name,tax_rate,tax_name) VALUES ('YARD','yard','Fleet yard',0.0825,'Yard tax')")
        self.con.execute("UPDATE company SET yard_loc_id='YARD', default_tax=0.0825 WHERE id=1")
        self.con.execute("INSERT INTO customers(customer_id,account_name,tax_exempt) VALUES ('C1','Customer One',0)")
        self.con.execute("INSERT INTO sites(site_id,site_name,customer_id,loc_id,tax_exempt) VALUES ('S1','Job Site','C1','YARD',0)")
        self.con.execute("INSERT INTO assets(asset_id,unit_no,description,rate_unit,rate_value,active) VALUES ('A1','101','Test unit','Day',250,1)")
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_complete_rental_to_cash_to_close(self):
        tid = engine.create_ticket(self.con, {
            'customer_id':'C1', 'site_id':'S1', 'asset_id':'A1',
            'rate_type':'Day', 'rate_value':250, 'on_rent':'2026-10-02',
            'status':'Reserved', 'haul_by':'we', 'deliver_to':'job_site',
            'tax_loc_id':'YARD', 'waiver_yn':False,
        })
        self.assertEqual(self.con.execute("SELECT status FROM tickets WHERE ticket_id=?", (tid,)).fetchone()[0], 'Reserved')

        with self.assertRaisesRegex(ValueError, 'check-out condition'):
            engine.set_status(self.con, tid, 'Dispatched', clerk='TEST')

        engine.save_ticket_condition(self.con, tid, 'out', {
            'condition':'Available', 'meter':'100', 'hours':100, 'clerk':'TEST'
        })
        engine.set_status(self.con, tid, 'Dispatched', clerk='TEST')
        engine.set_status(self.con, tid, 'On Rent', clerk='TEST')

        with self.assertRaisesRegex(ValueError, 'check-in condition'):
            engine.set_status(self.con, tid, 'Off Rent', off_rent='2026-10-05', clerk='TEST')

        engine.save_ticket_condition(self.con, tid, 'in', {
            'condition':'Available', 'meter':'110', 'hours':110, 'clerk':'TEST'
        })
        engine.set_status(self.con, tid, 'Off Rent', off_rent='2026-10-05', clerk='TEST')
        engine.set_status(self.con, tid, 'Ready to Bill', clerk='TEST')

        ino = engine.create_invoice(self.con, 'C1', [tid], inv_date='2026-10-05')
        self.assertEqual(self.con.execute("SELECT status,invoice_no FROM tickets WHERE ticket_id=?", (tid,)).fetchone()[0:2], ('Billed', ino))
        totals = engine.invoice_totals(self.con, ino)
        self.assertGreater(totals['total'], 0)

        payment = engine.record_payment(self.con, ino, totals['total'], '2026-10-06', 'Check', 'E2E', 'TEST')
        self.assertAlmostEqual(payment['applied'], totals['total'], places=2)
        self.assertEqual(self.con.execute("SELECT status FROM invoices WHERE invoice_no=?", (ino,)).fetchone()[0], 'Paid')

        engine.set_status(self.con, tid, 'Closed', clerk='TEST')
        row = self.con.execute("SELECT status,invoice_no,off_rent FROM tickets WHERE ticket_id=?", (tid,)).fetchone()
        self.assertEqual(row['status'], 'Closed')
        self.assertEqual(row['invoice_no'], ino)
        self.assertEqual(row['off_rent'], '2026-10-05')


if __name__ == '__main__':
    unittest.main(verbosity=2)
