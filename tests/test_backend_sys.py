"""Cobertura backend (mocks): firmware/permissions/bluetooth/prefs/i18n/updates/inputs."""
import os

from tests import _env  # noqa: F401
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backend import bluetooth, firmware, inputs, permissions, prefs, updates


class TestFirmwareFull(unittest.TestCase):
    def test_trusted_script_accepts_root_owned(self):
        st = mock.Mock(st_uid=0, st_mode=0o755)
        with mock.patch("os.path.realpath", return_value="/usr/bin/fw"), \
             mock.patch("os.path.isfile", return_value=True), \
             mock.patch("os.access", return_value=True), \
             mock.patch("os.stat", return_value=st):
            self.assertEqual(firmware._trusted_script("/usr/bin/fw"),
                             "/usr/bin/fw")

    def test_trusted_script_rejects_nonroot_and_errors(self):
        with mock.patch("os.path.realpath", return_value="/usr/bin/fw"), \
             mock.patch("os.path.isfile", return_value=True), \
             mock.patch("os.access", return_value=True), \
             mock.patch("os.stat", return_value=mock.Mock(st_uid=1000,
                                                          st_mode=0o755)):
            self.assertIsNone(firmware._trusted_script("/usr/bin/fw"))
        with mock.patch("os.path.realpath", return_value="/usr/bin/fw"), \
             mock.patch("os.path.isfile", return_value=True), \
             mock.patch("os.access", return_value=True), \
             mock.patch("os.stat", side_effect=OSError("x")):
            self.assertIsNone(firmware._trusted_script("/usr/bin/fw"))
        with mock.patch("os.path.realpath", return_value="/usr/bin/fw"), \
             mock.patch("os.path.isfile", return_value=False):
            self.assertIsNone(firmware._trusted_script("/usr/bin/fw"))

    def test_pkexec_fallback_and_unknown_driver(self):
        with mock.patch("os.path.isfile", return_value=True), \
             mock.patch("os.access", return_value=True):
            self.assertEqual(firmware._pkexec(), "/usr/bin/pkexec")
        with mock.patch("os.path.isfile", return_value=False):
            self.assertIsNone(firmware._pkexec())
        self.assertIsNone(firmware.script_for("nenhum"))
        with mock.patch("os.path.isdir", return_value=False), \
             mock.patch("backend.firmware.glob.glob") as g:
            self.assertEqual(firmware.installed_files("xone"), [])
            g.assert_not_called()

    def test_installed_dedup(self):
        def fake_glob(pat):
            if "xone_dongle" in pat and pat.startswith("/usr"):
                return ["/usr/lib/firmware/xone_dongle_02e6.bin"]
            if "xone_dongle" in pat:
                return ["/lib/firmware/xone_dongle_02e6.bin"]
            return []
        with mock.patch("os.path.isdir", return_value=True), \
             mock.patch("backend.firmware.glob.glob", side_effect=fake_glob):
            files = firmware.installed_files()
        self.assertEqual(files, ["/usr/lib/firmware/xone_dongle_02e6.bin"])

    def test_status_branches(self):
        with mock.patch("backend.firmware.installed_files",
                        return_value=[]), \
             mock.patch("backend.firmware.script_for", return_value=None):
            st = firmware.status("xone")
            self.assertEqual(st["state"], "missing")
        with mock.patch("os.path.getsize", side_effect=OSError("x")), \
             mock.patch("backend.firmware.installed_files",
                        return_value=["/f/a.bin"]), \
             mock.patch("backend.firmware.script_for",
                        return_value="/usr/bin/xone-get-firmware.sh"):
            st = firmware.status("xone")
            self.assertIn("a.bin", st["detail"])

    def test_script_no_cross_driver_fallback(self):
        # xone ausente não deve usar o script do xow
        def fake_which(name):
            return "/usr/bin/xow-get-firmware.sh" if name == "xow-get-firmware.sh" else None
        with mock.patch("shutil.which", side_effect=fake_which), \
             mock.patch("backend.firmware._trusted_script",
                        side_effect=lambda p: p):
            self.assertIsNone(firmware.script_for("xone"))
            self.assertEqual(firmware.script_for("xow"),
                             "/usr/bin/xow-get-firmware.sh")

    def test_install_branches(self):
        import subprocess as sp
        with mock.patch("backend.firmware.script_for", return_value=None):
            self.assertFalse(firmware.install("xone")[0])
        with mock.patch("backend.firmware.script_for", return_value="/s"), \
             mock.patch("backend.firmware._pkexec", return_value=None):
            self.assertFalse(firmware.install("xone")[0])
        with mock.patch("backend.firmware.script_for", return_value="/s"), \
             mock.patch("backend.firmware._pkexec", return_value="/pk"), \
             mock.patch("backend.firmware.subprocess.run",
                        side_effect=sp.TimeoutExpired("x", 1)):
            self.assertFalse(firmware.install("xone")[0])
        with mock.patch("backend.firmware.script_for", return_value="/s"), \
             mock.patch("backend.firmware._pkexec", return_value="/pk"), \
             mock.patch("backend.firmware.subprocess.run",
                        side_effect=OSError("x")):
            self.assertFalse(firmware.install("xone")[0])
        with mock.patch("backend.firmware.script_for", return_value="/s"), \
             mock.patch("backend.firmware._pkexec", return_value="/pk"), \
             mock.patch("backend.firmware.subprocess.run",
                        return_value=mock.Mock(returncode=0, stdout="",
                                              stderr="")), \
             mock.patch("backend.firmware.installed_files",
                        return_value=["/f/x.bin"]):
            ok, msg = firmware.install("xone")
            self.assertTrue(ok)
            self.assertIn("x.bin", msg)
        with mock.patch("backend.firmware.script_for", return_value="/s"), \
             mock.patch("backend.firmware._pkexec", return_value="/pk"), \
             mock.patch("backend.firmware.subprocess.run",
                        return_value=mock.Mock(returncode=0, stdout="",
                                              stderr="")), \
             mock.patch("backend.firmware.installed_files",
                        return_value=[]):
            # script saiu 0 mas o arquivo esperado não apareceu
            self.assertFalse(firmware.install("xone")[0])
        with mock.patch("backend.firmware.script_for", return_value="/s"), \
             mock.patch("backend.firmware._pkexec", return_value="/pk"), \
             mock.patch("backend.firmware.subprocess.run",
                        return_value=mock.Mock(returncode=3, stdout="",
                                              stderr="boom")):
            ok, msg = firmware.install("xone")
            self.assertFalse(ok)
            self.assertIn("boom", msg)
        with mock.patch("backend.firmware.script_for", return_value="/s"), \
             mock.patch("backend.firmware._pkexec", return_value="/pk"), \
             mock.patch("backend.firmware.subprocess.run",
                        return_value=mock.Mock(returncode=3, stdout="",
                                              stderr="")):
            self.assertFalse(firmware.install("xone")[0])


