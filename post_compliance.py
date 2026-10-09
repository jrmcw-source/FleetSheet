"""FleetSheet POST actions — certification/calibration flow: compliance packs and checklist items."""
import html
from datetime import date

import engine
from urllib.parse import quote_plus


def handle_post(handler, con, data, u):
    """Handle one POST. Returns True when the path was handled."""
    if u.path == "/compliance/assign":
            aid = data.get("asset_id") or ""
            try:
                n = engine.assign_pack(con, aid, data.get("pack_id") or "")
                handler._redirect(f"/ucompliance/{aid}?msg=" + quote_plus(f"Pack assigned — {n} checks added"))
            except ValueError as e:
                handler._redirect(f"/ucompliance/{aid}?err=" + quote_plus(str(e)))
    elif u.path == "/compliance/custom":
            aid = data.get("asset_id") or ""
            try:
                engine.add_custom_requirement(con, aid, data.get("name"),
                                            data.get("trigger"),
                                            data.get("interval_months"),
                                            data.get("backstop_months"),
                                            data.get("notes"))
                handler._redirect(f"/ucompliance/{aid}?msg=" + quote_plus("Check added"))
            except ValueError as e:
                handler._redirect(f"/ucompliance/{aid}?err=" + quote_plus(str(e)))
    elif u.path == "/compliance/item/done":
            eid = (data.get("eqc_id") or "").strip()
            aid = handler._eqc_asset(con, eid)
            nxt = data.get("next") or f"/ucompliance/{aid}"
            try:
                notes = data.get("notes") or ""
                if data.get("data_book_ok") == "1":
                    notes = (notes + " " if notes else "") + "[data book checked]"
                engine.record_completion(con, int(eid), data.get("done_date"),
                                         data.get("result") or "pass",
                                         data.get("evidence"), notes,
                                         data.get("clerk"))
                up = (handler._files or {}).get("doc_file")
                if up and up[2]:
                    engine.save_unit_doc(con, aid, data.get("evidence") or up[0] or "compliance doc",
                                         "other", up[0] or "", up[2],
                                         data.get("clerk"))
                handler._redirect(nxt + ("&" if "?" in nxt else "?") + "msg=" + quote_plus("Recorded"))
            except (ValueError, TypeError) as e:
                handler._redirect(f"/ucompliance/{aid}?err=" + quote_plus(str(e)))
    elif u.path == "/compliance/item/save":
            eid = (data.get("eqc_id") or "").strip()
            aid = handler._eqc_asset(con, eid)
            try:
                engine.update_checklist_item(con, int(eid),
                                             trigger=data.get("trigger") or None,
                                             interval_months=data.get("interval_months"),
                                             backstop_months=data.get("backstop_months"),
                                             notes=data.get("notes"),
                                             custom_name=data.get("custom_name") or None)
                perf = (data.get("performer_id") or "").strip()
                engine.set_checklist_performer(con, int(eid), int(perf) if perf else None)
                handler._redirect(f"/ucompliance/{aid}?msg=" + quote_plus("Check updated"))
            except (ValueError, TypeError) as e:
                handler._redirect(f"/ucompliance/{aid}?err=" + quote_plus(str(e)))
    elif u.path == "/compliance/item/delete":
            eid = (data.get("eqc_id") or "").strip()
            aid = handler._eqc_asset(con, eid)
            try:
                engine.remove_checklist_item(con, int(eid))
                handler._redirect(f"/ucompliance/{aid}?msg=" + quote_plus("Check removed"))
            except (ValueError, TypeError) as e:
                handler._redirect(f"/ucompliance/{aid}?err=" + quote_plus(str(e)))
    elif u.path == "/compliance/doc/upload":
            aid = data.get("asset_id") or ""
            up = (handler._files or {}).get("doc_file")
            try:
                if not up or not up[2]:
                    raise ValueError("Choose a file to attach")
                doc_id = engine.save_unit_doc(con, aid, data.get("title"),
                                             data.get("kind") or "other",
                                             up[0] or "", up[2],
                                             data.get("clerk"))
                handler._redirect(f"/ucompliance/{aid}?msg=" + quote_plus("Document added to the data book"))
            except ValueError as e:
                handler._redirect(f"/ucompliance/{aid}?err=" + quote_plus(str(e)))
    elif u.path == "/compliance/doc/delete":
            try:
                doc_id = int(data.get("doc_id") or 0)
            except (TypeError, ValueError):
                doc_id = 0
            row = engine.get_unit_doc(con, doc_id)
            aid = row["asset_id"] if row else ""
            if engine.delete_unit_doc(con, doc_id):
                handler._redirect(f"/ucompliance/{aid}?msg=" + quote_plus("Document removed"))
            else:
                handler._redirect(f"/ucompliance/{aid}?err=" + quote_plus("Unknown document"))
    # ---- Cert records: every certification/calibration/function test names its asset. ----
    elif u.path == "/compliance/cert/save":
            cert_id = (data.get("cert_id") or "").strip()
            try:
                if cert_id:
                    aid = handler._cert_asset(con, cert_id)
                    engine.update_cert(
                        con, int(cert_id),
                        kind=data.get("kind"), title=data.get("title"),
                        cert_number=data.get("cert_number"), issuer=data.get("issuer"),
                        issued_date=data.get("issued_date"), expiry_date=data.get("expiry_date"),
                        notes=data.get("notes"))
                else:
                    aid = (data.get("asset_id") or "").strip()
                    cert_id = engine.save_cert(
                        con, aid, data.get("kind") or "certification",
                        data.get("title") or "",
                        cert_number=data.get("cert_number") or "",
                        issuer=data.get("issuer") or "",
                        issued_date=data.get("issued_date") or None,
                        expiry_date=data.get("expiry_date") or None,
                        notes=data.get("notes") or "", clerk=data.get("clerk") or "")
                    # Optional evidence file: into this unit's data book, attached to the record.
                    up = (handler._files or {}).get("doc_file")
                    if up and up[2]:
                        doc_id = engine.save_unit_doc(
                            con, aid, data.get("title") or "certificate",
                            "cert", up[0] or "", up[2], data.get("clerk"))
                        engine.attach_cert_evidence(con, cert_id, doc_id)
                handler._redirect(f"/ucompliance/{aid}?msg=" + quote_plus("Certificate saved"))
            except (ValueError, TypeError) as e:
                aid = (data.get("asset_id") or "").strip() or handler._cert_asset(con, cert_id)
                handler._redirect(f"/ucompliance/{aid}?err=" + quote_plus(str(e)))
    elif u.path == "/compliance/cert/evidence":
            cert_id = (data.get("cert_id") or "").strip()
            aid = handler._cert_asset(con, cert_id)
            try:
                engine.attach_cert_evidence(con, int(cert_id), int(data.get("doc_id") or 0))
                handler._redirect(f"/ucompliance/{aid}?msg=" + quote_plus("Evidence attached"))
            except (ValueError, TypeError) as e:
                handler._redirect(f"/ucompliance/{aid}?err=" + quote_plus(str(e)))
    elif u.path == "/compliance/cert/supersede":
            cert_id = (data.get("cert_id") or "").strip()
            aid = handler._cert_asset(con, cert_id)
            try:
                engine.set_cert_superseded(con, int(cert_id), data.get("restore") != "1")
                handler._redirect(f"/ucompliance/{aid}?msg=" + quote_plus("Certificate updated"))
            except (ValueError, TypeError) as e:
                handler._redirect(f"/ucompliance/{aid}?err=" + quote_plus(str(e)))
    elif u.path == "/compliance/cert/delete":
            cert_id = (data.get("cert_id") or "").strip()
            aid = handler._cert_asset(con, cert_id)
            try:
                engine.delete_cert(con, int(cert_id))
                handler._redirect(f"/ucompliance/{aid}?msg=" + quote_plus("Certificate removed"))
            except (ValueError, TypeError) as e:
                handler._redirect(f"/ucompliance/{aid}?err=" + quote_plus(str(e)))
    else:
        return False
    return True
