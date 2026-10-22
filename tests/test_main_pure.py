"""Funções puras de main.py (sem display)."""
import os

from tests import _env  # noqa: F401
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import main


class TestPure(unittest.TestCase):
    def test_fmt_duration(self):
        self.assertEqual(main.fmt_duration(None), "")
        self.assertEqual(main.fmt_duration(0), "")
        self.assertEqual(main.fmt_duration(-3), "")
        self.assertEqual(main.fmt_duration(5), "5s")
        self.assertEqual(main.fmt_duration(59), "59s")
        self.assertEqual(main.fmt_duration(60), "1min")
        self.assertEqual(main.fmt_duration(125), "2min")
        self.assertEqual(main.fmt_duration(3600), "1h00")
        self.assertEqual(main.fmt_duration(3661), "1h01")

    def test_bat_time_text(self):
        self.assertEqual(main.bat_time_text(
            {"state_en": "discharging", "state": "X", "time_empty": 3600}),
            "1h00 restantes")
        self.assertEqual(main.bat_time_text(
            {"state_en": "charging", "state": "X", "time_full": 1800}),
            "cheio em 30min")
        self.assertEqual(main.bat_time_text(
            {"state_en": "fully-charged", "state": "Carregada"}),
            "carregado")
        self.assertEqual(main.bat_time_text(
            {"state_en": "fully-charged", "state": "Carregada",
             "time_full": 600}), "carregado")
        self.assertEqual(main.bat_time_text(
            {"state_en": "discharging", "state": "Descarregando"}),
            "Descarregando")
        self.assertEqual(main.bat_time_text({"state": "?"}), "?")
        self.assertEqual(main.bat_time_text({}), "")


if __name__ == "__main__":
    unittest.main()
