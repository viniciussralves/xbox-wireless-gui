"""Testes unitários do backend (sem hardware: sysfs/evdev/UPower com mock)."""
import os

from tests import _env  # noqa: F401
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backend import battery, bluetooth, detector, firmware, inputs, permissions, prefs, rumble, updates, xone, xow


class TestBattery(unittest.TestCase):
    def test_translate(self):
        self.assertEqual(battery.translate_state("charging"), "Carregando")
        self.assertEqual(battery.translate_state("discharging"), "Descarregando")
        self.assertEqual(battery.translate_state("fully-charged"), "Carregada")

    def test_icon_full_before_charg(self):
        self.assertEqual(battery.icon_for(100, "fully-charged", "full"),
                         "battery-full-charged-symbolic")
        self.assertEqual(battery.icon_for(50, "charging", "normal"),
                         "battery-good-charging-symbolic")
        self.assertEqual(battery.icon_for(70, "discharging", "high"),
                         "battery-good-symbolic")
        self.assertEqual(battery.icon_for(10, "discharging", "normal"),
                         "battery-empty-symbolic")


class TestInputs(unittest.TestCase):
    def test_norms(self):
        self.assertAlmostEqual(inputs._norm_stick(0, -32768, 32767), 0.0, places=2)
        self.assertEqual(inputs._norm_stick(-32768, -32768, 32767), -1.0)
        self.assertEqual(inputs._norm_trigger(255, 0, 255), 1.0)

    def test_deadzone(self):
        self.assertEqual(inputs._norm_stick(100, -32768, 32767, deadzone=0.1), 0.0)
        self.assertNotEqual(inputs._norm_stick(32767, -32768, 32767, deadzone=0.1), 0.0)

    def test_key_abs(self):
        from evdev import ecodes
        st = inputs.new_state()
        self.assertTrue(inputs.apply_key(st, ecodes.BTN_SOUTH, True))
        self.assertTrue(st["a"])
        self.assertFalse(inputs.apply_key(st, 999999, True))
        st2 = inputs.new_state()
        self.assertTrue(inputs.apply_abs(st2, ecodes.ABS_X, 32767,
                                        {ecodes.ABS_X: (-32768, 32767)}))
        self.assertEqual(st2["lx"], 1.0)

    def test_resync(self):
        from evdev import ecodes

        class Fake:
            def active_keys(self):
                return [ecodes.BTN_SOUTH]

            def absinfo(self, code):
                class A:
                    value = 0
                return A()

        st = inputs.new_state()
        st["b"] = True
        self.assertTrue(inputs.resync(st, Fake(), {}))
        self.assertTrue(st["a"])
        self.assertFalse(st["b"])


class TestDetector(unittest.TestCase):
    def test_xone_mocked(self):
        with mock.patch("backend.detector.glob.glob",
                        return_value=["/sys/bus/usb/drivers/xone-dongle/1-1:1.0"]):
            self.assertIn("1-1", detector.detect_xone_dongle())

    def test_xow_which(self):
        with mock.patch("shutil.which", return_value="/usr/bin/xow"):
            self.assertTrue(detector.detect_xow())


class TestXoneValidation(unittest.TestCase):
    def test_pairing_file_rejects(self):
        for bad in (None, "", "/etc/passwd",
                    "/tmp/pairing",
                    "/sys/bus/usb/drivers/xone-dongle/../x/pairing"):
            self.assertIsNone(xone._valid_pairing_file(bad))

    def test_set_led_rejects_without_write(self):
        for args in [("", "2", "5"), ("x;rm", "2", "5"),
                     ("gip0.0:white:status", "7", "5"),
                     ("gip0.0:white:status", "2", "abc"),
                     ("gip99", "2", "1")]:
            ok, _ = xone.set_led(*args)
            self.assertFalse(ok)

    def test_list_controllers_type(self):
        self.assertIsInstance(xone.list_controllers(), list)


class TestFirmwarePermissionsBT(unittest.TestCase):
    def test_firmware_status_keys(self):
        st = firmware.status("xone")
        self.assertIn(st["state"], ("installed", "missing"))
        self.assertIn("detail", st)

    def test_permissions_status_keys(self):
        st = permissions.status()
        for k in ("ok", "rule", "in_input_group", "problems", "detail"):
            self.assertIn(k, st)

    def test_bt_bogus_path(self):
        self.assertFalse(bluetooth.is_bluetooth("/dev/input/event9999"))
        ok, _ = bluetooth.disconnect("/dev/input/event9999")
        self.assertFalse(ok)


class TestPrefsUpdates(unittest.TestCase):
    def test_prefs_roundtrip(self):
        p = prefs.Prefs()
        p.set_int("rumble-duration", 700)
        self.assertEqual(p.get_int("rumble-duration"), 700)
        p.set_double("tester-deadzone", 0.1)
        self.assertAlmostEqual(p.get_double("tester-deadzone"), 0.1)

    def test_rumble_magnitudes(self):
        p = prefs.Prefs()
        p.set_int("rumble-strong", 100)
        s, _ = prefs.rumble_magnitudes(p)
        self.assertEqual(s, 0xFFFF)

    def test_updates_compare(self):
        self.assertTrue(updates.is_newer("v0.2.0", "0.1.0"))
        self.assertFalse(updates.is_newer("0.1.0", "0.1.0"))


class TestRumbleXow(unittest.TestCase):
    def test_rumble_bogus(self):
        ok, _ = rumble.rumble("/dev/input/event9999", duration_ms=50)
        self.assertFalse(ok)

    def test_xow_hint(self):
        self.assertIn("xow", xow.firmware_hint())


class TestI18nHygiene(unittest.TestCase):
    def test_no_shadowed_gettext(self):
        """Nenhum método pode usar `*_` (vira tupla `_` e quebra o gettext)."""
        import re
        path = os.path.join(os.path.dirname(__file__), "..", "src", "main.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        bad = re.findall(r"def \w+\(self, \*_\):", src)
        self.assertEqual(bad, [], f"métodos com `*_`: {bad}")
        loops = re.findall(r"for _ in ", src)
        self.assertEqual(loops, [], "`for _ in` sombreia o gettext")


if __name__ == "__main__":
    unittest.main()
