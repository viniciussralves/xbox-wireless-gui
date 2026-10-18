"""Casos-limite de main.py (precisa de display)."""
import os
import sys
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


def ctrl(cid="gip0.0:white:status", mode="1", br="20", mx="50"):
    return {"id": cid, "sysfs": "/x/" + cid, "mode": mode,
            "brightness": br, "max_brightness": mx}


def pad(i=0, name="Microsoft Xbox Controller"):
    return {"path": f"/dev/q{i}", "name": name, "has_rumble": True}


def bat(native="gip0.0", pct=70, empty=0):
    return {"device": "Pad", "percentage": pct, "state": "Descarregando",
            "state_en": "discharging", "kind": "gaming-input",
            "level": "alto", "level_en": "high", "native_path": native,
            "serial": "S", "icon": "battery-good-symbolic",
            "time_empty": empty, "time_full": 0}


@NEEDS_DISPLAY
class ExtraCase(unittest.TestCase):
    def setUp(self):
        from gi.repository import Adw, Gio
        self.app = Adw.Application(
            application_id="com.github.xbox-wireless-gui.TestsExtra",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self._pts = [
            mock.patch.object(main.prefs, "get_prefs",
                              side_effect=prefs_mod.Prefs),
            mock.patch.object(main, "detector"),
            mock.patch.object(main, "xone"),
            mock.patch.object(main, "rumble"),
            mock.patch.object(main, "battery"),
            mock.patch.object(main, "firmware"),
            mock.patch.object(main, "permissions"),
        ]
        self.m = {}
        for name, pt in [("p", self._pts[0]), ("d", self._pts[1]),
                         ("x", self._pts[2]), ("r", self._pts[3]),
                         ("b", self._pts[4]), ("f", self._pts[5]),
                         ("pm", self._pts[6])]:
            self.m[name] = pt.start()
        self.addCleanup(self._stop)
        m = self.m
        m["d"].detect.return_value = DriverInfo(
            name="xone", dongle_sysfs="/d/0", detail="", dongles=["/d/0"])
        m["x"].get_pairing.return_value = False
        m["x"].list_controllers.return_value = [ctrl()]
        m["x"].set_pairing.return_value = (True, "ok")
        m["x"].set_led.return_value = (True, "ok")
        m["r"].find_gamepads.return_value = [pad()]
        m["r"].rumble.return_value = (True, "ok")
        m["b"].list_batteries.return_value = [bat()]
        m["f"].status.return_value = {"state": "installed",
                                      "detail": "ok", "script": "/s"}
        m["pm"].status.return_value = {"ok": True, "detail": "ok"}
        m["pm"].install_fix.return_value = (True, "ok")

    def _stop(self):
        for pt in self._pts:
            try:
                pt.stop()
            except RuntimeError:
                pass

    def _win(self):
        w = main.MainWindow(self.app)
        w._prefs.set_bool("check-updates", False)
        return w

    def test_led_invalid_values_fallback(self):
        bad = [dict(ctrl(), id="gip0", mode="9", brightness="abc",
                    max_brightness="zz")]
        with mock.patch.object(main.xone, "list_controllers",
                               return_value=bad):
            card = main.ControllerCard("C", "s", "gip0", mock.Mock(),
                                       pad_path="/dev/q0")
            self.assertEqual(int(card.led_scale.get_value()), 0)
            self.assertEqual(int(card.led_mode.get_selected()), 2)
        card.led_mode = mock.Mock()
        card.led_mode.get_selected.return_value = 99
        with mock.patch.object(main.xone, "list_controllers",
                               side_effect=RuntimeError("x")), \
             mock.patch.object(main.xone, "set_led",
                               return_value=(True, "ok")) as sl:
            card._on_led_apply(None)
            self.assertEqual(sl.call_args[0][1], "2")

    def test_battery_card_edges(self):
        card = main.ControllerCard("C", "s", None, mock.Mock(),
                                   pad_path=None)
        card.set_battery_info({"percentage": "xx", "state": "?"})
        card.set_battery_info(dict(bat(), time_empty=3600))

    def test_busy_returns(self):
        w = self._win()
        w._fw_busy = True
        with mock.patch.object(main.firmware, "install") as ins:
            w._on_fw_install(None)
            ins.assert_not_called()
        w._perm_busy = True
        with mock.patch.object(main.permissions, "install_fix") as fx:
            w._on_perm_fix(None)
            fx.assert_not_called()

    def test_deadzone_scale_errors(self):
        w = self._win()
        badscale = mock.Mock()
        badscale.get_value.side_effect = RuntimeError("x")
        w._on_rumble_dur(badscale)
        w._on_rumble_int(badscale)

    def test_countdown_replace(self):
        w = self._win()
        w._xow_countdown_id = 99999
        with mock.patch.object(main.GLib, "source_remove",
                               side_effect=RuntimeError("x")):
            w._start_xow_countdown()
        self.assertIsNotNone(w._xow_countdown_id)

    def test_auto_refresh(self):
        w = self._win()
        self.assertTrue(w._auto_refresh())
        with mock.patch.object(w, "on_refresh",
                               side_effect=RuntimeError("x")):
            self.assertTrue(w._auto_refresh())

    def test_xow_countdown_subtitle(self):
        self.m["d"].detect.return_value = DriverInfo(
            name="xow", dongle_sysfs=None, detail="", dongles=[])
        w = self._win()
        w._xow_countdown_id = 12345
        w._xow_left = 7
        w.on_refresh()
        self.assertIn("7", w.driver_row.get_subtitle())

    def test_focus_branches(self):
        w = self._win()
        w.on_refresh()
        w._fp_ctrl = None  # força reconstrução (evita early-return do fp)
        with mock.patch.object(w, "get_focus",
                               side_effect=RuntimeError("x")):
            w._refresh_controllers()
        w._fp_ctrl = None
        focus = mock.Mock()
        focus.get_parent.return_value = w.g_ctrl
        with mock.patch.object(w, "get_focus", return_value=focus):
            w._refresh_controllers()

    def test_item_variants(self):
        m = self.m
        # 2 leds, 2 bats (take segunda), 3 pads (sobra 1), fallback, ...
        m["x"].list_controllers.return_value = [ctrl("gip0"), ctrl("gip1")]
        m["b"].list_batteries.return_value = [bat("gip0", 70),
                                              bat("gip1", 60)]
        m["r"].find_gamepads.return_value = [pad(0), pad(1), pad(2)]
        w = self._win()
        w.on_refresh()
        self.assertEqual(len(w.cards), 3)
        # 1 pad para 2 leds -> fallback para o primeiro real
        m["r"].find_gamepads.return_value = [pad(0)]
        w.on_refresh()
        self.assertEqual(len(w.cards), 2)
        # bateria esgotada -> None
        m["b"].list_batteries.return_value = []
        m["x"].list_controllers.return_value = [ctrl()]
        w.on_refresh()
        # led não-gip e vazio
        m["x"].list_controllers.return_value = [dict(ctrl(), id="foo")]
        m["b"].list_batteries.return_value = [dict(bat(), native_path="")]
        w.on_refresh()
        self.assertIn("foo", w.cards[0].get_title())
        # led gip não-numérico -> retorna a base
        m["x"].list_controllers.return_value = [
            dict(ctrl(), id="gipX:white:status")]
        w.on_refresh()
        self.assertIn("gipX", w.cards[0].get_title())
        m["x"].list_controllers.return_value = [dict(ctrl(), id="")]
        w.on_refresh()

    def test_expanded_restore(self):
        w = self._win()
        w.on_refresh()
        title = w.cards[0].get_title()
        w.cards[0].set_expanded(True)
        self.m["b"].list_batteries.return_value = [bat(pct=71)]
        w.on_refresh()
        got = [c for c in w.cards if c.get_title() == title]
        self.assertTrue(got and got[0].get_expanded())

    def test_battery_rows_edges(self):
        w = self._win()
        self.m["b"].list_batteries.return_value = [
            dict(bat(), percentage="xx"),
            dict(bat(), time_empty=3600, percentage=40),
        ]
        w.on_refresh()
        self.assertEqual(len(w.bat_rows), 2)

    def test_vibrate_found_and_all(self):
        w = self._win()
        w.on_refresh()
        w.vibrate_first()
        self.m["r"].rumble.assert_called()
        w._on_vibrate_all(None)

    def test_styled_draw(self):
        import cairo
        from backend import inputs
        st = inputs.new_state()
        st["a"] = True

        class Area:
            def get_style_context(self):
                ctx = mock.Mock()
                col = mock.Mock(red=0.1, green=0.2, blue=0.3)
                ctx.get_color.return_value = col
                return ctx

        class Fake:
            _state = st

        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 520, 360)
        main.TesterWindow._draw(Fake(), Area(), cairo.Context(surf),
                                520, 360, None)


