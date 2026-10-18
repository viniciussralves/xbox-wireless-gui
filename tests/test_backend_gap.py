"""Fecha os últimos gaps de cobertura do backend (todos com mock)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backend import battery, firmware, inputs, permissions, prefs, updates, xone, xow


class TestGapBattery(unittest.TestCase):
    def test_icon_low_and_full(self):
        self.assertEqual(battery.icon_for(20, "discharging", "normal"),
                         "battery-low-symbolic")
        self.assertEqual(battery.icon_for(96, "discharging", "normal"),
                         "battery-full-symbolic")


class TestGapFirmware(unittest.TestCase):
    def test_script_found(self):
        with mock.patch("shutil.which", return_value="/usr/bin/xone-get-firmware.sh"):
            self.assertEqual(firmware.script_for("xone"),
                             "/usr/bin/xone-get-firmware.sh")


class TestGapI18n(unittest.TestCase):
    def test_null_when_no_lang(self):
        from backend import i18n
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch("backend.i18n.locale.getdefaultlocale",
                        return_value=(None, None)):
            tr = i18n.get_translation()
            self.assertEqual(tr.gettext("Bateria"), "Bateria")

    def test_found_translation(self):
        from backend import i18n
        fake = mock.Mock()
        with mock.patch.dict(os.environ, {"LANGUAGE": "en"}), \
             mock.patch("backend.i18n.gettext.translation",
                        return_value=fake) as t:
            self.assertIs(i18n.get_translation(), fake)
            t.assert_called_once()


class TestGapInputs(unittest.TestCase):
    def test_all_abs_codes(self):
        from evdev import ecodes
        st = inputs.new_state()
        lim = {ecodes.ABS_Y: (-32768, 32767),
               ecodes.ABS_RX: (-32768, 32767),
               ecodes.ABS_RY: (-32768, 32767),
               ecodes.ABS_Z: (0, 255),
               ecodes.ABS_HAT0X: (-1, 1)}
        self.assertTrue(inputs.apply_abs(st, ecodes.ABS_Y, 32767, lim))
        self.assertTrue(inputs.apply_abs(st, ecodes.ABS_RX, -32768, lim))
        self.assertTrue(inputs.apply_abs(st, ecodes.ABS_RY, 0, lim))
        self.assertTrue(inputs.apply_abs(st, ecodes.ABS_Z, 255, lim))
        self.assertTrue(inputs.apply_abs(st, ecodes.ABS_HAT0X, 1, lim))
        self.assertEqual(inputs.pressed_names(inputs.new_state()), [])

    def test_resync_limits_change(self):
        from evdev import ecodes

        class Dev:
            def active_keys(self):
                return []

            def absinfo(self, code):
                class A:
                    value = 100
                return A()

        st = inputs.new_state()
        changed = inputs.resync(st, Dev(), {ecodes.ABS_X: (0, 100)})
        self.assertTrue(changed)
        self.assertEqual(st["lx"], 1.0)

    def test_list_devices_limits(self):
        import evdev
        from evdev import ecodes

        class Info:
            min = 0
            max = 255

        class Dev:
            def __init__(self, path):
                pass

            def capabilities(self, absinfo=False):
                if absinfo:
                    return {ecodes.EV_ABS: [(ecodes.ABS_X, Info())]}
                return {}

            def close(self):
                pass

        with mock.patch("backend.rumble.find_gamepads",
                        return_value=[{"path": "/r", "name": "Pad",
                                      "has_rumble": False}]), \
             mock.patch.object(evdev, "InputDevice", Dev):
            out = inputs.list_devices()
        self.assertEqual(out[0]["limits"], {ecodes.ABS_X: (0, 255)})


class TestGapPermissions(unittest.TestCase):
    def test_status_all_problems(self):
        with mock.patch("backend.permissions.rule_installed",
                        return_value=None), \
             mock.patch("backend.permissions.in_input_group",
                        return_value=False), \
             mock.patch("backend.permissions.leds_writable",
                        return_value=(False, ["a"])), \
             mock.patch("backend.permissions.pairing_writable",
                        return_value=(False, ["b"])), \
             mock.patch("backend.permissions.evdev_readable",
                        return_value=(False, "eventX")):
            st = permissions.status()
        self.assertFalse(st["ok"])
        self.assertIn("input", st["detail"])

    def test_rule_source_found(self):
        with mock.patch("os.path.isfile", return_value=True):
            src = permissions._rule_source()
            self.assertTrue(src.endswith(".rules"))

    def test_login_user_variants(self):
        with mock.patch.dict(os.environ, {"PKEXEC_UID": "1000",
                                          "SUDO_UID": ""}), \
             mock.patch("backend.permissions.pwd.getpwuid",
                        return_value=mock.Mock(pw_name="nomade")):
            self.assertEqual(permissions._login_user(), "nomade")
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch("backend.permissions.pwd.getpwuid",
                        side_effect=KeyError()):
            self.assertEqual(permissions._login_user(), "")


class TestGapPrefs(unittest.TestCase):
    def test_gsettings_new_raises(self):
        import types
        fake_repo = types.ModuleType("gi.repository")
        fake_gio = mock.Mock()
        fake_source = mock.Mock()
        fake_source.lookup.return_value = object()
        fake_gio.SettingsSchemaSource.get_default.return_value = fake_source
        fake_gio.Settings.new.side_effect = RuntimeError("no schema")
        fake_repo.Gio = fake_gio
        fake_gi = types.ModuleType("gi")
        fake_gi.require_version = mock.Mock()
        with mock.patch.dict(sys.modules, {"gi": fake_gi,
                                           "gi.repository": fake_repo}):
            p = prefs.Prefs()
            self.assertEqual(p.backend, "memory")

    def test_get_prefs_singleton(self):
        prefs._prefs = None
        a = prefs.get_prefs()
        b = prefs.get_prefs()
        self.assertIs(a, b)


class TestGapUpdates(unittest.TestCase):
    def test_norm_mixed_and_compare(self):
        self.assertEqual(updates._norm("v1.x"), (1, "x"))
        self.assertTrue(updates.is_newer("1.x", "1.0"))
        self.assertFalse(updates.is_newer("1.0", "1.0"))


class TestGapXone(unittest.TestCase):
    def test_pairing_file_none_and_get_none(self):
        with mock.patch("backend.xone.glob.glob", return_value=[]):
            self.assertIsNone(xone.get_pairing_file())
        with mock.patch("backend.xone.get_pairing_file",
                        return_value=None):
            self.assertIsNone(xone.get_pairing())
        with mock.patch("backend.xone.get_pairing_file",
                        return_value=None):
            ok, _ = xone.set_pairing(True)
            self.assertFalse(ok)

    def test_set_pairing_oserror(self):
        with mock.patch("backend.xone.get_pairing_file",
                        return_value="/sys/bus/usb/drivers/xone-dongle/d/pairing"), \
             mock.patch("builtins.open", side_effect=OSError("disk")):
            ok, msg = xone.set_pairing(True)
        self.assertFalse(ok)
        self.assertIn("disk", msg)

    def test_set_led_range_mocked(self):
        m = mock.mock_open(read_data="50")
        with mock.patch("os.path.isdir", return_value=True), \
             mock.patch("builtins.open", m):
            ok, msg = xone.set_led("gip0", "2", "51")
        self.assertFalse(ok)
        self.assertIn("0-50", msg)

    def test_set_led_pkexec_ok(self):
        m = mock.mock_open(read_data="50")
        m.side_effect = [mock.mock_open(read_data="50").return_value,
                         PermissionError(), PermissionError()]
        with mock.patch("os.path.isdir", return_value=True), \
             mock.patch("builtins.open", m), \
             mock.patch("backend.xone._run_pkexec_shell",
                        return_value=mock.Mock(returncode=0)):
            ok, _ = xone.set_led("gip0", "2", "5")
        self.assertTrue(ok)


class TestGapXow(unittest.TestCase):
    def test_set_pairing_fail_msg(self):
        with mock.patch("backend.xow.subprocess.run",
                        return_value=mock.Mock(returncode=1, stderr="",
                                              stdout="denied")):
            ok, msg = xow.set_pairing()
        self.assertFalse(ok)
        self.assertEqual(msg, "denied")


if __name__ == "__main__":
    unittest.main()
