"""Testes dos módulos novos: áudio, Bluetooth, perfis, diagnóstico, poweroff."""
import os
import sys
import tempfile
import unittest
from unittest import mock

from tests import _env  # noqa: F401

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backend import audio, battery, bluetooth, detector, diagnostics
from backend import inputs, permissions, profiles, rumble, xone, xow


class TestAudio(unittest.TestCase):
    def test_looks_like(self):
        self.assertTrue(audio.looks_like_xbox("Xbox Wireless Headset"))
        self.assertTrue(audio.looks_like_xbox("gip0.0"))
        self.assertFalse(audio.looks_like_xbox("HDA Intel"))

    def test_list_cards(self):
        data = " 0 [HDMI           ]: HDA-Intel - HDA ATI HDMI\n" \
               " 3 [Xbox Controller]: USB-Audio - Xbox Wireless Controller\n"
        with mock.patch("builtins.open", mock.mock_open(read_data=data)):
            cards = audio.list_cards()
        self.assertEqual(cards, [{"id": "3", "short": "Xbox Controller",
                                  "name": "USB-Audio - Xbox Wireless Controller"}])

    def test_list_cards_error(self):
        with mock.patch("builtins.open", side_effect=OSError("x")):
            self.assertEqual(audio.list_cards(), [])

    def test_pactl_list(self):
        with mock.patch("shutil.which", return_value="/usr/bin/pactl"), \
             mock.patch.object(audio, "_run", return_value=(
                 "1\talsa.xbox\tPipeWire\ts16le 2ch 48000Hz\tSUSPENDED\n")):
            out = audio._pactl_list("sinks")
        self.assertEqual(out[0]["name"], "alsa.xbox")

    def test_pactl_list_missing(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual(audio._pactl_list("sinks"), [])

    def test_status(self):
        with mock.patch.object(audio, "_pactl_list", side_effect=[
                [{"id": "1", "name": "alsa.xbox", "driver": "x", "state": ""}],
                [{"id": "2", "name": "alsa.mic", "driver": "x", "state": ""}]]), \
             mock.patch.object(audio, "list_cards", return_value=[{"id": "3"}]), \
             mock.patch("shutil.which", return_value="/p"):
            st = audio.status()
        self.assertTrue(st["available"])
        self.assertEqual(len(st["sinks"]), 1)
        self.assertEqual(st["sources"], [])

    def test_valid_and_set(self):
        self.assertFalse(audio._valid_name(""))
        self.assertFalse(audio._valid_name("a\nb"))
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(audio.set_default("sink", "x")[0])
            self.assertFalse(audio.set_volume("sink", "x", 10)[0])
            self.assertFalse(audio.set_mute("sink", "x", True)[0])
        with mock.patch("shutil.which", return_value="/p"), \
             mock.patch.object(audio, "_run", return_value="Failure: x"):
            self.assertFalse(audio.set_default("sink", "x")[0])
            self.assertFalse(audio.set_volume("sink", "x", 999)[0])
            self.assertFalse(audio.set_mute("sink", "x", True)[0])
        with mock.patch("shutil.which", return_value="/p"), \
             mock.patch.object(audio, "_run", return_value=""):
            self.assertTrue(audio.set_default("sink", "x")[0])
            self.assertTrue(audio.set_volume("sink", "x", 50)[0])
            self.assertTrue(audio.set_mute("source", "x", False)[0])
        self.assertFalse(audio.set_default("bogus", "x")[0])
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(audio.set_default("sink", "x")[0])
        self.assertFalse(audio.set_volume("sink", "x", "zz")[0])
        self.assertFalse(audio.set_mute("bogus", "x", True)[0])

    def test_has_and_card(self):
        with mock.patch.object(audio, "list_cards", return_value=[{"id": "3", "short": "Xbox", "name": "Xbox"}]):
            self.assertTrue(audio.has_xone_audio())
            self.assertEqual(audio.alsa_card_for("Xbox Controller"), "3")
        with mock.patch.object(audio, "list_cards", return_value=[]), \
             mock.patch.object(audio, "status", return_value={"sinks": [], "sources": []}):
            self.assertFalse(audio.has_xone_audio())
            self.assertIsNone(audio.alsa_card_for("nada"))


class TestBluetoothNew(unittest.TestCase):
    def test_bt_mac(self):
        self.assertIsNone(bluetooth._bt("xx"))
        self.assertEqual(bluetooth._bt("aa:bb:cc:dd:ee:ff"),
                         "AA:BB:CC:DD:EE:FF")

    def test_bluetoothctl_paths(self):
        import subprocess
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(bluetooth._bluetoothctl("x")[0])
        with mock.patch("shutil.which", return_value="/b"), \
             mock.patch("backend.bluetooth.subprocess.run",
                        side_effect=subprocess.TimeoutExpired("x", 1)):
            self.assertFalse(bluetooth._bluetoothctl("x")[0])
        with mock.patch("shutil.which", return_value="/b"), \
             mock.patch("backend.bluetooth.subprocess.run", side_effect=OSError("x")):
            self.assertFalse(bluetooth._bluetoothctl("x")[0])
        ok_run = mock.Mock(returncode=0, stdout="Success", stderr="")
        with mock.patch("shutil.which", return_value="/b"), \
             mock.patch("backend.bluetooth.subprocess.run", return_value=ok_run):
            self.assertTrue(bluetooth._bluetoothctl("x")[0])
        bad_run = mock.Mock(returncode=1, stdout="", stderr="erro")
        with mock.patch("shutil.which", return_value="/b"), \
             mock.patch("backend.bluetooth.subprocess.run", return_value=bad_run):
            self.assertFalse(bluetooth._bluetoothctl("x")[0])

    def test_paired_devices(self):
        out = "Device AA:BB:CC:DD:EE:FF Xbox Controller\n"
        with mock.patch("shutil.which", return_value="/b"), \
             mock.patch("backend.bluetooth.subprocess.run",
                        return_value=mock.Mock(stdout=out)):
            devs = bluetooth.paired_devices()
        self.assertEqual(devs[0]["mac"], "AA:BB:CC:DD:EE:FF")
        self.assertTrue(devs[0]["xbox"])
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual(bluetooth.paired_devices(), [])
        with mock.patch("shutil.which", return_value="/b"), \
             mock.patch("backend.bluetooth.subprocess.run", side_effect=OSError("x")):
            self.assertEqual(bluetooth.paired_devices(), [])

    def test_actions(self):
        with mock.patch.object(bluetooth, "_bluetoothctl",
                               return_value=(True, "ok")):
            self.assertTrue(bluetooth.pair("aa:bb:cc:dd:ee:ff")[0])
            self.assertTrue(bluetooth.trust("aa:bb:cc:dd:ee:ff")[0])
            self.assertTrue(bluetooth.connect("aa:bb:cc:dd:ee:ff")[0])
            self.assertTrue(bluetooth.remove("aa:bb:cc:dd:ee:ff")[0])
            self.assertTrue(bluetooth.scan(2)[0])
        for fn in (bluetooth.pair, bluetooth.trust, bluetooth.connect,
                   bluetooth.remove):
            self.assertFalse(fn("xx")[0])
        with mock.patch.object(bluetooth, "_bluetoothctl",
                               return_value=(False, "falhou")):
            self.assertFalse(bluetooth.pair("aa:bb:cc:dd:ee:ff")[0])
        with mock.patch.object(bluetooth, "mac_of", return_value="AA:BB:CC:DD:EE:FF"), \
             mock.patch.object(bluetooth, "_bluetoothctl",
                               return_value=(True, "Success")):
            self.assertTrue(bluetooth.disconnect("/dev/x")[0])


class TestProfiles(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": td}):
            self.assertEqual(profiles.load(), {})
            self.assertTrue(profiles.set_name("ABC", "Sala"))
            self.assertEqual(profiles.name_of("ABC"), "Sala")
            self.assertTrue(profiles.set_led("ABC", "2", 30))
            self.assertEqual(profiles.led_of("ABC"),
                             {"mode": "2", "brightness": 30})
            self.assertEqual(profiles.get("ABC")["name"], "Sala")
            self.assertEqual(profiles.get(None), {})
            self.assertEqual(profiles._key("  "), "default")
            self.assertTrue(profiles.save({"x": 1}))
            self.assertEqual(profiles.load(), {"x": 1})

    def test_corrupt_and_failure(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": td}):
            path = profiles.profiles_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("{quebrado")
            self.assertEqual(profiles.load(), {})
            with mock.patch("backend.profiles.os.makedirs",
                            side_effect=OSError("x")):
                self.assertFalse(profiles.save({"a": 1}))
            with mock.patch("backend.profiles.save", return_value=False):
                self.assertTrue(profiles.update("X", a=1))
            self.assertTrue(profiles.set_led("", "1", 5))


class TestDiagnostics(unittest.TestCase):
    def test_basic(self):
        with mock.patch("builtins.open", mock.mock_open(
                read_data='NAME="Fedora"\nPRETTY_NAME="Fedora 44"\n')):
            self.assertEqual(diagnostics.os_release()["NAME"], "Fedora")
        with mock.patch.object(diagnostics, "_cmd", return_value="SecureBoot enabled"):
            self.assertEqual(diagnostics.secure_boot(), "enabled")
        with mock.patch.object(diagnostics, "_cmd", return_value="SecureBoot disabled"):
            self.assertEqual(diagnostics.secure_boot(), "disabled")
        with mock.patch.object(diagnostics, "_cmd", return_value="?"):
            self.assertEqual(diagnostics.secure_boot(), "desconhecido")
        with mock.patch("os.walk", return_value=[("/lib/modules/x/extra", [], ["xone_dongle.ko.xz"])]):
            self.assertIn("xone_dongle.ko.xz", diagnostics.module_path())
        with mock.patch("os.walk", return_value=[]), \
             mock.patch.object(diagnostics, "_cmd", return_value="/m/x.ko"):
            self.assertEqual(diagnostics.module_path(), "/m/x.ko")

    def test_collect_and_format(self):
        info = detector.DriverInfo(name="xone", dongle_sysfs="/d",
                                   detail="ok", dongles=["/d"],
                                   state="ready", xone_loaded=True,
                                   xone_version="1.0",
                                   usb_dongles=[{"id": "045e:02e6",
                                                 "path": "/u",
                                                 "driver": "xone"}])
        with mock.patch.object(diagnostics.detector, "detect", return_value=info), \
             mock.patch.object(diagnostics.detector, "dongle_active_clients",
                               return_value={"count": 1, "slots": {0}, "raw": "x"}), \
             mock.patch.object(diagnostics.firmware, "status",
                               return_value={"state": "installed", "detail": "ok",
                                             "files": ["/f"]}), \
             mock.patch.object(diagnostics.permissions, "status",
                               return_value={"detail": "ok"}), \
             mock.patch.object(diagnostics.xow, "service_active", return_value=False), \
             mock.patch.object(diagnostics.audio, "status",
                               return_value={"cards": [1], "sinks": [2], "sources": [3]}), \
             mock.patch.object(diagnostics.rumble, "find_gamepads",
                               return_value=[{"name": "Pad", "path": "/p",
                                              "phys": "g", "has_rumble": True}]), \
             mock.patch.object(diagnostics.battery, "list_batteries",
                               return_value=[{"device": "Pad", "percentage": 70,
                                              "level": "alto", "level_en": "high",
                                              "serial": "S", "power_supply": False}]):
            data = diagnostics.collect()
            text = diagnostics.format_markdown(data)
        self.assertEqual(data["driver"]["name"], "xone")
        self.assertIn("## Diagnóstico", text)
        self.assertIn("Pad", text)
        self.assertIn("Baterias", text)

    def test_collect_errors(self):
        info = detector.DriverInfo(name="nenhum")
        with mock.patch.object(diagnostics.detector, "detect", return_value=info), \
             mock.patch.object(diagnostics.detector, "dongle_active_clients",
                               side_effect=RuntimeError("x")), \
             mock.patch.object(diagnostics.firmware, "status",
                               side_effect=RuntimeError("x")), \
             mock.patch.object(diagnostics.permissions, "status",
                               side_effect=RuntimeError("x")), \
             mock.patch.object(diagnostics.xow, "service_active",
                               side_effect=RuntimeError("x")), \
             mock.patch.object(diagnostics.audio, "status",
                               side_effect=RuntimeError("x")), \
             mock.patch.object(diagnostics.rumble, "find_gamepads",
                               side_effect=RuntimeError("x")), \
             mock.patch.object(diagnostics.battery, "list_batteries",
                               side_effect=RuntimeError("x")):
            data = diagnostics.collect()
        self.assertEqual(data["active_clients"], {})
        self.assertIn("Dongles USB", diagnostics.format_markdown(data))


class TestBatteryNew(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(battery.level_pct("full"), 100)
        self.assertEqual(battery.level_pct("high"), 80)
        self.assertEqual(battery.level_pct("??"), -1)
        self.assertTrue(battery.is_reliable({"power_supply": True, "percentage": 50}))
        self.assertFalse(battery.is_reliable({"percentage": "x"}))
        self.assertEqual(battery.display_pct({"power_supply": True, "percentage": 50}), 50)
        self.assertEqual(battery.display_pct({"level_en": "low"}), 30)
        self.assertFalse(battery.is_low({"level_en": "high", "power_supply": False}))
        self.assertTrue(battery.is_low({"level_en": "critical"}))
        self.assertTrue(battery.is_low({"power_supply": True, "percentage": 10}))
        self.assertFalse(battery.is_low({"power_supply": True, "percentage": "x"}))


class TestXoneNew(unittest.TestCase):
    def test_active_and_version(self):
        with mock.patch("backend.detector.dongle_active_clients",
                        return_value={"count": 1}):
            self.assertEqual(xone.active_clients("/d")["count"], 1)
        with mock.patch("backend.detector.module_version", return_value="1.0"):
            self.assertEqual(xone.driver_version(), "1.0")

    def test_valid_poweroff(self):
        good = "/sys/bus/usb/drivers/xone-dongle/1-1:1.0/poweroff"
        self.assertEqual(xone._valid_poweroff_file(good), good)
        for bad in (None, "", "/etc/poweroff",
                    "/sys/bus/usb/drivers/xone-dongle/../poweroff"):
            self.assertIsNone(xone._valid_poweroff_file(bad))

    def test_poweroff_validation(self):
        self.assertFalse(xone.poweroff("x")[0])
        self.assertFalse(xone.poweroff(99)[0])
        with mock.patch("backend.xone.glob.glob", return_value=[]):
            self.assertFalse(xone.poweroff(1)[0])
        with mock.patch("backend.xone.glob.glob",
                        return_value=["/sys/bus/usb/drivers/xone-dongle/1-1:1.0"]), \
             mock.patch("os.path.isfile", return_value=False):
            self.assertFalse(xone.poweroff(1)[0])

    def test_poweroff_paths(self):
        base = "/sys/bus/usb/drivers/xone-dongle/1-1:1.0"
        pf = base + "/poweroff"
        with mock.patch("backend.xone.glob.glob", return_value=[base]), \
             mock.patch("os.path.isfile", return_value=True), \
             mock.patch("builtins.open", mock.mock_open()) as op:
            self.assertTrue(xone.poweroff(1)[0])
            op.assert_called_once_with(pf, "w")
        with mock.patch("backend.xone.glob.glob", return_value=[base]), \
             mock.patch("os.path.isfile", return_value=True), \
             mock.patch("builtins.open", side_effect=PermissionError), \
             mock.patch.object(xone, "_run_helper",
                               return_value=mock.Mock(returncode=0)):
            self.assertTrue(xone.poweroff(-1)[0])
        with mock.patch("backend.xone.glob.glob", return_value=[base]), \
             mock.patch("os.path.isfile", return_value=True), \
             mock.patch("builtins.open", side_effect=PermissionError), \
             mock.patch.object(xone, "_run_helper",
                               return_value=mock.Mock(returncode=1, stderr="no")):
            self.assertFalse(xone.poweroff(1)[0])
        with mock.patch("backend.xone.glob.glob", return_value=[base]), \
             mock.patch("os.path.isfile", return_value=True), \
             mock.patch("builtins.open", side_effect=PermissionError), \
             mock.patch.object(xone, "_run_helper", return_value=None), \
             mock.patch.object(xone, "_run_pkexec_shell",
                               return_value=mock.Mock(returncode=0)):
            self.assertTrue(xone.poweroff(1)[0])
        with mock.patch("backend.xone.glob.glob", return_value=[base]), \
             mock.patch("os.path.isfile", return_value=True), \
             mock.patch("builtins.open", side_effect=PermissionError), \
             mock.patch.object(xone, "_run_helper", return_value=None), \
             mock.patch.object(xone, "_run_pkexec_shell",
                               return_value=mock.Mock(returncode=1, stderr="x")):
            self.assertFalse(xone.poweroff(1)[0])
        with mock.patch("backend.xone.glob.glob", return_value=[base]), \
             mock.patch("os.path.isfile", return_value=True), \
             mock.patch("builtins.open", side_effect=PermissionError), \
             mock.patch.object(xone, "_run_helper", return_value=None), \
             mock.patch.object(xone, "_run_pkexec_shell",
                               side_effect=FileNotFoundError):
            self.assertFalse(xone.poweroff(1)[0])

    def test_wakeup(self):
        base = "/sys/bus/usb/devices/3-1"
        with mock.patch("backend.xone.glob.glob", return_value=[base + "/idVendor"]), \
             mock.patch("builtins.open", mock.mock_open(read_data="045e")):
            # idProduct lê o mesmo mock (045e) -> não casa; cobre o continue
            self.assertIsNone(xone._wakeup_file())
        data = {"idVendor": "045e", "idProduct": "02e6",
                "power/wakeup": "enabled"}

        def fake_open(path, *a, **k):
            key = path.replace(base + "/", "")
            if key in data:
                return mock.mock_open(read_data=data[key]).return_value
            raise OSError("x")

        with mock.patch("backend.xone.glob.glob", return_value=[base + "/idVendor"]), \
             mock.patch("os.path.isfile", return_value=True), \
             mock.patch("builtins.open", side_effect=fake_open):
            self.assertEqual(xone._wakeup_file(), base + "/power/wakeup")
            self.assertTrue(xone.get_wakeup())
        with mock.patch.object(xone, "_wakeup_file", return_value=None):
            self.assertIsNone(xone.get_wakeup())
            self.assertFalse(xone.set_wakeup(True)[0])
        with mock.patch.object(xone, "_wakeup_file", return_value="/w"), \
             mock.patch("builtins.open", mock.mock_open()) as op:
            self.assertTrue(xone.set_wakeup(True)[0])
            op.assert_called_once_with("/w", "w")
        with mock.patch.object(xone, "_wakeup_file", return_value="/w"), \
             mock.patch("builtins.open", side_effect=PermissionError), \
             mock.patch.object(xone, "_run_helper",
                               return_value=mock.Mock(returncode=0)):
            self.assertTrue(xone.set_wakeup(False)[0])
        with mock.patch.object(xone, "_wakeup_file", return_value="/w"), \
             mock.patch("builtins.open", side_effect=PermissionError), \
             mock.patch.object(xone, "_run_helper", return_value=None), \
             mock.patch.object(xone, "_run_pkexec_shell",
                               return_value=mock.Mock(returncode=0)):
            self.assertTrue(xone.set_wakeup(True)[0])
        with mock.patch.object(xone, "_wakeup_file", return_value="/w"), \
             mock.patch("builtins.open", side_effect=OSError("x")):
            self.assertFalse(xone.set_wakeup(True)[0])


class TestDetectorNew(unittest.TestCase):
    def test_module(self):
        with mock.patch("os.path.isdir", return_value=True):
            self.assertTrue(detector.module_loaded())
        with mock.patch("builtins.open", mock.mock_open(read_data="0.5.8")):
            self.assertEqual(detector.module_version(), "0.5.8")
        with mock.patch("builtins.open", side_effect=OSError):
            self.assertEqual(detector.module_version(), "")

    def test_systemctl(self):
        import subprocess
        with mock.patch("backend.detector.subprocess.run",
                        return_value=mock.Mock(stdout="active\n")):
            self.assertEqual(detector._systemctl(["is-active"]), "active")
        with mock.patch("backend.detector.subprocess.run",
                        side_effect=subprocess.TimeoutExpired("x", 1)):
            self.assertEqual(detector._systemctl(["x"]), "")

    def test_usb_and_poweroff(self):
        with mock.patch("backend.detector.glob.glob",
                        return_value=["/u/idVendor"]), \
             mock.patch("backend.detector._read", side_effect=[
                 "045e", "02e6", "", "XBOX", "", "0100", ""]):
            out = detector.find_usb_dongles()
        self.assertEqual(out[0]["id"], "045e:02e6")
        with mock.patch("backend.detector.detect_xone_dongle",
                        return_value="/d"), \
             mock.patch("os.path.isfile", return_value=True):
            self.assertEqual(detector.dongle_poweroff_file(), "/d/poweroff")
        with mock.patch("backend.detector.detect_xone_dongle", return_value=None):
            self.assertIsNone(detector.dongle_poweroff_file())

    def test_active_clients(self):
        raw = "Active clients: 2\n[00]* [01]\n[02] [03]\n"
        with mock.patch("backend.detector.detect_xone_dongle", return_value="/d"), \
             mock.patch("backend.detector._read", return_value=raw):
            out = detector.dongle_active_clients()
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["slots"], {0})
        self.assertEqual(out["all_slots"], {0, 1, 2, 3})
        with mock.patch("backend.detector.detect_xone_dongle", return_value=None):
            self.assertEqual(detector.dongle_active_clients()["count"], 0)
        with mock.patch("backend.detector.detect_xone_dongle", return_value="/d"), \
             mock.patch("backend.detector._read",
                        return_value="Active clients: x\n"):
            self.assertEqual(detector.dongle_active_clients()["count"], 0)

    def test_detect_states(self):
        with mock.patch("backend.detector.detect_xone_dongle", return_value="/d"), \
             mock.patch("backend.detector.xone_pairing_file", return_value="/p"), \
             mock.patch("backend.detector.glob.glob", return_value=["/d"]), \
             mock.patch("backend.detector.find_usb_dongles", return_value=[{"id": "045e:02e6"}]):
            info = detector.detect()
        self.assertEqual(info.state, "ready")
        self.assertIn("xone", info.detail)
        with mock.patch("backend.detector.detect_xone_dongle", return_value=None), \
             mock.patch("backend.detector.detect_xow", return_value=False), \
             mock.patch("backend.detector.find_usb_dongles",
                        return_value=[{"id": "045e:02e6"}]), \
             mock.patch("backend.detector.module_loaded", return_value=False):
            info = detector.detect()
        self.assertEqual(info.state, "dongle-no-driver")
        with mock.patch("backend.detector.detect_xone_dongle", return_value=None), \
             mock.patch("backend.detector.detect_xow", return_value=True), \
             mock.patch("backend.detector.xow_active", return_value=False), \
             mock.patch("backend.detector.xow_enabled", return_value=True):
            info = detector.detect()
        self.assertEqual(info.state, "xow-stopped")
        with mock.patch("backend.detector.detect_xone_dongle", return_value=None), \
             mock.patch("backend.detector.detect_xow", return_value=False), \
             mock.patch("backend.detector.find_usb_dongles", return_value=[]):
            self.assertEqual(detector.detect().state, "none")


class TestXowNew(unittest.TestCase):
    def test_service(self):
        with mock.patch("backend.xow.subprocess.run",
                        return_value=mock.Mock(stdout="enabled\n")):
            self.assertTrue(xow.service_enabled())
        with mock.patch("backend.xow.subprocess.run", side_effect=OSError):
            self.assertFalse(xow.service_enabled())
        self.assertFalse(xow.service_control("bogus")[0])
        with mock.patch.object(xow, "_pkexec", return_value=None):
            self.assertFalse(xow.service_control("start")[0])
        with mock.patch.object(xow, "_pkexec", return_value="/p"), \
             mock.patch("backend.xow.subprocess.run",
                        return_value=mock.Mock(returncode=0)):
            self.assertTrue(xow.service_control("start")[0])
        with mock.patch.object(xow, "_pkexec", return_value="/p"), \
             mock.patch("backend.xow.subprocess.run",
                        return_value=mock.Mock(returncode=1, stderr="x")):
            self.assertFalse(xow.service_control("stop")[0])
        with mock.patch.object(xow, "_pkexec", return_value="/p"), \
             mock.patch("backend.xow.subprocess.run", side_effect=OSError("x")):
            self.assertFalse(xow.service_control("restart")[0])
        with mock.patch("backend.xow.subprocess.run",
                        return_value=mock.Mock(stdout="log", stderr="")):
            self.assertIn("log", xow.logs(10))
        with mock.patch("backend.xow.subprocess.run", side_effect=OSError("x")):
            self.assertIn("x", xow.logs("zz"))


class TestInputsNew(unittest.TestCase):
    def test_extras(self):
        from evdev import ecodes
        self.assertEqual(inputs.code_name(ecodes.BTN_SOUTH), "BTN_SOUTH")
        st = inputs.new_state()
        self.assertFalse(inputs.apply_key(st, 999999, True))
        self.assertTrue(st["extra"])
        self.assertTrue(inputs.pressed_names(st))
        inputs.apply_key(st, 999999, False)
        self.assertEqual(st["extra"], {})
        self.assertTrue(inputs.apply_key(st, ecodes.BTN_SOUTH, True))

    def test_resync_extras(self):
        from evdev import ecodes

        class Dev:
            def active_keys(self):
                return [ecodes.BTN_SOUTH, 999999]

            def absinfo(self, code):
                class A:
                    value = 0
                return A()

        st = inputs.new_state()
        self.assertTrue(inputs.resync(st, Dev(), {}, 0.1))
        self.assertTrue(st["extra"])


class TestRumbleNew(unittest.TestCase):
    def test_motor(self):
        with mock.patch.object(rumble, "rumble", return_value=(True, "ok")) as r:
            rumble.rumble_motor("/p", "strong", 100, 1000)
            self.assertEqual(r.call_args.kwargs["weak"], 0)
            rumble.rumble_motor("/p", "weak", 100, 1000)
            self.assertEqual(r.call_args.kwargs["strong"], 0)
            rumble.rumble_motor("/p", "both", 100, 99999)
            self.assertEqual(r.call_args.kwargs["strong"], 0xFFFF)


class TestPermissionsNew(unittest.TestCase):
    def test_poweroff_writable(self):
        with mock.patch("backend.permissions.glob.glob", return_value=[]):
            self.assertEqual(permissions.poweroff_writable(), (True, []))
        with mock.patch("backend.permissions.glob.glob",
                        return_value=["/p"]), \
             mock.patch("os.access", return_value=False):
            self.assertEqual(permissions.poweroff_writable()[0], False)


if __name__ == "__main__":
    unittest.main()