@NEEDS_DISPLAY
class TesterEdgeCase(unittest.TestCase):
    def test_stop_and_open_errors(self):
        import os as _os
        import evdev
        from evdev import ecodes

        class Dev:
            _all = []

            def __init__(self, path):
                r, w = _os.pipe()
                self.fd = r
                Dev._all.append((r, w))
                self.name = "D"

            def absinfo(self, code):
                raise OSError("x")

            def active_keys(self):
                return []

            def read_one(self):
                return None

            def close(self):
                raise OSError("x")

        try:
            with mock.patch.object(main.inputs, "list_devices",
                                   return_value=[{"path": "/d", "name": "D",
                                                  "has_rumble": False,
                                                  "limits": {ecodes.ABS_X: (0, 9)}}]), \
                 mock.patch.object(evdev, "InputDevice", Dev):
                w = main.TesterWindow(None)
                # absinfo OSError -> continue; close OSError no _stop
                w._open("/d")
                # source_remove falhando no _stop:
                w._watch_id = 424242
                with mock.patch.object(main.GLib, "source_remove",
                                       side_effect=RuntimeError("x")):
                    w._stop()
                # read_one OSError -> desconectado:
                with mock.patch.object(evdev, "InputDevice", Dev):
                    w2 = main.TesterWindow(None)
                with mock.patch.object(w2._dev, "read_one",
                                       side_effect=OSError("gone")):
                    self.assertFalse(w2._on_io(w2._dev.fd, None))
                self.assertIn("sconectado", w2.status_label.get_text())
                w2._stop()
        finally:
            for r, f in Dev._all:
                for fd in (r, f):
                    try:
                        _os.close(fd)
                    except OSError:
                        pass

    def test_open_inner_errors(self):
        import evdev

        class Dev:
            fd = 1
            name = "D"

            def __init__(self, path):
                pass

            def absinfo(self, code):
                class A:
                    value = 0
                return A()

            def close(self):
                pass

        with mock.patch.object(main.inputs, "list_devices",
                               return_value=[{"path": "/d", "name": "D",
                                              "has_rumble": False,
                                              "limits": {227: (0, 9)}}]), \
             mock.patch.object(evdev, "InputDevice", Dev), \
             mock.patch("os.set_blocking",
                        side_effect=OSError("noblock")), \
             mock.patch.object(main.inputs, "apply_abs",
                               side_effect=RuntimeError("boom")):
            # set_blocking falha (pass) + apply_abs falha (except externo)
            w = main.TesterWindow(None)
            self.assertIn("Lendo", w.status_label.get_text())
            w._stop()


if __name__ == "__main__":
    unittest.main()
