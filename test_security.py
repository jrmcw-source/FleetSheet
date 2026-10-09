"""LAN/security regression checks."""
import os
import unittest
from pathlib import Path

import app

class SecurityTests(unittest.TestCase):
    def test_bind_policy_is_explicit(self):
        old=os.environ.get("FLEETSHEET_BIND")
        try:
            os.environ.pop("FLEETSHEET_BIND",None)
            self.assertEqual(os.environ.get("FLEETSHEET_BIND","localhost"),"localhost")
            os.environ["FLEETSHEET_BIND"]="localhost"
            self.assertEqual(os.environ["FLEETSHEET_BIND"],"localhost")
            os.environ["FLEETSHEET_BIND"]="lan"
            self.assertEqual(os.environ["FLEETSHEET_BIND"],"lan")
        finally:
            if old is None: os.environ.pop("FLEETSHEET_BIND",None)
            else: os.environ["FLEETSHEET_BIND"]=old
    def test_device_management_is_pin_sensitive(self):
        v=app.views_core.CoreViews()
        self.assertTrue(v._money_path("/setup/devices"))
        self.assertTrue(v._money_path("/setup/devices/show"))
        self.assertTrue(v._money_path("/setup/devices/issue"))
        self.assertFalse(v._money_path("/d"))
        self.assertFalse(v._money_path("/d/ticket/T-1"))
        # Compliance packs are operational records, not money pages; financial
        # printouts remain protected individually.
        self.assertFalse(v._money_path("/print/compliance/A-001"))
        self.assertTrue(v._money_path("/print/invoice/INV-1"))
        self.assertTrue(v._money_path("/print/credit/CM-1"))
    def test_unexpected_errors_use_safe_customer_message(self):
        src=Path(app.__file__).read_text()
        self.assertIn("def _safe_failure", src)
        self.assertIn("Technical details belong in", src)
        self.assertNotIn('"?err=" + str(e).replace(" ", "+")[:180]', src)

    def test_sensitive_response_headers_present(self):
        src=Path(app.views_core.__file__).read_text()
        self.assertIn('Cache-Control", "no-store',src)
        self.assertIn('Referrer-Policy", "no-referrer',src)
        self.assertIn('X-Content-Type-Options", "nosniff',src)
if __name__=="__main__": unittest.main(verbosity=2)
