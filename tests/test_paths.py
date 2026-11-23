"""Paths + crash-safe JSON persistence + app log rotation."""

import unittest

from conductor.core.paths import AppLog, JSONStore, data_dir, logs_dir

from .support import IsolatedDataDirTest


class PathsTests(IsolatedDataDirTest):
    def test_data_dir_honours_override(self):
        self.assertEqual(data_dir(), self.data_dir)
        self.assertTrue((self.data_dir / "logs").is_dir())

    def test_json_store_round_trip(self):
        path = self.data_dir / "thing.json"
        JSONStore.save_raw({"b": 1, "a": [1, 2]}, path)
        self.assertEqual(JSONStore.load_raw(path), {"a": [1, 2], "b": 1})
        self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_load_missing_or_corrupt_returns_none(self):
        path = self.data_dir / "missing.json"
        self.assertIsNone(JSONStore.load_raw(path))
        path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(JSONStore.load_raw(path))

    def test_app_log_write(self):
        AppLog.write("hello")
        AppLog._handle and AppLog._handle.close()
        AppLog._handle = None
        content = (logs_dir() / "app.log").read_text(encoding="utf-8")
        self.assertIn("hello", content)


if __name__ == "__main__":
    unittest.main()
