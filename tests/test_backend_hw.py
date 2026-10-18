"""Cobertura backend (mocks, sem hardware): battery/detector/xone/xow/rumble."""
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backend import battery, detector, rumble, xone, xow


def make_upower(devices, fail_client=False, fail_level=False):
    """Monta gi/gi.repository/UPowerGlib falsos em sys.modules."""
    mod_gi = types.ModuleType("gi")
    mod_gi.require_version = mock.Mock()
    mod_repo = types.ModuleType("gi.repository")
    mod_up = types.ModuleType("UPowerGlib")

    class FakeProps:
        def __init__(self, d):
            self.__dict__.update(d)

    class FakeDev:
        def __init__(self, d):
            self.props = FakeProps(d["props"])
            self._path = d["path"]

        def get_object_path(self):
            return self._path

    class FakeClient:
        @staticmethod
        def new():
            if fail_client:
                raise RuntimeError("sem upower")
            return FakeClient()

        def get_devices(self):
            return [FakeDev(d) for d in devices]

    class FakeDevice:
        kind_to_string = staticmethod(lambda k: {1: "gaming-input"}.get(k, "other"))
        state_to_string = staticmethod(
            lambda s: {1: "charging", 2: "discharging", 3: "fully-charged"}.get(s, "?"))
        level_to_string = staticmethod(
            lambda lv: (_ for _ in ()).throw(RuntimeError("x")) if fail_level else "high")

    mod_up.Client = FakeClient
    mod_up.Device = FakeDevice
    mod_repo.UPowerGlib = mod_up
    return {"gi": mod_gi, "gi.repository": mod_repo}


GAMEPAD = {"path": "/org/fake/battery_gip0",
           "props": {"model": "Xbox Controller", "vendor": "Microsoft",
                     "native_path": "gip0.0", "kind": 1, "percentage": 70.0,
                     "state": 2, "battery_level": 5, "serial": "ABC",
                     "time_to_empty": 0, "time_to_full": 0}}


class TestBatteryFull(unittest.TestCase):
    def test_list_gamepad(self):
        with mock.patch.dict(sys.modules, make_upower([GAMEPAD])):
            out = battery.list_batteries()
        self.assertEqual(len(out), 1)
        b = out[0]
        self.assertEqual(b["device"], "Microsoft Xbox Controller")
        self.assertEqual(b["percentage"], 70)
        self.assertEqual(b["native_path"], "gip0.0")

    def test_skips_display_and_nongamepad(self):
        disp = {"path": "/org/fake/DisplayDevice",
                "props": dict(GAMEPAD["props"], model="Display", native_path="")}
        mouse = {"path": "/org/fake/mouse",
                 "props": dict(GAMEPAD["props"], model="Mouse", vendor="Logi",
                               native_path="usb0", kind=99)}
        with mock.patch.dict(sys.modules, make_upower([disp, mouse])):
            self.assertEqual(battery.list_batteries(), [])

    def test_client_fail(self):
        with mock.patch.dict(sys.modules, make_upower([], fail_client=True)):
            out = battery.list_batteries()
        self.assertEqual(out[0]["percentage"], -1)

    def test_level_fail(self):
        # level_to_string quebrou -> level cai para str(battery_level)
        with mock.patch.dict(sys.modules, make_upower([GAMEPAD], fail_level=True)):
            out = battery.list_batteries()
        self.assertEqual(out[0]["level"], "5")
        self.assertEqual(out[0]["level_en"], "5")

    def test_kind_state_importerror(self):
        with mock.patch.dict(sys.modules, {"gi": None, "gi.repository": None,
                                           "UPowerGlib": None}):
            self.assertEqual(battery._kind_str(3), "3")
            self.assertEqual(battery._state_str(4), "4")

    def test_levels_icons_edges(self):
        self.assertEqual(battery._level_pt("???"), "???")
        self.assertEqual(battery.icon_for(5, "discharging", "critical"),
                         "battery-empty-symbolic")
        self.assertEqual(battery.icon_for(-1, "unknown", "critical"),
                         "battery-caution-symbolic")
        self.assertEqual(battery.icon_for(-1, "unknown", "???"),
                         "battery-missing-symbolic")


