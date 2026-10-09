"""Concurrent sequence-allocation regression tests for desk + yard writers."""
from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

import engine


class SequenceAllocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="fleetsheet-seq-")
        self.db = Path(self.tmp.name) / "test.db"
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        engine.init_db(con)
        con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def _parallel(self, fn, count=12):
        out, errors = [], []
        lock = threading.Lock()
        barrier = threading.Barrier(count)

        def worker():
            con = None
            try:
                con = engine.connect(self.db)
                barrier.wait()
                value = fn(con)
                con.commit()
                with lock:
                    out.append(value)
            except Exception as exc:
                with lock:
                    errors.append(exc)
            finally:
                if con:
                    con.close()

        threads = [threading.Thread(target=worker) for _ in range(count)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(errors, [], [repr(e) for e in errors])
        self.assertEqual(len(out), count)
        self.assertEqual(len(set(out)), count)
        return out

    def test_ticket_numbers_are_unique_under_concurrency(self):
        vals = self._parallel(engine.next_ticket_id)
        self.assertEqual(len(vals), 12)

    def test_document_counters_are_unique_under_concurrency(self):
        for fn in (engine.next_invoice_id, engine.next_cm_id, engine.next_quote_id,
                   engine.next_co_id, engine.next_pc_id, engine.next_wo_id):
            vals = self._parallel(fn, 8)
            self.assertEqual(len(vals), 8)


if __name__ == '__main__':
    unittest.main(verbosity=2)
