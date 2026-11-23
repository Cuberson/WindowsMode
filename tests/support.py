"""Shared test support: isolated data dir per test so tests can never touch
real projects/sessions/memory (mirrors XCTest's CONDUCTOR_DATA_DIR override)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


class IsolatedDataDirTest(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="ConductorTests-")
        os.environ["CONDUCTOR_DATA_DIR"] = self._tmp.name
        self.data_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        os.environ.pop("CONDUCTOR_DATA_DIR", None)
        self._tmp.cleanup()
        super().tearDown()


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")
