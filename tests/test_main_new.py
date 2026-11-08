"""Testes das funções novas da UI (display necessário; sem hardware)."""
import io
import os
import sys
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

from tests import _env  # noqa: F401

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

try:
    import main
    from backend import prefs as prefs_mod
    from backend.detector import DriverInfo
    HAVE_MAIN = True
except Exception:  # noqa: BLE001
    HAVE_MAIN = False


def have_display():
    if not HAVE_MAIN:
        return False
    try:
        from gi.repository import Gdk
        return Gdk.Display.get_default() is not None
    except Exception:  # noqa: BLE001
        return False


NEEDS_DISPLAY = unittest.skipUnless(have_display(), "sem display")


def pump(seconds=0.4):
    from gi.repository import GLib
    end = time.time() + seconds
    ctx = GLib.main_context_default()
    while time.time() < end:
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(0.01)


def ctrl(cid="gip0.0:white:status"):
    return {"id": cid, "sysfs": "/x/" + cid, "mode": "1",
            "brightness": "20", "max_brightness": "50"}


def pad(i=0, uniq="S"):
    return {"path": f"/dev/q{i}", "name": "Microsoft Xbox Controller",
            "has_rumble": True, "uniq": uniq, "phys": "gip0.0/input0"}


def bat(serial="S", pct=70):
    return {"device": "Pad", "percentage": pct, "state": "Descarregando",
            "state_en": "discharging", "kind": "gaming-input",
            "level": "alto", "level_en": "high", "native_path": "gip0.0",
            "serial": serial, "icon": "battery-good-symbolic",
            "time_empty": 0, "time_full": 0, "is_reliable": True}