class TestDetectorFull(unittest.TestCase):
    def test_no_dongle(self):
        with mock.patch("backend.detector.glob.glob", return_value=[]):
            self.assertIsNone(detector.detect_xone_dongle())

    def test_pairing_file_none(self):
        with mock.patch("backend.detector.glob.glob", return_value=[]):
            self.assertIsNone(detector.xone_pairing_file())
            self.assertIsNone(detector.xone_pairing_file("/x"))

    def test_pairing_file_explicit(self):
        with mock.patch("backend.detector.glob.glob",
                        return_value=["/sys/d/pairing"]):
            self.assertEqual(detector.xone_pairing_file("/sys/d"),
                             "/sys/d/pairing")

    def test_pairing_file_glob(self):
        with mock.patch("backend.detector.glob.glob",
                        return_value=["/sys/a/pairing"]):
            self.assertEqual(detector.xone_pairing_file(), "/sys/a/pairing")

    def test_xow_variants(self):
        import subprocess as sp
        with mock.patch("shutil.which", return_value=None), \
             mock.patch("backend.detector.subprocess.run",
                        return_value=mock.Mock(stdout="active\n")):
            self.assertTrue(detector.detect_xow())
        with mock.patch("shutil.which", return_value=None), \
             mock.patch("backend.detector.subprocess.run",
                        return_value=mock.Mock(stdout="inactive\n")):
            self.assertFalse(detector.detect_xow())
        with mock.patch("shutil.which", return_value=None), \
             mock.patch("backend.detector.subprocess.run",
                        side_effect=sp.TimeoutExpired("x", 1)):
            self.assertFalse(detector.detect_xow())

    def test_detect_branches(self):
        with mock.patch("backend.detector.detect_xone_dongle",
                        return_value="/sys/dongle"), \
             mock.patch("backend.detector.xone_pairing_file",
                        return_value="/sys/dongle/pairing"), \
             mock.patch("backend.detector.glob.glob",
                        return_value=["/sys/dongle"]):
            info = detector.detect()
            self.assertEqual(info.name, "xone")
            self.assertEqual(info.dongles, ["/sys/dongle"])
        with mock.patch("backend.detector.detect_xone_dongle",
                        return_value=None), \
             mock.patch("backend.detector.detect_xow", return_value=True):
            self.assertEqual(detector.detect().name, "xow")
        with mock.patch("backend.detector.detect_xone_dongle",
                        return_value=None), \
             mock.patch("backend.detector.detect_xow", return_value=False):
            self.assertEqual(detector.detect().name, "nenhum")