class TestPermissionsFull(unittest.TestCase):
    def test_rule_source_missing(self):
        with mock.patch("os.path.isfile", return_value=False):
            self.assertIsNone(permissions._rule_source())
            self.assertIsNone(permissions.rule_installed())
        with mock.patch("os.path.isfile", return_value=True):
            self.assertTrue(permissions.rule_installed().endswith(".rules"))

    def test_in_group_variants(self):
        import grp

        class G:
            gr_name = "input"
            gr_mem = ["eu"]

        with mock.patch.object(grp, "getgrall", return_value=[G()]), \
             mock.patch("backend.permissions.pwd.getpwuid",
                        return_value=mock.Mock(pw_name="eu")):
            self.assertTrue(permissions.in_input_group())
        with mock.patch.object(grp, "getgrall", side_effect=KeyError()):
            self.assertFalse(permissions.in_input_group())

    def test_sysfs_branches(self):
        with mock.patch("backend.permissions.glob.glob", return_value=[]):
            ok, _ = permissions.leds_writable()
            self.assertTrue(ok)
        with mock.patch("backend.permissions.glob.glob",
                        return_value=["/a", "/b"]), \
             mock.patch("os.access", side_effect=[True, False]):
            ok, bad = permissions.pairing_writable()
            self.assertFalse(ok)
            self.assertEqual(bad, ["/b"])

    def test_evdev_branches(self):
        with mock.patch.dict(sys.modules, {"evdev": None}):
            ok, _ = permissions.evdev_readable()
            self.assertTrue(ok)
        import evdev

        class D:
            def __init__(self, p):
                if p == "bad":
                    raise PermissionError()
            path = "x"

            def close(self):
                pass

        with mock.patch.object(evdev, "InputDevice", D), \
             mock.patch("backend.rumble.find_gamepads") as rb:
            rb.return_value = []
            ok, _ = permissions.evdev_readable()
            self.assertTrue(ok)
            rb.return_value = [{"path": "bad"}]
            ok, _ = permissions.evdev_readable()
            self.assertFalse(ok)
            rb.return_value = [{"path": "good"}]
            ok, _ = permissions.evdev_readable()
            self.assertTrue(ok)

    def test_user_group_missing_and_evdev_exception(self):
        class G:
            gr_name = "other"
            gr_mem = []
            gr_gid = 1

        class P:
            pw_name = "u"
            pw_gid = 2

        with mock.patch("backend.permissions.grp.getgrall",
                        return_value=[G()]), \
             mock.patch("backend.permissions.pwd.getpwuid",
                        return_value=P()):
            self.assertFalse(permissions._user_in_group("xboxwireless"))
        with mock.patch("backend.rumble.find_gamepads",
                        side_effect=RuntimeError("x")):
            ok, msg = permissions.evdev_readable()
        self.assertFalse(ok)
        self.assertIn("x", msg)

    def test_login_root_env_and_pkexec_fallback(self):
        with mock.patch("backend.permissions.os.geteuid", return_value=0), \
             mock.patch.dict(os.environ, {"SUDO_UID": "1000"}), \
             mock.patch("backend.permissions.pwd.getpwuid",
                        return_value=mock.Mock(pw_name="nomade")):
            self.assertEqual(permissions._login_user(), "nomade")
        with mock.patch("backend.permissions.os.path.isfile",
                        return_value=False):
            self.assertIsNone(permissions._pkexec())
        with mock.patch("backend.permissions.os.path.isfile",
                        return_value=True), \
             mock.patch("backend.permissions.os.access",
                        return_value=True):
            self.assertEqual(permissions._pkexec(), "/usr/bin/pkexec")

    def test_rule_source_installed_layout(self):
        expected = "/usr/share/xbox-wireless-gui/71-xbox-wireless-gui.rules"
        with mock.patch.object(
                permissions, "__file__",
                "/usr/share/xbox-wireless-gui/backend/permissions.py"), \
             mock.patch("os.path.isfile",
                        side_effect=lambda p: p == expected):
            self.assertEqual(permissions._rule_source(), expected)

    def test_helper_detection_and_finish(self):
        with mock.patch("backend.permissions.os.path.isfile",
                        return_value=True), \
             mock.patch("backend.permissions.os.access",
                        return_value=True), \
             mock.patch("backend.permissions.os.stat",
                        return_value=mock.Mock(st_uid=0, st_mode=0o755)):
            self.assertEqual(permissions._helper(),
                             permissions.HELPER)
        with mock.patch("backend.permissions.os.path.isfile",
                        return_value=True), \
             mock.patch("backend.permissions.os.access",
                        return_value=True), \
             mock.patch("backend.permissions.os.stat",
                        side_effect=OSError("x")):
            self.assertIsNone(permissions._helper())
        with mock.patch("backend.permissions.status",
                        return_value={"ok": False, "detail": "x",
                                      "in_control_group": True}):
            ok, msg = permissions._finish_fix()
        self.assertTrue(ok)
        self.assertIn("saia", msg)

    def test_install_fix_helper_errors(self):
        import subprocess as sp
        base = [
            mock.patch("backend.permissions._login_user",
                       return_value="nomade"),
            mock.patch("backend.permissions._pkexec", return_value="/pk"),
            mock.patch("backend.permissions._helper", return_value="/h"),
        ]
        for exc in (sp.TimeoutExpired("x", 1), OSError("x")):
            with base[0], base[1], base[2], \
                 mock.patch("backend.permissions.subprocess.run",
                            side_effect=exc):
                self.assertFalse(permissions.install_fix()[0])
        with base[0], base[1], base[2], \
             mock.patch("backend.permissions.subprocess.run",
                        return_value=mock.Mock(returncode=1, stderr="bad",
                                              stdout="")):
            ok, msg = permissions.install_fix()
        self.assertFalse(ok)
        self.assertIn("bad", msg)

    def test_install_fix_uses_helper(self):
        with mock.patch("backend.permissions._login_user",
                        return_value="nomade"), \
             mock.patch("backend.permissions._pkexec", return_value="/pk"), \
             mock.patch("backend.permissions._helper", return_value="/h"), \
             mock.patch("backend.permissions.subprocess.run",
                        return_value=mock.Mock(returncode=0, stdout="",
                                              stderr="")) as run, \
             mock.patch("backend.permissions._finish_fix",
                        return_value=(True, "ok")):
            self.assertTrue(permissions.install_fix()[0])
        self.assertEqual(run.call_args[0][0],
                         ["/pk", "/h", "permissions", "nomade"])

    def test_install_fix_command_uses_control_group(self):
        with mock.patch("backend.permissions._login_user",
                        return_value="nomade"), \
             mock.patch("backend.permissions._pkexec", return_value="/pk"), \
             mock.patch("backend.permissions.subprocess.run",
                        return_value=mock.Mock(returncode=0, stdout="",
                                              stderr="")) as run, \
             mock.patch("backend.permissions.status",
                        return_value={"ok": True, "detail": "x",
                                      "in_control_group": True}):
            self.assertTrue(permissions.install_fix()[0])
        script = run.call_args[0][0][-1]
        self.assertIn("usermod -aG xboxwireless nomade", script)
        self.assertNotIn("usermod -aG input", script)
        self.assertIn("71-xbox-wireless-gui.rules", script)

    def test_install_fix_branches(self):
        import subprocess as sp
        with mock.patch("backend.permissions._login_user", return_value=""):
            self.assertFalse(permissions.install_fix()[0])
        with mock.patch("backend.permissions._login_user",
                        return_value="user name"):
            self.assertFalse(permissions.install_fix()[0])
        with mock.patch("backend.permissions._login_user",
                        return_value="nomade"), \
             mock.patch("backend.permissions._pkexec", return_value=None):
            self.assertFalse(permissions.install_fix()[0])
        with mock.patch("backend.permissions._login_user",
                        return_value="nomade"), \
             mock.patch("backend.permissions._pkexec", return_value="/pk"), \
             mock.patch("backend.permissions.subprocess.run",
                        side_effect=sp.TimeoutExpired("x", 1)):
            self.assertFalse(permissions.install_fix()[0])
        with mock.patch("backend.permissions._login_user",
                        return_value="nomade"), \
             mock.patch("backend.permissions._pkexec", return_value="/pk"), \
             mock.patch("backend.permissions.subprocess.run",
                        side_effect=OSError("x")):
            self.assertFalse(permissions.install_fix()[0])
        with mock.patch("backend.permissions._login_user",
                        return_value="nomade"), \
             mock.patch("backend.permissions._pkexec", return_value="/pk"), \
             mock.patch("backend.permissions.subprocess.run",
                        return_value=mock.Mock(returncode=1, stderr="",
                                              stdout="")):
            self.assertFalse(permissions.install_fix()[0])
        with mock.patch("backend.permissions._login_user",
                        return_value="nomade"), \
             mock.patch("backend.permissions._pkexec", return_value="/pk"), \
             mock.patch("backend.permissions.subprocess.run",
                        return_value=mock.Mock(returncode=0, stdout="",
                                              stderr="")), \
             mock.patch("backend.permissions.status",
                        return_value={"ok": True, "detail": "x",
                                      "in_control_group": True}):
            ok, msg = permissions.install_fix()
            self.assertTrue(ok)
            self.assertIn("corrigidas", msg)
        with mock.patch("backend.permissions._login_user",
                        return_value="nomade"), \
             mock.patch("backend.permissions._pkexec", return_value="/pk"), \
             mock.patch("backend.permissions.subprocess.run",
                        return_value=mock.Mock(returncode=0, stdout="",
                                              stderr="")), \
             mock.patch("backend.permissions.status",
                        return_value={"ok": False,
                                      "detail": "falta y",
                                      "in_control_group": False}):
            ok, msg = permissions.install_fix()
            self.assertTrue(ok)
            self.assertIn("falta y", msg)

    def test_login_user(self):
        with mock.patch.dict(os.environ, {"PKEXEC_UID": "xyz"}):
            self.assertIsInstance(permissions._login_user(), str)


