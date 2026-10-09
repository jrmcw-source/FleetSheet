"""Small integration checks for the operator-facing ticket entry screen."""
import sqlite3
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import engine
from views_assets import AssetViews
from views_accounting import AccountingViews
import views_core


def main():
    con = sqlite3.connect(str(HERE / "demo.db"))
    con.row_factory = sqlite3.Row
    page = AssetViews().view_new_ticket(con, {"kind": "rental"})
    checks = {
        "rental section": '<fieldset' in page and '<legend>Rental</legend>' not in page,
        "delivery merged": 'Who hauls it' in page and 'Deliver to' in page,
        "workflow scrubbed": '<fieldset><legend>3. Workflow</legend>' not in page,
        # REMOVED 2026-10-07 F5: Jason said remove Save explanation text
        # REMOVED 2026-10-07 F5: Jason said remove row 5 explanations
        "required customer": 'id="f_customer_id" name=customer_id' in page and 'id="f_customer"' in page and 'required' in page,
        # REMOVED 2026-10-07 F5: Jason said job site is in Job info now
        "required unit": 'id="f_unit_id" name=asset_id' in page and 'id="f_unit"' in page and 'required' in page,
        "required rate": 'name=rate_type' in page and 'name=rate_value' in page,
        "required date": 'name=on_rent' in page and 'required data-label="On-rent date"' in page,
        # REMOVED 2026-10-07 F5: Jason said tax jurisdiction is in Job info now
    }
    # Text-size preference (Setup → Devices → Preferences): rendered as CSS
    # zoom on <html>, invalid values fall back to standard (no zoom rule).
    _old_ts = views_core.TEXT_SIZE
    try:
        views_core.TEXT_SIZE = "standard"
        _p_std = views_core.page("T", "<p>x</p>")
        views_core.TEXT_SIZE = "large"
        _p_large = views_core.page("T", "<p>x</p>")
        views_core.TEXT_SIZE = "xlarge"
        _p_xl = views_core.page("T", "<p>x</p>")
        views_core.TEXT_SIZE = "banana"
        _p_bad = views_core.page("T", "<p>x</p>")
    finally:
        views_core.TEXT_SIZE = _old_ts
    _dev = views_core.CoreViews().view_devices(con, {})
    # Page-box layout lock (bite 4): fenced grid, lock defaults on, drag and
    # width toggles are unlock-gated. The company form must not nest forms
    # (a nested <form> silently closes the outer one and drops fields).
    _pbox = views_core.PBOX_JS
    _setup = views_core.CoreViews().view_setup(con, {"edit": "1"})
    _setup_form = _setup.split('id="setup-form"')[1].split("</form>")[0]
    checks.update({
        "text size standard emits no zoom": "zoom:" not in _p_std,
        "text size large zooms 1.15": "html{zoom:1.15}" in _p_large,
        "text size xlarge zooms 1.3": "html{zoom:1.3}" in _p_xl,
        "text size invalid falls back": "zoom:" not in _p_bad,
        "preferences has text-size select": "name=text_size" in _dev and "Extra large" in _dev,
        "pbox has lock toggle": "pbox-lock" in _pbox and "state.locked" in _pbox,
        "pbox drag is lock-gated": 'box.draggable = !isLocked' in _pbox,
        "pbox width toggle is lock-gated": "pbox-width" in _pbox,
        "pbox fence grid CSS": ".pbox-grid" in views_core.CSS,
        "company form has no nested form": "<form" not in _setup_form,
        "company form keeps company fields and moves billing out": (
            "name=addr_street2" in _setup_form and "name=billing_email" not in _setup_form
            and "name=min_days" not in _setup_form and "name=invoice_prefix" not in _setup_form
            and "name=bill_both_dates" not in _setup_form),
        "billing setup owns billing defaults": (
            "name=billing_email" in views_core.CoreViews().view_setup_billing(con, {})
            and "name=min_days" in views_core.CoreViews().view_setup_billing(con, {})
            and "name=invoice_prefix" in views_core.CoreViews().view_setup_billing(con, {})),
        "company form moves backup config out": "name=backup_dir" not in _setup_form,
        "backups page owns backup config": (
            "name=backup_dir" in views_core.CoreViews().view_backups(con)),
        "administration links to backups": (
            "Backup Settings" in views_core.CoreViews().view_setup_admin(con, {})
            and "/backup" in views_core.CoreViews().view_setup_admin(con, {})),
        "administration owns system tools": (
            "Manage devices" in views_core.CoreViews().view_setup_admin(con, {})
            and "Data Health" in views_core.CoreViews().view_setup_admin(con, {})),
        "site creation is not blocked by missing tax setup": (
            "Tax location setup is required" not in AssetViews().view_site_form(con, None, {})
            and "Address" in AssetViews().view_site_form(con, None, {})
            and "Tax location (optional)" in AssetViews().view_site_form(con, None, {})),
        "customer uses conventional business structure": (
            "Business Name" in AccountingViews().view_customer_form(con, None)
            and "DBA / trade name" in AccountingViews().view_customer_form(con, None)
            and "Primary / Billing Address" in AccountingViews().view_customer_form(con, None)
            and "Commercial terms" in AccountingViews().view_customer_form(con, None)),
        "professional condition choices": (
            all(x in engine.COND_RANK for x in ("Excellent","Good","Fair","Poor","Damaged"))),
    })
    bad = [k for k, ok in checks.items() if not ok]
    for k, ok in checks.items():
        print(("PASS" if ok else "FAIL") + "  " + k)
    con.close()
    if bad:
        raise SystemExit("UX regression failures: " + ", ".join(bad))
    print(f"\n{len(checks)}/{len(checks)} UX checks passed")


if __name__ == "__main__":
    main()