class TestXoneFull(unittest.TestCase):
    def test_dongles(self):
        with mock.patch("backend.xone.glob.glob",
                        return_value=["/a", "/b"]):
            self.assertEqual(xone.list_dongles(), ["/a", "/b"])

    def test_pairing_file_dongle(self):
        self.assertIsNone(xone.get_pairing_file("/etc/passwd"))
        self.assertIsNone(xone.get_pairing_file("/sys/bus/usb/drivers/xone-dongle/../x"))
        with mock.patch("os.path.isfile", return_value=True):
            self.assertTrue(xone.get_pairing_file(
                "/sys/bus/usb/drivers/xone-dongle/1-1:1.0").endswith("pairing"))
        with mock.patch("os.path.isfile", return_value=False):
            self.assertIsNone(xone.get_pairing_file(
                "/sys/bus/usb/drivers/xone-dongle/1-1:1.0"))

    def test_get_pairing_oserror(self):
        with mock.patch("backend.xone.get_pairing_file",
                        return_value="/pf"), \
             mock.patch("builtins.open", side_effect=OSError("x")):
            self.assertIsNone(xone.get_pairing())
        m = mock.mock_open(read_data="1\n")
        with mock.patch("backend.xone.get_pairing_file",
                        return_value="/pf"), \
             mock.patch("builtins.open", m):
            self.assertTrue(xone.get_pairing())

    def test_set_pairing_direct(self):
        m = mock.mock_open()
        with mock.patch("backend.xone.get_pairing_file",
                        return_value="/sys/bus/usb/drivers/xone-dongle/d/pairing"), \
             mock.patch("builtins.open", m):
            ok, msg = xone.set_pairing(True)
        self.assertTrue(ok)
        self.assertIn("ativado", msg)

    def test_set_pairing_oserror(self):
        with mock.patch("backend.xone.get_pairing_file",
                        return_value="/pf"), \
             mock.patch("builtins.open", side_effect=OSError("disk")):
            ok, _ = xone.set_pairing(True)
        self.assertFalse(ok)

    def test_set_pairing_pkexec(self):
        import subprocess as sp
        with mock.patch("backend.xone.get_pairing_file",
                        return_value="/sys/bus/usb/drivers/xone-dongle/d/pairing"), \
             mock.patch("builtins.open", side_effect=PermissionError()), \
             mock.patch("backend.xone._run_pkexec_shell",
                        return_value=mock.Mock(returncode=0)):
            self.assertTrue(xone.set_pairing(False)[0])
        with mock.patch("backend.xone.get_pairing_file",
                        return_value="/sys/bus/usb/drivers/xone-dongle/d/pairing"), \
             mock.patch("builtins.open", side_effect=PermissionError()), \
             mock.patch("backend.xone._run_pkexec_shell",
                        return_value=mock.Mock(returncode=1, stderr="no",
                                              stdout="")):
            self.assertFalse(xone.set_pairing(True)[0])
        with mock.patch("backend.xone.get_pairing_file",
                        return_value="/sys/bus/usb/drivers/xone-dongle/d/pairing"), \
             mock.patch("builtins.open", side_effect=PermissionError()), \
             mock.patch("backend.xone._run_pkexec_shell",
                        side_effect=sp.TimeoutExpired("x", 1)):
            self.assertFalse(xone.set_pairing(True)[0])
        with mock.patch("backend.xone.get_pairing_file",
                        return_value="/sys/bus/usb/drivers/xone-dongle/d/pairing"), \
             mock.patch("builtins.open", side_effect=PermissionError()), \
             mock.patch("backend.xone._run_pkexec_shell",
                        side_effect=FileNotFoundError()):
            self.assertFalse(xone.set_pairing(True)[0])

    def test_run_pkexec_shell(self):
        import subprocess as sp
        with mock.patch("backend.xone.subprocess.run",
                        return_value=mock.Mock(returncode=0)) as r:
            xone._run_pkexec_shell("echo 1")
            self.assertIn("pkexec", r.call_args[0][0])

    def test_list_controllers(self):
        m = mock.mock_open(read_data="7")
        with mock.patch("backend.xone.glob.glob",
                        return_value=["/sys/class/leds/gip0"]), \
             mock.patch("builtins.open", m):
            out = xone.list_controllers()
        self.assertEqual(out[0]["mode"], "7")
        with mock.patch("backend.xone.glob.glob",
                        return_value=["/sys/class/leds/gip0"]), \
             mock.patch("builtins.open", side_effect=OSError("x")):
            out = xone.list_controllers()
        self.assertEqual(out[0]["mode"], "?")

    def test_set_led_direct_and_pkexec(self):
        m = mock.mock_open(read_data="50")
        with mock.patch("os.path.isdir", return_value=True), \
             mock.patch("builtins.open", m):
            ok, _ = xone.set_led("gip0", "2", "5")
        self.assertTrue(ok)
        m2 = mock.mock_open(read_data="50")
        m2.side_effect = [mock.mock_open(read_data="50").return_value,
                          PermissionError(), PermissionError()]
        with mock.patch("os.path.isdir", return_value=True), \
             mock.patch("builtins.open", m2), \
             mock.patch("backend.xone._run_pkexec_shell",
                        return_value=mock.Mock(returncode=1, stderr="e",
                                              stdout="")):
            ok, _ = xone.set_led("gip0", "2", "5")
        self.assertFalse(ok)

    def test_set_led_oserror_and_exception(self):
        m = mock.mock_open(read_data="50")
        m.side_effect = [mock.mock_open(read_data="50").return_value,
                         OSError("disk")]
        with mock.patch("os.path.isdir", return_value=True), \
             mock.patch("builtins.open", m):
            ok, _ = xone.set_led("gip0", "2", "5")
        self.assertFalse(ok)
        with mock.patch("os.path.isdir", return_value=True), \
             mock.patch("builtins.open",
                        side_effect=[mock.mock_open(read_data="50").return_value,
                                    PermissionError(), PermissionError()]), \
             mock.patch("backend.xone._run_pkexec_shell",
                        side_effect=RuntimeError("boom")):
            ok, _ = xone.set_led("gip0", "2", "5")
        self.assertFalse(ok)

    def test_set_led_max_unreadable(self):
        with mock.patch("os.path.isdir", return_value=True), \
             mock.patch("builtins.open", side_effect=OSError("x")):
            ok, _ = xone.set_led("gip0", "2", "300")
        self.assertFalse(ok)
        m = mock.mock_open()
        with mock.patch("os.path.isdir", return_value=True), \
             mock.patch("builtins.open",
                        side_effect=[OSError("x"), m.return_value,
                                    m.return_value]):
            # max ilegível -> faixa 0-255; valor 5 passa na direta
            ok, _ = xone.set_led("gip0", "1", "5")
        self.assertTrue(ok)