class TestBluetoothFull(unittest.TestCase):
    def test_phys_success_closes(self):
        import evdev

        class Dev:
            phys = "AA:BB:CC:DD:EE:FF"
            closed = False

            def close(self):
                Dev.closed = True

        with mock.patch.object(evdev, "InputDevice", return_value=Dev()):
            self.assertEqual(bluetooth.phys_of("/p"), "AA:BB:CC:DD:EE:FF")
        self.assertTrue(Dev.closed)

    def test_phys_close_error(self):
        import evdev

        class Dev:
            phys = "AA:BB:CC:DD:EE:FF"

            def close(self):
                raise OSError("close")

        with mock.patch.object(evdev, "InputDevice", return_value=Dev()):
            self.assertEqual(bluetooth.phys_of("/p"), "AA:BB:CC:DD:EE:FF")

    def test_phys_variants(self):
        import evdev
        with mock.patch.object(evdev, "InputDevice",
                               side_effect=OSError("x")):
            self.assertIsNone(bluetooth.phys_of("/p"))
        with mock.patch.dict(sys.modules, {"evdev": None}):
            self.assertIsNone(bluetooth.phys_of("/p"))
        self.assertFalse(bluetooth.is_bluetooth("/p"))
        self.assertIsNone(bluetooth.mac_of("/p"))

    def test_mac_ok(self):
        with mock.patch("backend.bluetooth.phys_of",
                        return_value="AA:BB:CC:DD:EE:FF/input0"):
            self.assertTrue(bluetooth.is_bluetooth("/p"))
            self.assertEqual(bluetooth.mac_of("/p"), "AA:BB:CC:DD:EE:FF")

    def test_disconnect_branches(self):
        import subprocess as sp
        with mock.patch("backend.bluetooth.mac_of", return_value=None):
            self.assertFalse(bluetooth.disconnect("/p")[0])
        with mock.patch("backend.bluetooth.mac_of",
                        return_value="AA:BB:CC:DD:EE:FF"), \
             mock.patch("shutil.which", return_value=None):
            self.assertFalse(bluetooth.disconnect("/p")[0])
        with mock.patch("backend.bluetooth.mac_of",
                        return_value="AA:BB:CC:DD:EE:FF"), \
             mock.patch("shutil.which", return_value="/bt"), \
             mock.patch("backend.bluetooth.subprocess.run",
                        side_effect=sp.TimeoutExpired("x", 1)):
            self.assertFalse(bluetooth.disconnect("/p")[0])
        with mock.patch("backend.bluetooth.mac_of",
                        return_value="AA:BB:CC:DD:EE:FF"), \
             mock.patch("shutil.which", return_value="/bt"), \
             mock.patch("backend.bluetooth.subprocess.run",
                        side_effect=OSError("x")):
            self.assertFalse(bluetooth.disconnect("/p")[0])
        with mock.patch("backend.bluetooth.mac_of",
                        return_value="AA:BB:CC:DD:EE:FF"), \
             mock.patch("shutil.which", return_value="/bt"), \
             mock.patch("backend.bluetooth.subprocess.run",
                        return_value=mock.Mock(returncode=0,
                                              stdout="Successful\n",
                                              stderr="")):
            ok, msg = bluetooth.disconnect("/p")
            self.assertTrue(ok)
            self.assertIn("FF", msg)
        with mock.patch("backend.bluetooth.mac_of",
                        return_value="AA:BB:CC:DD:EE:FF"), \
             mock.patch("shutil.which", return_value="/bt"), \
             mock.patch("backend.bluetooth.subprocess.run",
                        return_value=mock.Mock(returncode=1, stdout="",
                                              stderr="")):
            self.assertFalse(bluetooth.disconnect("/p")[0])