@NEEDS_DISPLAY
class MainNewCase(unittest.TestCase):
    def setUp(self):
        from gi.repository import Adw, Gio
        self.app = Adw.Application(
            application_id="com.github.xbox-wireless-gui.NewTests",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self._pts = [
            ("prefs", mock.patch.object(main.prefs, "get_prefs",
                                        side_effect=prefs_mod.Prefs)),
            ("det", mock.patch.object(main, "detector")),
            ("xone", mock.patch.object(main, "xone")),
            ("rumble", mock.patch.object(main, "rumble")),
            ("battery", mock.patch.object(main, "battery")),
            ("fw", mock.patch.object(main, "firmware")),
            ("perm", mock.patch.object(main, "permissions")),
            ("audio", mock.patch.object(main, "audio")),
            ("diag", mock.patch.object(main, "diagnostics")),
            ("profiles", mock.patch.object(main, "profiles")),
            ("xow", mock.patch.object(main, "xow")),
            ("bt", mock.patch.object(main, "bluetooth")),
            ("updates", mock.patch.object(main, "updates")),
        ]
        self.m = {}
        for name, pt in self._pts:
            self.m[name] = pt.start()
        self.addCleanup(self._stop)
        m = self.m
        info = DriverInfo(name="xone", dongle_sysfs="/d/0", detail="",
                          dongles=["/d/0"], state="ready",
                          xone_loaded=True, xone_version="0.5.8")
        m["det"].detect.return_value = info
        m["xone"].get_pairing.return_value = False
        m["xone"].list_controllers.return_value = [ctrl()]
        m["xone"].set_pairing.return_value = (True, "ok")
        m["xone"].set_led.return_value = (True, "ok")
        m["xone"].poweroff.return_value = (True, "ok")
        m["xone"].get_wakeup.return_value = True
        m["xone"].set_wakeup.return_value = (True, "ok")
        m["xone"].active_clients.return_value = {"count": 1, "slots": {0}}
        m["rumble"].find_gamepads.return_value = [pad()]
        m["rumble"].rumble.return_value = (True, "ok")
        m["battery"].list_batteries.return_value = [bat()]
        m["fw"].status.return_value = {"state": "installed", "detail": "ok",
                                       "script": "/s"}
        m["fw"].install.return_value = (True, "ok")
        m["perm"].status.return_value = {"ok": True, "detail": "ok"}
        m["perm"].install_fix.return_value = (True, "ok")
        m["audio"].status.return_value = {
            "available": True, "cards": [{"id": "3"}],
            "sinks": [{"id": "1", "name": "alsa.xbox.sink", "driver": "x"}],
            "sources": [{"id": "2", "name": "alsa.xbox.src", "driver": "x"}],
        }
        m["audio"].set_default.return_value = (True, "ok")
        m["audio"].set_volume.return_value = (True, "ok")
        m["audio"].set_mute.return_value = (True, "ok")
        m["diag"].format_markdown.return_value = "## Diagnóstico\nok"
        m["profiles"].name_of.return_value = ""
        m["profiles"].led_of.return_value = {}
        m["xow"].service_active.return_value = False
        m["xow"].available.return_value = False
        m["xow"].logs.return_value = "log"
        m["xow"].service_control.return_value = (True, "ok")
        m["bt"].is_bluetooth.return_value = False
        m["bt"].xbox_devices.return_value = [
            {"name": "Xbox Controller", "mac": "AA:BB:CC:DD:EE:FF"}]
        m["bt"].connect.return_value = (True, "ok")
        m["bt"].trust.return_value = (True, "ok")
        m["updates"].check.return_value = {"newer": False, "tag": ""}

    def _stop(self):
        for _, pt in self._pts:
            try:
                pt.stop()
            except RuntimeError:
                pass

    def _win(self):
        w = main.MainWindow(self.app)
        w._prefs.set_bool("check-updates", False)
        return w

    def test_preferences_handlers(self):
        w = self._win()
        w.refresh_spin.set_value(30)
        w._on_refresh_interval(w.refresh_spin)
        self.assertEqual(w._prefs.get_int("refresh-interval"), 30)
        w.pair_auto.set_selected(1)
        w._on_pair_auto(w.pair_auto, None)
        self.assertEqual(w._prefs.get_int("pairing-auto-off"), 30)
        self.assertEqual(w._pair_auto_index(), 1)
        w.notify_switch.set_active(False)
        w._on_notifications(w.notify_switch, None)
        self.assertFalse(w._prefs.get_bool("notifications"))
        w.updates_switch.set_active(True)
        w._on_check_updates_pref(w.updates_switch, None)
        self.assertTrue(w._prefs.get_bool("check-updates"))
        w.updates_switch.set_active(False)
        w._on_check_updates_pref(w.updates_switch, None)
        w.low_bat_spin.set_value(10)
        w._on_low_battery(w.low_bat_spin)
        self.assertEqual(w._prefs.get_int("low-battery"), 10)
        w._on_reset_prefs(None)
        self.assertEqual(w._prefs.get_int("refresh-interval"), 15)

    def test_wakeup_and_poweroff(self):
        w = self._win()
        w._refresh_wakeup()
        self.assertTrue(w.wakeup_switch.get_active())
        w._on_wakeup_switch(w.wakeup_switch, None)
        pump()
        self.m["xone"].set_wakeup.assert_called()
        w._on_poweroff_all(None)
        w._do_poweroff(None, "cancel", 1)
        w._do_poweroff(None, "ok", 1)
        pump()
        self.m["xone"].poweroff.assert_called()
        w._poweroff_done(True, "ok")

    def test_pair_auto_and_notifications(self):
        w = self._win()
        w._prefs.set_int("pairing-auto-off", 30)
        w._start_pair_auto_off()
        self.assertIsNotNone(w._pair_auto_id)
        w._start_pair_auto_off()
        w._pair_auto_off()
        pump()
        self.m["xone"].set_pairing.assert_called()
        w._cancel_pair_auto_off()
        self.assertIsNone(w._pair_auto_id)

        w._notify = mock.Mock()
        w._last_conn = {"A"}
        w.cards = [mock.Mock(serial="B")]
        w._check_connection_notifications([])
        self.assertTrue(w._notify.called)
        w._prefs.set_int("low-battery", 20)
        w._check_low_battery([bat(serial="S", pct=10)])
        w._check_low_battery([bat(serial="S", pct=90)])
        w._check_low_battery([{"device": "Pad", "level_en": "critical"}])
        w._check_low_battery([{"device": "Pad", "level_en": "high"}])

    def test_diagnostics_and_text(self):
        w = self._win()
        w._on_diagnostics()
        pump()
        self.m["diag"].format_markdown.assert_called()
        w._show_text_window("t", "x")
        w.copy_text("abc")
        with mock.patch.object(main.Gdk.ContentProvider, "new_for_bytes",
                               side_effect=RuntimeError("x")):
            w.copy_text("abc")
        w._on_xow_logs(None)
        w._xow_action("start")
        pump()
        w._refresh_xow_row(self.m["det"].detect.return_value)

    def test_bluetooth_and_audio(self):
        w = self._win()
        w._on_bt_scan(None)
        pump()
        w._show_bt_devices([])
        w._show_bt_devices([{"name": "Xbox", "mac": "AA:BB:CC:DD:EE:FF"}])
        w._bt_connect("AA:BB:CC:DD:EE:FF")
        pump()
        w._refresh_audio()
        self.assertGreater(len(w._audio_rows), 1)
        w._audio_default("sink", "alsa.xbox.sink")
        w._audio_volume("sink", "alsa.xbox.sink", 50)
        w._audio_mute("sink", "alsa.xbox.sink", True)
        pump()
        w._notify("t", "b")

    def test_refresh_branches(self):
        w = self._win()
        w.on_refresh()
        self.assertIn("xone", w.driver_row.get_title())
        self.m["det"].detect.return_value = DriverInfo(
            name="nenhum", detail="dongle sem driver", state="dongle-no-driver",
            usb_dongles=[{"id": "045e:02e6"}])
        w.on_refresh()
        self.assertIn("inativo", w.driver_row.get_title())
        self.assertTrue(w.banner.get_revealed())
        self.m["det"].detect.return_value = DriverInfo(
            name="xow", detail="parado", state="xow-stopped",
            xow_installed=True)
        w.on_refresh()
        self.assertIn("parado", w.driver_row.get_title())
        self.assertTrue(w.banner.get_revealed())

    def test_dongle_selected_and_tester(self):
        w = self._win()
        w._dongles = ["/a", "/b"]
        w._prefs.set_string("selected-dongle", "/b")
        self.assertEqual(w._selected_dongle(), "/b")
        with mock.patch.object(main, "TesterWindow") as tw:
            w.open_tester(None)
            tw.assert_called_once()
        with mock.patch.object(main.TesterWindow, "present"):
            self.m["rumble"].find_gamepads.return_value = []
            w.open_tester(None)

    def test_card_new_actions(self):
        win = mock.Mock()
        card = main.ControllerCard("Controle 1", "sub", "gip0.0:white:status",
                                   win, pad_path="/dev/q0", serial="S")
        self.assertEqual(card.power_index, 0)
        card._on_poweroff(None)
        win.poweroff_controller.assert_called_once()
        card._on_rename(None)
        win.rename_controller.assert_called_once()
        card._on_copy_info(None)
        win.copy_text.assert_called_once()
        card._on_vibrate_motor("strong")
        win.vibrate_path.assert_called_once_with("/dev/q0", motor="strong")
        with mock.patch.object(main.profiles, "led_of",
                               return_value={"mode": "1", "brightness": 20}), \
             mock.patch.object(main.xone, "set_led",
                               return_value=(True, "ok")) as sl:
            card.apply_saved_profile()
            pump()
            sl.assert_called_once()
        card._led_done("ok")
        card.set_battery_info({"percentage": 50, "state": "x",
                               "level": "normal", "level_en": "normal"})
        card.set_battery_info({"percentage": -1, "state": "x"})
        card.set_battery(50, "y")

    def test_tester_copy(self):
        class Fake:
            _state = main.inputs.new_state()
            _raw = main.deque(["KEY A=1"])
            get_clipboard = mock.Mock()
        main.TesterWindow._on_copy_state(Fake(), None)
        self.assertTrue(Fake.get_clipboard.called)
        with mock.patch.object(main.Gdk.ContentProvider, "new_for_bytes",
                               side_effect=RuntimeError("x")):
            main.TesterWindow._on_copy_state(Fake(), None)

    def test_edges(self):
        self.assertFalse(main.battery_is_reliable({"percentage": "x"}))
        self.assertEqual(main.battery_pct({"percentage": "x",
                                           "level_en": "nope"}), -1)
        self.assertEqual(main.battery_level_text({"level_en": "high"}), "alto")
        with mock.patch.object(main.bluetooth, "is_bluetooth",
                               side_effect=RuntimeError("x")):
            self.assertEqual(main.connection_kind("/p", None), "USB/evdev")
        self.assertEqual(main.connection_kind(None, None), "desconhecido")
        self.assertIsNone(main.power_index(None))
        self.assertIsNone(main.power_index("gipX"))
        self.assertEqual(main.power_index("gip0"), 0)
        self.assertEqual(main.power_index("gip0.1"), 1)

        w = self._win()
        w._on_window_close()
        w._refresh_wakeup()
        self.m["xone"].get_wakeup.return_value = None
        w._refresh_wakeup()
        w._updating_wakeup = True
        w._on_wakeup_switch(w.wakeup_switch, None)
        w._updating_wakeup = False
        self.m["xow"].service_active.side_effect = RuntimeError("x")
        w._refresh_xow_row(DriverInfo(name="xone"))
        self.m["xow"].service_active.side_effect = None
        self.m["xow"].service_active.return_value = False
        self.m["xow"].xbox_devices.side_effect = RuntimeError("x")
        w._on_bt_scan(None)
        pump()
        self.m["bt"].connect.return_value = (False, "não")
        w._bt_connect("AA:BB:CC:DD:EE:FF")
        pump()
        self.m["audio"].status.side_effect = RuntimeError("x")
        w._refresh_audio()
        self.m["audio"].status.side_effect = None
        self.m["audio"].status.return_value = {"available": False}
        w._refresh_audio()
        self.m["audio"].status.return_value = {"available": True,
                                                "cards": [], "sinks": [],
                                                "sources": []}
        w._refresh_audio()
        self.m["audio"].set_default.return_value = (False, "x")
        self.m["audio"].set_volume.return_value = (False, "x")
        self.m["audio"].set_mute.return_value = (False, "x")
        w._audio_default("sink", "s")
        w._audio_volume("sink", "s", 1)
        w._audio_mute("sink", "s", True)
        pump()
        self.m["xone"].active_clients.side_effect = RuntimeError("x")
        w.on_refresh()
        self.m["xone"].active_clients.side_effect = None
        self.m["xone"].active_clients.return_value = {"count": 1, "slots": {0}}
        self.m["battery"].list_batteries.return_value = []
        self.m["xone"].list_controllers.return_value = []
        self.m["rumble"].find_gamepads.return_value = []
        w.on_refresh()
        self.assertTrue(w.bat_rows)
        w.vibrate_first()
        w._on_rumble_int(mock.Mock(get_value=mock.Mock(side_effect=RuntimeError("x"))))

    def test_card_edges(self):
        win = mock.Mock()
        card = main.ControllerCard("C", "s", "gip0.0:white:status", win,
                                   pad_path=None, serial="S")
        card._on_vibrate(None)
        win.vibrate_first.assert_called_once()
        card._on_test_buttons(None)
        card._on_disconnect(None)
        with mock.patch.object(main.profiles, "set_led",
                               side_effect=RuntimeError("x")):
            card._led_done("ok")
        with mock.patch.object(main.profiles, "led_of",
                               return_value={"mode": "x", "brightness": "x"}):
            card.apply_saved_profile()
        with mock.patch.object(main.profiles, "led_of",
                               return_value={"mode": "9", "brightness": -1}):
            card.apply_saved_profile()
        with mock.patch.object(main.profiles, "led_of",
                               return_value={"mode": "1", "brightness": 20}), \
             mock.patch.object(card.led_mode, "set_selected",
                               side_effect=RuntimeError("x")):
            card.apply_saved_profile()
        with mock.patch.object(main.xone, "set_led",
                               side_effect=RuntimeError("x")):
            card._on_led_apply(None)
            pump()
        card2 = main.ControllerCard("C", "s", None, win, pad_path=None)
        card2._on_vibrate(None)
        win.vibrate_first.assert_called()


class TestCli(unittest.TestCase):
    def setUp(self):
        self._pts = [
            mock.patch.object(main, "detector"),
            mock.patch.object(main, "xone"),
            mock.patch.object(main, "battery"),
            mock.patch.object(main, "diagnostics"),
            mock.patch.object(main, "xow"),
        ]
        self.m = {}
        for name, pt in zip(("det", "xone", "bat", "diag", "xow"), self._pts):
            self.m[name] = pt.start()
        self.addCleanup(self._stop)
        self.m["det"].detect.return_value = DriverInfo(
            name="xone", dongle_sysfs="/d", state="ready", dongles=["/d"])
        self.m["xone"].get_pairing.return_value = False
        self.m["xone"].list_controllers.return_value = [ctrl()]
        self.m["xone"].active_clients.return_value = {"count": 1, "slots": {0}}
        self.m["xone"].set_pairing.return_value = (True, "ok")
        self.m["xone"].poweroff.return_value = (True, "ok")
        self.m["xone"].set_led.return_value = (True, "ok")
        self.m["bat"].list_batteries.return_value = [bat()]
        self.m["diag"].format_markdown.return_value = "diag"

    def _stop(self):
        for pt in self._pts:
            try:
                pt.stop()
            except RuntimeError:
                pass

    def test_status_and_actions(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main._cli(["--status"]), 0)
            self.assertEqual(main._cli(["--status", "--json"]), 0)
            self.assertEqual(main._cli(["--diagnose"]), 0)
            self.assertEqual(main._cli(["--pair", "on"]), 0)
            self.assertEqual(main._cli(["--poweroff"]), 0)
            self.assertEqual(main._cli(["--led", "gip0", "2", "5"]), 0)
            self.assertEqual(main._cli(["--version"]), 0)
            self.assertEqual(main._cli(["--help"]), 0)
            self.assertIsNone(main._cli([]))
            self.m["det"].detect.return_value = DriverInfo(name="xow")
            self.m["xow"].available.return_value = True
            self.m["xow"].set_pairing.return_value = (True, "ok")
            self.assertEqual(main._cli(["--pair", "on"]), 0)
            self.assertEqual(main._cli(["--pair", "off"]), 1)
            self.m["det"].detect.return_value = DriverInfo(name="nenhum")
            self.m["xow"].available.return_value = False
            self.assertEqual(main._cli(["--pair", "on"]), 1)
        self.assertIn("driver:", out.getvalue())
        self.assertIn("diag", out.getvalue())


if __name__ == "__main__":
    unittest.main()