class TestXowFull(unittest.TestCase):
    def test_all(self):
        import subprocess as sp
        with mock.patch("shutil.which", return_value="/usr/bin/xow"):
            self.assertTrue(xow.available())
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(xow.available())
        with mock.patch("backend.xow.subprocess.run",
                        return_value=mock.Mock(stdout="active\n")):
            self.assertTrue(xow.service_active())
        with mock.patch("backend.xow.subprocess.run",
                        side_effect=OSError("x")):
            self.assertFalse(xow.service_active())
        with mock.patch("backend.xow.subprocess.run",
                        return_value=mock.Mock(returncode=0)):
            self.assertTrue(xow.set_pairing()[0])
        with mock.patch("backend.xow.subprocess.run",
                        side_effect=sp.TimeoutExpired("x", 1)):
            self.assertFalse(xow.set_pairing()[0])
        self.assertIn("xow", xow.firmware_hint())


class FakeInputDevice:
    def __init__(self, path, name="Microsoft Xbox Controller",
                 caps=None, fail=None):
        if fail:
            raise fail
        self.path = path
        self.name = name
        self._caps = caps if caps is not None else {0x15: []}

    def capabilities(self, absinfo=False):
        return self._caps

    def close(self):
        pass


class TestRumbleFull(unittest.TestCase):
    def test_find_gamepads(self):
        import evdev
        devs = {"p1": FakeInputDevice("p1"),
                "p2": FakeInputDevice("p2", name="Keyboard",
                                       caps={0x01: []}),
                "p3": FakeInputDevice("p3", name="Microsoft X-Box 360 pad 0")}
        with mock.patch.object(evdev, "list_devices",
                               return_value=list(devs)), \
             mock.patch.object(evdev, "InputDevice",
                               side_effect=lambda p: devs[p]):
            out = rumble.find_gamepads()
        names = [d["name"] for d in out]
        self.assertIn("Microsoft Xbox Controller", names)
        self.assertNotIn("Keyboard", names)
        # virtual 360 por último
        self.assertTrue(names[-1].startswith("Microsoft X-Box"))

    def test_find_oserror(self):
        import evdev
        with mock.patch.object(evdev, "list_devices",
                               return_value=["p9"]), \
             mock.patch.object(evdev, "InputDevice",
                               side_effect=OSError("x")):
            self.assertEqual(rumble.find_gamepads(), [])

    def test_find_importerror(self):
        with mock.patch.dict(sys.modules, {"evdev": None}):
            self.assertEqual(rumble.find_gamepads(), [])

    def test_rumble_success(self):
        import evdev

        class FakeFF:
            class Rumble:
                def __init__(self, **kw):
                    pass

            class Effect:
                def __init__(self, *a):
                    pass

            class Trigger:
                def __init__(self, *a):
                    pass

            class Replay:
                def __init__(self, *a):
                    pass

            class EffectType:
                def __init__(self, **kw):
                    pass

        class Dev(FakeInputDevice):
            def upload_effect(self, e):
                return 1

            def write(self, *a):
                pass

            def erase_effect(self, i):
                pass

        with mock.patch.object(evdev, "InputDevice",
                               return_value=Dev("p")), \
             mock.patch.object(evdev, "ff", FakeFF), \
             mock.patch("time.sleep"):
            ok, _ = rumble.rumble("p", duration_ms=100)
        self.assertTrue(ok)

    def test_rumble_errors(self):
        import evdev
        with mock.patch.object(evdev, "InputDevice",
                               side_effect=PermissionError()):
            ok, _ = rumble.rumble("p")
        self.assertFalse(ok)
        with mock.patch.object(evdev, "InputDevice",
                               side_effect=RuntimeError("x")):
            ok, _ = rumble.rumble("p")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