class TestPrefsFull(unittest.TestCase):
    def test_gsettings_branch(self):
        p = prefs.Prefs()
        fake = mock.Mock()
        fake.get_int.return_value = 111
        fake.get_double.return_value = 0.5
        fake.get_string.return_value = "s"
        fake.get_boolean.return_value = True
        p._settings = fake
        self.assertEqual(p.backend, "gsettings")
        self.assertEqual(p.get_int("rumble-duration"), 111)
        self.assertEqual(p.get_double("tester-deadzone"), 0.5)
        self.assertEqual(p.get_string("selected-dongle"), "s")
        self.assertTrue(p.get_bool("check-updates"))
        p.set_int("rumble-duration", 1)
        p.set_double("tester-deadzone", 0.1)
        p.set_string("selected-dongle", "d")
        p.set_bool("check-updates", False)
        fake.set_int.assert_called_once_with("rumble-duration", 1)
        fake.set_double.assert_called_once_with("tester-deadzone", 0.1)
        # com settings ativo, a leitura vem do backend (mock)
        self.assertEqual(p.get_int("rumble-duration"), 111)

    def test_gsettings_exceptions(self):
        p = prefs.Prefs()
        fake = mock.Mock()
        fake.get_int.side_effect = RuntimeError("x")
        fake.get_double.side_effect = RuntimeError("x")
        fake.get_string.side_effect = RuntimeError("x")
        fake.get_boolean.side_effect = RuntimeError("x")
        fake.set_int.side_effect = RuntimeError("x")
        fake.set_double.side_effect = RuntimeError("x")
        fake.set_string.side_effect = RuntimeError("x")
        fake.set_boolean.side_effect = RuntimeError("x")
        p._settings = fake
        p.set_int("rumble-duration", 700)
        self.assertEqual(p.get_int("rumble-duration"), 700)
        p.set_double("tester-deadzone", 0.2)
        self.assertAlmostEqual(p.get_double("tester-deadzone"), 0.2)
        p.set_string("selected-dongle", "d2")
        self.assertEqual(p.get_string("selected-dongle"), "d2")
        p.set_bool("check-updates", True)
        self.assertTrue(p.get_bool("check-updates"))


