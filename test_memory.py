"""
test_memory.py — Test suite for the hardened ZYRA memory store (memory.py).

Covers thread-safety, atomic persistence, corruption recovery, and the extended
API. Uses an isolated temporary store so the real memory/data.json is untouched.
"""

import json
import os
import sys
import tempfile
import threading
import unittest


# Point memory at an isolated temporary file BEFORE importing it.
_TMP_DIR = tempfile.mkdtemp()
_TMP_STORE = os.path.join(_TMP_DIR, "memory", "data.json")
os.environ["ZYRA_MEMORY_FILE"] = _TMP_STORE

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memory  # noqa: E402


class TestMemoryStore(unittest.TestCase):
    def setUp(self):
        memory.clear_memory()

    def tearDown(self):
        memory.clear_memory()

    def test_remember_recall(self):
        memory.remember("name", "Ada")
        self.assertEqual(memory.recall("name"), "Ada")
        self.assertIsNone(memory.recall("missing_key"))

    def test_remember_overwrites_and_snapshot_isolation(self):
        memory.remember("score", 1)
        memory.remember("score", 2)
        data = memory.all_memory()
        self.assertEqual(data["score"], 2)
        # Mutating the returned dict must not touch the store.
        data["new"] = "x"
        self.assertNotIn("new", memory.all_memory())

    def test_remember_many(self):
        memory.remember_many({"a": 1, "b": 2, "c": 3})
        self.assertEqual(memory.all_memory(), {"a": 1, "b": 2, "c": 3})

    def test_forget(self):
        memory.remember("k", "v")
        self.assertTrue(memory.forget("k"))
        self.assertIsNone(memory.recall("k"))
        self.assertFalse(memory.forget("k"))

    def test_clear_memory(self):
        memory.remember("k", "v")
        memory.clear_memory()
        self.assertEqual(memory.all_memory(), {})

    def test_load_save_cycle(self):
        memory.save_memory({"x": [1, 2]})
        self.assertEqual(memory.load_memory(), {"x": [1, 2]})
        self.assertEqual(memory.stats()["keys"], ["x"])

    def test_unrelated_writes_leave_valid_file_without_leftovers(self):
        for i in range(10):
            memory.remember(f"key_{i}", i * i)
        with open(_TMP_STORE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 10)
        # Atomic-write temp files (prefix "zyra_memory_") must never remain.
        # (.corrupt-* files are intentionally preserved backups, not leftovers.)
        leftovers = [
            name
            for name in os.listdir(os.path.dirname(_TMP_STORE))
            if name.startswith("zyra_memory_")
        ]
        self.assertEqual(leftovers, [])

    def test_concurrent_writers(self):
        """8 threads x 20 writes with zero lost updates."""
        def writer(wid):
            for j in range(20):
                memory.remember(f"t{wid}_{j}", wid * 1000 + j)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        data = memory.all_memory()
        self.assertEqual(len(data), 8 * 20)
        self.assertEqual(data["t7_19"], 7 * 1000 + 19)

    def test_corrupt_file_backup_and_recovery(self):
        """Damaged JSON is backed up and a fresh store is returned."""
        memory.remember("keep", "me")
        existing_backups = [
            name
            for name in os.listdir(os.path.dirname(_TMP_STORE))
            if name.startswith("data.json.corrupt")
        ]
        with open(_TMP_STORE, "w", encoding="utf-8") as fh:
            fh.write("{definitely not valid json")
        self.assertEqual(memory.all_memory(), {})
        # A new backup file exists.
        backups = [
            name
            for name in os.listdir(os.path.dirname(_TMP_STORE))
            if name.startswith("data.json.corrupt")
        ]
        self.assertEqual(len(backups), len(existing_backups) + 1)
        # The store keeps working afterwards.
        memory.remember("after", "ok")
        self.assertEqual(memory.recall("after"), "ok")

    def test_non_dict_root_is_treated_as_corrupt(self):
        with open(_TMP_STORE, "w", encoding="utf-8") as fh:
            json.dump(["not", "a", "dict"], fh)
        self.assertEqual(memory.all_memory(), {})
        memory.remember("still", "works")
        self.assertEqual(memory.recall("still"), "works")


if __name__ == "__main__":
    unittest.main(verbosity=2)