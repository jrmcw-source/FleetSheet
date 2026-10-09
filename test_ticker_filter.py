"""Ticker category filter guard (2026-10-08).

The operator's category setting (engine_alerts.get/set_ticker_cats) governs
the whole strip: the section alerts AND the Top-of-the-day ticker. Money
items need the Money category; the Top-of-the-day asset item is shipping
paper, which counts as Compliance. Filtering happens before the limit cut,
and an explicitly empty category set turns the ticker off entirely.
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import engine
import engine_today


class TickerFilterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="fleetsheet-ticker-")
        self.db = Path(self.tmp.name) / "test.db"
        self.con = sqlite3.connect(self.db)
        self.con.row_factory = sqlite3.Row
        engine.init_db(self.con)
        self.con.execute("INSERT INTO customers(customer_id,account_name,tax_exempt) VALUES ('C1','Customer One',0)")
        # One invoice 40 days old on Net 30: 10 days late, $500 open.
        inv_date = (date.today() - timedelta(days=40)).isoformat()
        self.con.execute(
            "INSERT INTO invoices(invoice_no,invoice_date,customer_id,terms,status) VALUES ('INV-1',?,'C1','Net 30','Sent')",
            (inv_date,))
        self.con.execute(
            "INSERT INTO invoice_lines(invoice_no,category,description,qty,uom,rate,amount,tax_amount) "
            "VALUES ('INV-1','Rental','Unit 101',1,'Day',500,500,0)")
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def _keys(self):
        return [it["key"] for it in engine_today.top_of_day(self.con)]

    def test_default_all_categories_shows_late_invoice(self):
        keys = self._keys()
        self.assertTrue(any(k.startswith("money:late:") for k in keys), keys)

    def test_money_off_hides_money_items(self):
        engine.set_ticker_cats(self.con, {"rentals", "compliance"})
        self.assertFalse(any(k.startswith("money:") for k in self._keys()))

    def test_all_categories_off_returns_empty(self):
        engine.set_ticker_cats(self.con, set())
        self.assertEqual(engine_today.top_of_day(self.con), [])

    def test_asset_item_needs_compliance_category(self):
        fake = {"key": "top:asset:T-1", "text": "101 → Customer One: bad paper",
                "href": "/ticket/T-1"}
        orig = engine_today._top_asset_item
        engine_today._top_asset_item = lambda con: fake
        try:
            engine.set_ticker_cats(self.con, {"money"})
            self.assertNotIn("top:asset:T-1", self._keys())
            engine.set_ticker_cats(self.con, {"compliance"})
            self.assertIn("top:asset:T-1", self._keys())
        finally:
            engine_today._top_asset_item = orig


if __name__ == "__main__":
    unittest.main()