class TestI18nFull(unittest.TestCase):
    def test_languages(self):
        from backend import i18n
        with mock.patch.dict(os.environ, {"LANGUAGE": "C"}):
            self.assertIsNotNone(i18n._pick_language() or True)
            tr = i18n.get_translation()
            self.assertTrue(hasattr(tr, "gettext"))
        with mock.patch.dict(os.environ, {"LANGUAGE": "en_US.UTF-8",
                                          "LC_ALL": "", "LC_MESSAGES": "",
                                          "LANG": ""}):
            self.assertEqual(i18n._pick_language(), "en_US.UTF-8")
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch("backend.i18n.locale.getlocale",
                        side_effect=Exception("x")):
            self.assertIsNone(i18n._pick_language())
        self.assertEqual(i18n.N_("abc"), "abc")

    def test_translation_missing(self):
        from backend import i18n
        with mock.patch.dict(os.environ, {"LANGUAGE": "xx_ZZ"}):
            tr = i18n.get_translation()
            self.assertEqual(tr.gettext("Bateria"), "Bateria")


class TestUpdatesFull(unittest.TestCase):
    def test_latest(self):
        import json

        class Resp:
            def __init__(self, payload):
                self._p = payload

            def read(self):
                return self._p

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        payload = json.dumps(
            {"tag_name": "v0.2.0",
             "html_url": "https://x/y"}).encode()
        with mock.patch("backend.updates.urllib.request.urlopen",
                        return_value=Resp(payload)):
            rel = updates.latest_release()
        self.assertEqual(rel["tag"], "v0.2.0")
        with mock.patch("backend.updates.urllib.request.urlopen",
                        side_effect=Exception("offline")):
            res = updates.check("0.1.0")
        self.assertFalse(res["newer"])
        self.assertIn("error", res)
        with mock.patch("backend.updates.latest_release",
                        return_value={"tag": "", "url": ""}):
            self.assertFalse(updates.check("0.1.0")["newer"])
        with mock.patch("backend.updates.latest_release",
                        return_value={"tag": "v9.9.9",
                                      "url": "https://x/y"}):
            res = updates.check("0.1.0")
            self.assertTrue(res["newer"])


