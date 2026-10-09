"""FleetSheet POST actions — accounting flow: invoices, payments, credit, quotes, petty cash, customers, export."""
import html
from datetime import date

import engine
from urllib.parse import quote_plus
from views_core import next_setup_step


def handle_post(handler, con, data, u):
    """Handle one POST. Returns True when the path was handled."""
    if u.path == "/invoice/create":
            tids = [k[3:] for k, v in data.items() if k.startswith("t__") and v == "1"]
            wids = [k[3:] for k, v in data.items() if k.startswith("w__") and v == "1"]
            ino = engine.create_invoice(
                con, data["customer_id"], tids, data.get("invoice_date") or None, wids,
                data.get("quote_no") or None, data.get("po") or None,
                po_expire=data.get("po_expire") or None,
                po_cost_code=data.get("po_cost_code") or None,
                po_notes=data.get("po_notes") or None,
            )
            # Save ref_ticket and quick line items (Jason 2026-10-07 F9)
            icols = [r[1] for r in con.execute("PRAGMA table_info(invoices)")]
            for col, ddl in [("ref_ticket", "TEXT"), ("quick_item", "TEXT"),
                             ("quick_desc", "TEXT"), ("quick_qty", "REAL DEFAULT 1"),
                             ("quick_rate", "REAL DEFAULT 0"),
                             ("tax_rate", "REAL DEFAULT 0"),
                             ("adjustment", "REAL DEFAULT 0")]:
                if col not in icols:
                    con.execute(f"ALTER TABLE invoices ADD COLUMN {col} {ddl}")
            # Server-side totals from the posted lines + tax_rate + adjustment
            # (never trust client math). Row 0 stays in the quick_* columns;
            # extra Add-item rows become real invoice lines.
            def _f(v):
                try:
                    return float(v or 0)
                except (TypeError, ValueError):
                    return 0.0
            q0, r0 = _f(data.get("qty")), _f(data.get("rate"))
            sub = round(q0 * r0, 2)
            extra = []
            for i in range(1, 61):
                qi, ri = _f(data.get(f"qty{i}")), _f(data.get(f"rate{i}"))
                it = (data.get(f"item{i}") or "").strip()
                ds = (data.get(f"item_desc{i}") or "").strip()
                if not it and not ds and not qi and not ri:
                    continue
                sub = round(sub + qi * ri, 2)
                extra.append((it, ds, qi, ri))
            tr = _f(data.get("tax_rate")) / 100.0
            adj = _f(data.get("adjustment"))
            try:
                _cx = con.execute("SELECT tax_exempt FROM customers WHERE customer_id=?",
                                  (data["customer_id"],)).fetchone()
                exempt = bool(_cx and _cx[0])
            except Exception:
                exempt = False
            tax = 0.0 if exempt else round(sub * tr, 2)
            con.execute(
                "UPDATE invoices SET ref_ticket=?, quick_item=?, quick_desc=?, quick_qty=?, quick_rate=?, tax_rate=?, adjustment=? WHERE invoice_no=?",
                ((data.get("ref_ticket") or "").strip(),
                 (data.get("item") or "").strip(),
                 (data.get("item_desc") or "").strip(),
                 q0, r0, tr, adj,
                 ino))
            for it, ds, qi, ri in extra:
                amt = round(qi * ri, 2)
                ltax = 0.0 if exempt else round(amt * tr, 2)
                desc = " — ".join(x for x in (it, ds) if x) or "Item"
                con.execute(
                    """INSERT INTO invoice_lines(invoice_no,po_line,category,description,qty,uom,rate,amount,
                       clerk,tax_rate,tax_amount,tax_exempt,tax_name,tax_loc,source_type,source_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (ino, "", "Item", desc, qi, "Each", ri, amt, "",
                     0.0 if exempt else tr, ltax, int(exempt),
                     "" if exempt else "Tax", "", "quick", ""))
            con.commit()
            up = (handler._files or {}).get("job_attach")
            if up and up[2]:
                engine.save_job_attachment(con, "invoice", ino, up[0], up[2], data.get("clerk", ""))
            handler._redirect(f"/invoice/{ino}?msg=Invoice+{ino}+created")
    elif u.path.endswith("/po") and u.path.startswith("/invoice/"):
            ino = u.path.split("/")[2]
            engine.set_invoice_po(
                con, ino, data.get("po") or "", data.get("clerk") or "",
                po_expire=data.get("po_expire") or None,
                po_cost_code=data.get("po_cost_code") or None,
                po_notes=data.get("po_notes") or None,
            )
            handler._redirect(f"/invoice/{ino}?msg=PO+saved")
    elif u.path.endswith("/doc") and u.path.startswith("/invoice/"):
            # Invoice paperwork: PO scan / tax-exempt certificate scan-in slot.
            # One slot per kind — a new upload replaces the old one.
            ino = u.path.split("/")[2]
            up = (handler._files or {}).get("doc_file")
            try:
                if not up or not up[2]:
                    raise ValueError("Choose a file to attach")
                engine.save_invoice_doc(con, ino, data.get("kind") or "",
                                        up[0] or "", up[2], data.get("clerk"))
                handler._redirect(f"/invoice/{ino}?msg=" + quote_plus("Paperwork attached"))
            except ValueError as e:
                handler._redirect(f"/invoice/{ino}?err=" + quote_plus(str(e)))
    elif u.path.endswith("/docdel") and u.path.startswith("/invoice/"):
            ino = u.path.split("/")[2]
            if engine.delete_invoice_doc(con, ino, data.get("kind") or ""):
                handler._redirect(f"/invoice/{ino}?msg=" + quote_plus("Paperwork removed"))
            else:
                handler._redirect(f"/invoice/{ino}?err=" + quote_plus("Nothing attached"))
    elif u.path.endswith("/line") and u.path.startswith("/invoice/"):
            ino = u.path.split("/")[2]
            engine.add_invoice_line(con, ino, {
                "po_line": data.get("po_line"),
                "category": data.get("category"),
                "description": data.get("description"),
                "qty": data.get("qty"),
                "uom": data.get("uom"),
                "rate": data.get("rate"),
                "clerk": data.get("clerk"),
            })
            handler._redirect(f"/invoice/{ino}?msg=Line+added")
    elif u.path.endswith("/linedel") and u.path.startswith("/invoice/"):
            engine.drop_invoice_line(con, int(data.get("line_id") or 0), data.get("clerk") or "")
            ino = data.get("invoice_no") or ""
            handler._redirect(f"/invoice/{ino}?msg=Line+removed")
    elif u.path == "/pay":
            # Ensure new columns exist (Jason 2026-10-07 F10)
            pcols = [r[1] for r in con.execute("PRAGMA table_info(collections)")]
            for col, ddl in [("pay_ref", "TEXT"), ("user_name", "TEXT")]:
                if col not in pcols:
                    con.execute(f"ALTER TABLE collections ADD COLUMN {col} {ddl}")
            res = engine.record_payment(
                con, data.get("invoice_no") or "", float(data.get("amount") or 0),
                data.get("pay_date") or date.today().isoformat(),
                data.get("method") or "", data.get("ref") or "", data.get("clerk") or "",
            )
            # Save extra fields
            if res.get("pay_id"):
                con.execute(
                    "UPDATE collections SET pay_ref=?, user_name=?, notes=? WHERE pay_id=?",
                    ((data.get("ref") or "").strip(),
                     (data.get("user_name") or "").strip(),
                     (data.get("notes") or "").strip(),
                     res["pay_id"]))
                con.commit()
                up = (handler._files or {}).get("pay_upload")
                if up and up[2]:
                    engine.save_job_attachment(con, "pay", str(res["pay_id"]), up[0], up[2], data.get("clerk", ""))
            ino2 = data.get("invoice_no") or ""
            if res["credit_memo"]:
                msg = (f"Payment recorded: ${res['applied']:,.2f} applied to {ino2} (paid in full); "
                       f"${res['credit_amount']:,.2f} overpayment kept as open credit {res['credit_memo']}.")
            else:
                msg = "Payment recorded"
            handler._redirect("/money?tab=pay&msg=" + quote_plus(msg))
    elif u.path == "/credit":
            applies = []
            for k, v in data.items():
                if k.startswith("a__") and v:
                    applies.append((k[3:], v))
            cno = engine.issue_credit_memo(
                con,
                data.get("customer_id") or "",
                data.get("face_amount") or 0,
                data.get("reason") or "",
                applies,
                data.get("cm_date") or None,
                data.get("notes") or "",
                data.get("clerk") or "",
            )
            # Save line items (Jason 2026-10-07 F11)
            cmcols = [r[1] for r in con.execute("PRAGMA table_info(credit_memos)")]
            for col, ddl in [("item", "TEXT"), ("item_desc", "TEXT"),
                             ("qty", "REAL DEFAULT 1"), ("rate", "REAL DEFAULT 0")]:
                if col not in cmcols:
                    con.execute(f"ALTER TABLE credit_memos ADD COLUMN {col} {ddl}")
            con.execute(
                "UPDATE credit_memos SET item=?, item_desc=?, qty=?, rate=? WHERE cm_no=?",
                ((data.get("item") or "").strip(),
                 (data.get("item_desc") or "").strip(),
                 float(data.get("qty") or 1),
                 float(data.get("rate") or 0),
                 cno))
            con.commit()
            up = (handler._files or {}).get("job_attach")
            if up and up[2]:
                engine.save_job_attachment(con, "credit", cno, up[0], up[2], data.get("clerk", ""))
            up2 = (handler._files or {}).get("cm_upload")
            if up2 and up2[2]:
                engine.save_job_attachment(con, "credit", cno, up2[0], up2[2], data.get("clerk", ""))
            handler._redirect(f"/money?tab=credit&msg=Credit+memo+{cno}+saved")
    elif u.path == "/credit/apply":
            applies = []
            for k, v in data.items():
                if k.startswith("a__") and v:
                    applies.append((k[3:], v))
            engine.apply_open_credit(
                con, data.get("cm_no") or "", applies, data.get("pay_date") or None,
                data.get("clerk") or "",
            )
            handler._redirect("/money?tab=credit&msg=Credit+applied")
    elif u.path == "/quote/save":
            lines = []
            for i in range(8):
                lines.append({
                    "kind": data.get(f"k{i}") or "other",
                    "asset_id": data.get(f"a{i}") or "",
                    "description": data.get(f"d{i}") or "",
                    "qty": data.get(f"q{i}") or 0,
                    "rate": data.get(f"r{i}") or 0,
                })
            qn = engine.save_quote(con, {
                "quote_no": data.get("quote_no") or None,
                "customer_id": data.get("customer_id"),
                "site_id": data.get("site_id"),
                "job_name": data.get("job_name"),
                "afe": data.get("afe"),
                "po": data.get("po"),
                "quote_date": data.get("quote_date"),
                "valid_until": data.get("valid_until"),
                "notes": data.get("notes"),
                "status": data.get("status") or "Draft",
                "clerk": data.get("clerk") or "",
            }, lines)
            up = (handler._files or {}).get("job_attach")
            if up and up[2]:
                engine.save_job_attachment(con, "quote", qn, up[0], up[2], data.get("clerk", ""))
            handler._redirect(f"/quotes?msg=Quote+saved")
    elif u.path.startswith("/quote/") and u.path.endswith("/status"):
            qn = u.path.split("/")[2]
            engine.set_quote_status(con, qn, data.get("status") or "")
            handler._redirect(f"/quote/{qn}?msg=Status+updated")
    elif u.path.startswith("/quote/") and u.path.endswith("/convert"):
            qn = u.path.split("/")[2]
            made = engine.convert_quote(con, qn, data.get("on_rent") or None)
            msg = "Tickets+" + "+".join(made) if made else "Quote+converted"
            handler._redirect(f"/quote/{qn}?msg={msg}")
    elif u.path == "/change/save":
            lines = []
            for i in range(6):
                lines.append({
                    "direction": data.get(f"dir{i}") or "add",
                    "kind": data.get(f"k{i}") or "other",
                    "description": data.get(f"d{i}") or "",
                    "qty": data.get(f"q{i}") or 0,
                    "rate": data.get(f"r{i}") or 0,
                })
            cno = engine.issue_change_order(
                con, data.get("quote_no") or "", data.get("reason") or "",
                lines, data.get("co_date") or None, data.get("notes") or "",
                data.get("clerk") or "", data.get("po") or "",
            )
            up = (handler._files or {}).get("job_attach")
            if up and up[2]:
                engine.save_job_attachment(con, "change", cno, up[0], up[2], data.get("clerk", ""))
            handler._redirect(f"/changes?msg=Change+order+{cno}+issued")
    elif u.path == "/petty":
            engine.record_petty(
                con,
                data.get("direction") or "",
                data.get("amount") or 0,
                data.get("category") or "",
                data.get("txn_date") or None,
                data.get("payee") or "",
                data.get("ref_no") or "",
                data.get("notes") or "",
                data.get("user_name") or data.get("clerk") or "",
            )
            handler._redirect("/money?tab=petty&msg=Petty+cash+saved")
    elif u.path == "/petty/float":
            engine.set_pc_float(con, float(data.get("pc_float") or 0))
            handler._redirect("/money?tab=petty&msg=Float+saved")
    elif u.path == "/customer/save":
            cid = data.get("customer_id") or None
            cid = engine.save_customer(con, {
                "account_name": data.get("account_name"),
                "short_name": data.get("short_name"),
                "bill_to": data.get("bill_to"),
                "phone": data.get("phone"),
                "email": data.get("email"),
                "bill_street": data.get("bill_street"),
                "bill_street2": data.get("bill_street2"),
                "bill_city": data.get("bill_city"),
                "bill_state": data.get("bill_state"),
                "bill_zip": data.get("bill_zip"),
                "terms": data.get("terms"),
                "tax_exempt": data.get("tax_exempt") == "1",
                "waiver_default": data.get("waiver_default") == "1",
                "credit_limit": data.get("credit_limit"),
                "notes": data.get("notes"),
            }, cid)
            # Setup flow (Jason 2026-10-08): during initial setup, saving
            # advances to the next step; after setup, stay on the page.
            nxt = next_setup_step(con, "/customers")
            if nxt:
                handler._redirect(nxt + "?from=setup&msg=Customer+saved")
            else:
                handler._redirect(f"/customers?msg=Customer+saved")
    elif u.path == "/customer/contact/save":
            cid=data.get("customer_id") or ""; name=(data.get("name") or "").strip()
            if not cid or not name: raise ValueError("Customer and contact name are required")
            if data.get("is_primary")=="1": con.execute("UPDATE customer_contacts SET is_primary=0 WHERE customer_id=?",(cid,))
            con.execute("INSERT INTO customer_contacts(customer_id,name,role,phone,email,is_primary) VALUES (?,?,?,?,?,?)",(cid,name,data.get("role") or "Other",data.get("phone") or "",data.get("email") or "",1 if data.get("is_primary")=="1" else 0))
            con.commit(); handler._redirect(f"/customer/{cid}#contacts")
    elif u.path == "/customer/contact/delete":
            cid=data.get("customer_id") or ""; con.execute("DELETE FROM customer_contacts WHERE contact_id=? AND customer_id=?",(int(data.get("contact_id") or 0),cid)); con.commit(); handler._redirect(f"/customer/{cid}#contacts")
    elif u.path == "/customer/location/save":
            cid=data.get("customer_id") or ""; name=(data.get("location_name") or "").strip()
            if not cid or not name: raise ValueError("Customer and location name are required")
            if data.get("is_primary")=="1": con.execute("UPDATE customer_locations SET is_primary=0 WHERE customer_id=?",(cid,))
            con.execute("INSERT INTO customer_locations(customer_id,location_name,street,street2,city,state,zip,is_primary) VALUES (?,?,?,?,?,?,?,?)",(cid,name,data.get("street") or "",data.get("street2") or "",data.get("city") or "",data.get("state") or "",data.get("zip") or "",1 if data.get("is_primary")=="1" else 0))
            con.commit(); handler._redirect(f"/customer/{cid}#locations")
    elif u.path == "/customer/location/delete":
            cid=data.get("customer_id") or ""; con.execute("DELETE FROM customer_locations WHERE location_id=? AND customer_id=?",(int(data.get("location_id") or 0),cid)); con.commit(); handler._redirect(f"/customer/{cid}#locations")
    elif u.path == "/export/run":
            what = data.get("what") or "all"
            how = data.get("how") or "csv"
            start, end = handler._export_range(data)
            out, fname = handler._export_build(con, what, how, start, end)
            folder = engine.backup_folder(con)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / fname).write_bytes(out)
            handler._redirect("/export?msg=Saved+" + fname.replace(" ", "+") + "+to+" + str(folder).replace(" ", "+"))
    elif u.path == "/export/save":
            engine.save_export(
                con,
                data.get("label") or "",
                data.get("what") or "all",
                data.get("when") or "all",
                data.get("from") or "",
                data.get("to") or "",
                data.get("how") or "csv",
            )
            handler._redirect("/export?msg=Preset+saved")
    elif u.path == "/export/saved/del":
            engine.delete_saved_export(con, data.get("export_id") or "")
            handler._redirect("/export?msg=Preset+removed")
    elif u.path == "/export/custom/save":
            fields = [k[2:] for k, v in data.items() if k.startswith("f_") and v]
            rid = engine.save_custom_report(
                con,
                data.get("label") or "",
                data.get("ds") or "tickets",
                fields,
                data.get("cfrom") or "",
                data.get("cto") or "",
                data.get("cfield") or "",
                data.get("ctext") or "",
                data.get("csort") or "",
                data.get("cdir") or "asc",
                data.get("how") or "csv",
            )
            handler._redirect("/export?msg=Build+saved")
    elif u.path == "/export/custom/del":
            try:
                rid = int(data.get("report_id") or 0)
            except (TypeError, ValueError):
                rid = 0
            engine.delete_custom_report(con, rid)
            handler._redirect("/export?msg=Build+removed")
    else:
        return False
    return True
