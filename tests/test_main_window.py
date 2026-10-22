"""MainWindow/App (precisa de display; usa backends com mock)."""
import os

from tests import _env  # noqa: F401
import sys
import time
import unittest
from unittest import mock

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


def ctrl(i=0):
    return {"id": f"gip{i}.0:white:status", "sysfs": "/x",
            "mode": "1", "brightness": "20", "max_brightness": "50"}


def pad(i=0, name="Microsoft Xbox Controller"):
    return {"path": f"/dev/p{i}", "name": name, "has_rumble": True}


def bat(native="gip0.0", pct=70):
    return {"device": "Pad", "percentage": pct, "state": "Descarregando",
            "state_en": "discharging", "kind": "gaming-input",
            "level": "alto", "level_en": "high", "native_path": native,
            "serial": "S", "icon": "battery-good-symbolic",
            "time_empty": 0, "time_full": 0}


def pump(seconds=0.6):
    from gi.repository import GLib
    end = time.time() + seconds
    ctx = GLib.main_context_default()
    while time.time() < end:
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(0.02)


@NEEDS_DISPLAY
class MainWindowCase(unittest.TestCase):
    def setUp(self):
        from gi.repository import Adw, Gio
        self.app = Adw.Application(
            application_id="com.github.xbox-wireless-gui.Tests",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self._patchers = [
            ("prefs", mock.patch.object(main.prefs, "get_prefs",
                                        side_effect=prefs_mod.Prefs)),
            ("det", mock.patch.object(main, "detector")),
            ("xone", mock.patch.object(main, "xone")),
            ("rumble", mock.patch.object(main, "rumble")),
            ("battery", mock.patch.object(main, "battery")),
            ("fw", mock.patch.object(main, "firmware")),
            ("perm", mock.patch.object(main, "permissions")),
        ]
        self.mocks = {}
        for name, pt in self._patchers:
            self.mocks[name] = pt.start()
        self.det = self.mocks["det"]
        self.xone = self.mocks["xone"]
        self.rumble = self.mocks["rumble"]
        self.battery = self.mocks["battery"]
        self.fw = self.mocks["fw"]
        self.perm = self.mocks["perm"]
        self.addCleanup(self._stop_patches)
        self._std_xone()

    def _stop_patches(self):
        for _, pt in self._patchers:
            try:
                pt.stop()
            except RuntimeError:
                pass

    def _std_xone(self, n=1, pairing=False, dongles=1, name="xone"):
        dlist = [f"/d/{i}" for i in range(max(dongles, 1))]
        info = DriverInfo(name=name,
                          dongle_sysfs=dlist[0] if name == "xone" else None,
                          detail="", dongles=dlist if name == "xone" else [])
        self.det.detect.return_value = info
        self.xone.get_pairing.return_value = pairing
        self.xone.list_controllers.return_value = [ctrl(i) for i in range(n)]
        self.xone.set_pairing.return_value = (True, "ok")
        self.xone.set_led.return_value = (True, "ok")
        self.rumble.find_gamepads.return_value = [pad()]
        self.rumble.rumble.return_value = (True, "ok")
        self.battery.list_batteries.return_value = [bat()]
        self.fw.status.return_value = {"state": "installed",
                                       "detail": "fw ok",
                                       "script": "/s"}
        self.fw.script_for.return_value = "/s"
        self.perm.status.return_value = {"ok": True, "detail": "tudo certo"}
        self.perm.install_fix.return_value = (True, "ok")
        self.fw.install.return_value = (True, "ok")

    def _win(self):
        main.prefs.get_prefs.side_effect = prefs_mod.Prefs
        w = main.MainWindow(self.app)
        w._prefs.set_bool("check-updates", False)
        return w

    def test_refresh_xone(self):
        w = self._win()
        w.on_refresh()
        self.assertIn("xone", w.driver_row.get_title())
        self.assertEqual(len(w.cards), 1)
        self.assertTrue(w.bat_rows)
        # segundo refresh com mesmos dados: early-return
        w.on_refresh()
        self.assertEqual(len(w.cards), 1)

    def test_refresh_pairing_elapsed(self):
        self._std_xone(pairing=True)
        w = self._win()
        w.on_refresh()
        self.assertIn("desde", w.driver_row.get_subtitle())
        first = w._pair_since
        w.on_refresh()
        self.assertEqual(w._pair_since, first)

    def test_refresh_multi_dongle(self):
        self._std_xone(dongles=2)
        w = self._win()
        w.on_refresh()
        self.assertTrue(w.dongle_row.get_visible())
        w._loading_dongle = True
        w._on_dongle_selected(w.dongle_drop, None)
        w._loading_dongle = False
        w.dongle_drop.set_selected(1)
        self.assertEqual(w._prefs.get_string("selected-dongle"), "/d/1")

    def test_refresh_xow_and_none(self):
        self._std_xone(name="xow")
        from backend import xow as _xow
        with mock.patch.object(_xow, "service_active",
                               return_value=True):
            w = self._win()
            w.on_refresh()
            self.assertIn("xow", w.driver_row.get_title())
        self._std_xone(name="nenhum")
        w = self._win()
        w.on_refresh()
        self.assertTrue(w.banner.get_revealed())

    def test_refresh_empty(self):
        self._std_xone(n=0)
        self.rumble.find_gamepads.return_value = []
        self.battery.list_batteries.return_value = []
        w = self._win()
        w.on_refresh()
        self.assertEqual(w.cards, [])
        self.assertTrue(w.empty_wrap.get_visible())

    def test_refresh_virtual_pad(self):
        self._std_xone(n=0)
        self.rumble.find_gamepads.return_value = [
            pad(0, "Microsoft X-Box 360 pad 0")]
        w = self._win()
        w.on_refresh()
        self.assertEqual(len(w.cards), 1)
        self.assertIn("virtual", w.cards[0].get_title())

    def test_pair_actions(self):
        w = self._win()
        w.on_refresh()
        w._updating_switch = True
        w._on_pair_switch(w.pair_switch, None)
        self.xone.set_pairing.assert_not_called()
        w._updating_switch = False
        w._on_pair_switch(w.pair_switch, None)
        pump()
        self.xone.set_pairing.assert_called()
        w.on_pair()
        pump()
        self.xone.set_pairing.assert_called_with(True, "/d/0")

    def test_pair_xow_none(self):
        from backend import xow as _xow
        self._std_xone(name="xow")
        w = self._win()
        with mock.patch.object(_xow, "set_pairing",
                               return_value=(True, "ok")), \
             mock.patch.object(w, "_start_xow_countdown") as cd:
            w.on_pair()
            pump()
            cd.assert_called_once()
        self._std_xone(name="nenhum")
        w = self._win()
        with mock.patch.object(main.xow, "available",
                               return_value=False):
            w.on_pair()

    def test_vibrate(self):
        w = self._win()
        w.on_refresh()
        w.vibrate_path("/dev/p0")
        pump()
        self.rumble.rumble.assert_called()
        args, kw = self.rumble.rumble.call_args
        self.assertEqual(kw["duration_ms"],
                         w._prefs.get_int("rumble-duration"))
        self.rumble.find_gamepads.return_value = []
        w.vibrate_first()
        w._on_vibrate_all(None)

    def test_disconnect_bt(self):
        w = self._win()
        with mock.patch.object(main.bluetooth, "disconnect",
                               return_value=(True, "ok")) as d:
            w.disconnect_bt("/dev/bt0")
            pump()
            d.assert_called_once_with("/dev/bt0")

    def test_rumble_prefs(self):
        w = self._win()
        w.rumble_dur.set_value(900)
        w._on_rumble_dur(w.rumble_dur)
        self.assertEqual(w._prefs.get_int("rumble-duration"), 900)
        w.rumble_int.set_value(70)
        w._on_rumble_int(w.rumble_int)
        self.assertEqual(w._prefs.get_int("rumble-strong"), 70)
        self.assertEqual(w._prefs.get_int("rumble-weak"), 70)

    def test_fw_flow(self):
        w = self._win()
        w._refresh_firmware_row()
        self.assertIn("fw ok", w.fw_row.get_subtitle())
        w._on_fw_confirm(None, "cancel")
        self.assertFalse(w._fw_busy)
        with mock.patch.object(main.firmware, "install",
                               return_value=(True, "feito")):
            w._on_fw_install(None)
            w._on_fw_confirm(None, "ok")
            pump()
        self.assertFalse(w._fw_busy)
        self.fw.status.return_value = {"state": "missing",
                                       "detail": "nada",
                                       "script": None}
        w._refresh_firmware_row()
        self.assertFalse(w.fw_install_btn.get_sensitive())

    def test_perm_flow(self):
        w = self._win()
        w._refresh_perm_row()
        self.assertIn("tudo certo", w.perm_row.get_subtitle())
        w._on_perm_fix(None)
        self.assertTrue(w._perm_busy)
        pump()
        self.assertFalse(w._perm_busy)
        with mock.patch.object(main.permissions, "install_fix",
                               return_value=(False, "negado")):
            w._on_perm_fix(None)
            pump()
            self.assertFalse(w._perm_busy)

    def test_copy_fw(self):
        w = self._win()
        w._on_copy_fw(None)
        with mock.patch.object(main.Gdk.ContentProvider,
                               "new_for_bytes",
                               side_effect=RuntimeError("x")):
            w._on_copy_fw(None)

    def test_about(self):
        w = self._win()
        w._on_about()

    def test_updates(self):
        w = self._win()
        w._show_update("v9.9", "http://x/y")
        self.assertEqual(w.upd_btn.get_label(), "Abrir")
        with mock.patch.object(main.Gtk, "show_uri") as su:
            w._on_check_updates(None)
            su.assert_called_once()
        w._upd_url = ""
        with mock.patch.object(main.updates, "check",
                               return_value={"newer": True, "tag": "v2",
                                             "url": "http://x"}):
            w._on_check_updates(None)
            pump()
            self.assertEqual(w.upd_btn.get_label(), "Abrir")
        w._check_done({"newer": False, "tag": "v1", "url": ""})
        self.assertIn("última", w.upd_row.get_subtitle())
        w._check_done({"newer": False, "tag": "", "url": "",
                       "error": "x"})
        with mock.patch.object(main.updates, "check",
                               return_value={"newer": True, "tag": "v3",
                                             "url": "http://x"}):
            self.assertFalse(w._auto_update_check())
            pump()

    def test_countdown(self):
        from gi.repository import GLib
        self._std_xone(name="xow")
        w = self._win()
        w._start_xow_countdown()
        self.assertFalse(w.pair_btn.get_sensitive())
        loop = GLib.MainLoop()
        GLib.timeout_add(2500, loop.quit)
        loop.run()
        self.assertRegex(w.pair_btn.get_label(), r"Pareando… \d+s")
        self.assertFalse(w.pair_btn.get_sensitive())
        w._xow_left = 1
        loop2 = GLib.MainLoop()
        GLib.timeout_add(1500, loop2.quit)
        loop2.run()
        self.assertTrue(w.pair_btn.get_sensitive())

    def test_open_tester(self):
        w = self._win()
        with mock.patch.object(main, "TesterWindow") as tw:
            w.open_tester("/dev/p0")
            tw.assert_called_once()
        with mock.patch.object(main, "TesterWindow") as tw:
            w._on_open_tester(None)
            tw.assert_called_once()
        with mock.patch.object(main.TesterWindow, "present",
                               return_value=None):
            self.rumble.find_gamepads.return_value = []
            w.open_tester(None)

    def test_app(self):
        with mock.patch.object(main, "MainWindow") as mw:
            app = main.App()
            app.do_activate()
            mw.assert_called()
        with mock.patch.object(main.App, "run", return_value=0) as r:
            self.assertEqual(main.main(), 0)
            r.assert_called_once()


if __name__ == "__main__":
    unittest.main()