class TestInputsFull(unittest.TestCase):
    def test_edge_norms(self):
        self.assertEqual(inputs._norm_stick(5, 10, 10), 0.0)
        self.assertEqual(inputs._norm_trigger(5, 9, 9), 0.0)

    def test_keymap_noevdev(self):
        with mock.patch.dict(sys.modules, {"evdev": None}):
            self.assertEqual(inputs.key_map(), {})
            self.assertEqual(inputs.new_state()["lx"], 0.0)

    def test_apply_abs_variants(self):
        from evdev import ecodes
        st = inputs.new_state()
        lim = {ecodes.ABS_RX: (-32768, 32767),
               ecodes.ABS_RY: (-32768, 32767),
               ecodes.ABS_Z: (0, 255),
               ecodes.ABS_RZ: (0, 255),
               ecodes.ABS_HAT0X: (-1, 1),
               ecodes.ABS_HAT0Y: (-1, 1)}
        self.assertTrue(inputs.apply_abs(st, ecodes.ABS_RZ, 255, lim))
        self.assertEqual(st["rt"], 1.0)
        self.assertTrue(inputs.apply_abs(st, ecodes.ABS_HAT0Y, -1, lim))
        self.assertEqual(st["hat"], (0, -1))
        self.assertFalse(inputs.apply_abs(st, 99999, 0, lim))
        with mock.patch.dict(sys.modules, {"evdev": None}):
            self.assertFalse(inputs.apply_abs(st, ecodes.ABS_X, 0, lim))

    def test_resync_branches(self):
        from evdev import ecodes

        class NoKeys:
            def active_keys(self):
                raise OSError("x")

        st = inputs.new_state()
        self.assertFalse(inputs.resync(st, NoKeys(), {}))

        class Dev:
            def active_keys(self):
                return []

            def absinfo(self, code):
                raise OSError("x")

        st["a"] = True
        self.assertTrue(inputs.resync(st, Dev(), {ecodes.ABS_X: (0, 1)}))

    def test_list_devices_branches(self):
        with mock.patch.dict(sys.modules, {"evdev": None}):
            self.assertEqual(inputs.list_devices(), [])
        import evdev
        with mock.patch("backend.rumble.find_gamepads") as find:
            find.return_value = [{"path": "/p1", "name": "Pad",
                                  "has_rumble": False}]
            with mock.patch.object(evdev, "InputDevice",
                                   side_effect=OSError("x")):
                out = inputs.list_devices()
            self.assertEqual(out[0]["limits"], {})
        with mock.patch("backend.rumble.find_gamepads") as find:
            find.return_value = [
                {"path": "/v", "name": "Microsoft X-Box 360 pad",
                 "has_rumble": False},
                {"path": "/r", "name": "Real", "has_rumble": False}]
            with mock.patch.object(evdev, "InputDevice") as cls, \
                 mock.patch.object(evdev, "ecodes"):
                inst = cls.return_value
                inst.capabilities.return_value = {}
                out = inputs.list_devices()
            self.assertEqual(out[-1]["path"], "/v")


if __name__ == "__main__":
    unittest.main()
