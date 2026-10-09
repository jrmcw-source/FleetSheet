import sqlite3
import tempfile
import unittest
from pathlib import Path

import engine


class SchemaAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="fleetsheet-schema-")
        self.db = Path(self.tmp.name) / "fresh.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_schema_sql_creates_all_runtime_tables(self):
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        engine.init_db(con)
        expected = {
            "company", "customers", "sites", "assets", "tickets", "invoices",
            "invoice_lines", "invoice_docs", "collections", "credit_memos",
            "petty_cash", "lookups", "work_orders", "quotes", "quote_lines",
            "change_orders", "change_order_lines", "crew", "saved_exports",
            "custom_reports", "compliance_packs", "compliance_requirements",
            "equipment_compliance", "compliance_events", "asset_certs", "vendors",
            "device_auths", "options", "unit_docs", "alert_ack", "purchase_orders",
            "today_tasks", "done_manual", "today_money_done", "today_stickies",
            "company_phones", "customer_phones", "customer_locations", "customer_contacts",
        }
        actual = {
            r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        missing = sorted(expected - actual)
        self.assertEqual(missing, [])
        con.close()

    def test_init_is_idempotent(self):
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        engine.init_db(con)
        before = {
            name: con.execute("SELECT COUNT(*) FROM \"%s\"" % name).fetchone()[0]
            for name in ("company", "lookups", "compliance_packs", "compliance_requirements")
        }
        engine.init_db(con)
        after = {
            name: con.execute("SELECT COUNT(*) FROM \"%s\"" % name).fetchone()[0]
            for name in before
        }
        self.assertEqual(before, after)
        con.close()


    def test_address_line2_columns_exist(self):
        # Bite 3 (2026-10-02): optional second street line on company and
        # customer billing addresses, for foreign addresses / c/o lines.
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        try:
            engine.init_db(con)
            ccols = [r[1] for r in con.execute("PRAGMA table_info(company)")]
            ucols = [r[1] for r in con.execute("PRAGMA table_info(customers)")]
            self.assertIn("addr_street2", ccols)
            self.assertIn("bill_street2", ucols)
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
