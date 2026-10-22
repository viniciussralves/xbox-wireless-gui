"""Widgets main.py que precisam de display (pulados sem X/Wayland)."""
import os

from tests import _env  # noqa: F401
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

try:
    import main
    HAVE_MAIN = True
except Exception:  # noqa: BLE001 (CI sem gir)
    HAVE_MAIN = False


def pump(seconds=0.3):
    from gi.repository import GLib
    end = time.time() + seconds
    ctx = GLib.main_context_default()
    while time.time() < end:
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(0.01)


def have_display():
    if not HAVE_MAIN:
        return False
    try:
        from gi.repository import Gdk
        return Gdk.Display.get_default() is not None
    except Exception:  # noqa: BLE001
        return False


NEEDS_DISPLAY = unittest.skipUnless(have_display(), "sem display")


def fake_controller(cid="gip0.0:white:status"):
    return {"id": cid, "sysfs": "/sys/" + cid, "mode": "1",
            "brightness": "20", "max_brightness": "50"}


def fake_battery():
    return {"device": "Pad", "percentage": 70, "state": "Descarregando",
            "state_en": "discharging", "kind": "gaming-input",
            "level": "alto", "level_en": "high", "native_path": "gip0.0",
            "serial": "S", "icon": "battery-good-symbolic",
            "time_empty": 0, "time_full": 0}


@NEEDS_DISPLAY
class TestControllerCard(unittest.TestCase):
    def setUp(self):
        self.win = mock.Mock()
        self.xone_p = mock.patch.object(main.xone, "list_controllers",
                                        return_value=[fake_controller()])
        self.xone_p.start()
        self.addCleanup(self.xone_p.stop)

    def test_led_card(self):
        card = main.ControllerCard("Controle 1", "sub",
                                   "gip0.0:white:status", self.win,
                                   pad_path="/dev/event9")
        self.assertEqual(int(card.led_scale.get_value()), 20)
        self.assertEqual(int(card.led_mode.get_selected()), 1)
        card.set_battery_info(fake_battery())
        card.set_battery_info({"percentage": -1, "state": "x"})
        card.set_battery(50, "y")
        with mock.patch.object(main.xone, "set_led",
                               return_value=(True, "ok")) as sl:
            card.led_scale.set_value(30)
            card._on_led_apply(None)
            pump()
            sl.assert_called_once_with("gip0.0:white:status", "1", "30")
        self.win.toast.assert_called()
        card._on_vibrate(None)
        self.win.vibrate_path.assert_called_once_with("/dev/event9")
        card2 = main.ControllerCard("T", "s", None, self.win,
                                    pad_path=None)
        card2._on_vibrate(None)
        self.win.vibrate_first.assert_called_once()
        card._on_test_buttons(None)
        self.win.open_tester.assert_called_once_with("/dev/event9")

    def test_no_led_no_crash(self):
        card = main.ControllerCard("Pad", "/dev/x", None, self.win,
                                   pad_path="/dev/x")
        self.assertFalse(hasattr(card, "led_scale"))
        card._on_led_apply(None)  # led_id None -> sai sem erro

    def test_bt_disconnect_row(self):
        with mock.patch.object(main.bluetooth, "is_bluetooth",
                               return_value=True):
            card = main.ControllerCard("Pad", "s", None, self.win,
                                       pad_path="/dev/bt0")
        card._on_disconnect(None)
        self.win.disconnect_bt.assert_called_once_with("/dev/bt0")

    def test_led_apply_fallback_mode(self):
        card = main.ControllerCard("Controle 1", "sub",
                                   "gip0.0:white:status", self.win,
                                   pad_path="/dev/event9")
        card.led_mode = mock.Mock()
        card.led_mode.get_selected.side_effect = RuntimeError("x")
        with mock.patch.object(main.xone, "list_controllers",
                               return_value=[fake_controller()]), \
             mock.patch.object(main.xone, "set_led",
                               return_value=(True, "ok")) as sl:
            card._on_led_apply(None)
            pump()
            sl.assert_called_once_with("gip0.0:white:status", "1", "20")


@NEEDS_DISPLAY
class TestStyle(unittest.TestCase):
    def test_thresholds(self):
        from gi.repository import Gtk
        bar = Gtk.LevelBar(min_value=0, max_value=100)
        main.style_bat_bar(bar, 10)
        self.assertTrue(bar.has_css_class("crit"))
        main.style_bat_bar(bar, 30)
        self.assertTrue(bar.has_css_class("warn"))
        main.style_bat_bar(bar, 80)
        self.assertFalse(bar.has_css_class("warn"))
        self.assertFalse(bar.has_css_class("crit"))


class TestDraw(unittest.TestCase):
    """Só precisa de cairo (roda sem display)."""

    def test_draw_all_states(self):
        if not HAVE_MAIN:
            self.skipTest("sem main")
        import cairo
        from backend import inputs

        class FakeArea:
            def get_style_context(self):
                raise AttributeError("x")

        class Fake:
            pass

        for pressed in (False, True):
            st = inputs.new_state()
            if pressed:
                st.update({"a": True, "lb": True, "xbox": True,
                           "l3": True, "lx": 0.5, "ly": -0.3,
                           "lt": 0.7, "rt": 0.2, "hat": (1, 0)})
                st["back"] = st["start"] = st["rb"] = True
                st["x"] = st["y"] = st["b"] = True
                st["r3"] = True
            fake = Fake()
            fake._state = st
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 520, 360)
            cr = cairo.Context(surf)
            main.TesterWindow._draw(fake, FakeArea(), cr, 520, 360, None)
        # sem estado conectado / sem botões também não quebra
        fake = Fake()
        fake._state = inputs.new_state()
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 800, 200)
        main.TesterWindow._draw(fake, FakeArea(),
                                cairo.Context(surf), 800, 200, None)


@NEEDS_DISPLAY
class TestTesterWindow(unittest.TestCase):
    def setUp(self):
        import evdev
        self.evdev = evdev
        self.pipes = []

        class FakeDev:
            def __init__(self, path, events=()):
                self.path = path
                self.name = "Fake Pad"
                r, w = __import__("os").pipe()
                self.fd = r
                self._w = w
                self._events = list(events)
                FakeDev._ws.append(w)

            def absinfo(self, code):
                return mock.Mock(value=0)

            def active_keys(self):
                return []

            def read_one(self):
                if self._events:
                    return self._events.pop(0)
                return None

            def close(self):
                import os as _os
                try:
                    _os.close(self.fd)
                except OSError:
                    pass

        FakeDev._ws = self.pipes
        self.FakeDev = FakeDev
        self.dev_list_p = mock.patch.object(
            main.inputs, "list_devices",
            return_value=[{"path": "/dev/t0", "name": "Fake Pad",
                           "has_rumble": False, "limits": {}}])
        self.dev_list_p.start()
        self.addCleanup(self.dev_list_p.stop)
        self.dev_p = mock.patch.object(evdev, "InputDevice", FakeDev)
        self.dev_p.start()
        self.addCleanup(self.dev_p.stop)
        self.addCleanup(self._close_pipes)

    def _close_pipes(self):
        import os as _os
        for w in self.pipes:
            try:
                _os.close(w)
            except OSError:
                pass

    def _win(self, **kw):
        return main.TesterWindow(None, **kw)

    def test_reload_open_flow(self):
        w = self._win(initial_path="/dev/t0")
        self.assertTrue(w._state["connected"])
        w._on_device_selected(w.dropdown, None)
        w._on_close()
        self.assertFalse(w._state["connected"])
        w._stop()

    def test_empty_devices(self):
        with mock.patch.object(main.inputs, "list_devices",
                               return_value=[]):
            w = self._win()
            self.assertIn("evdev", w.status_label.get_text())

    def test_import_error(self):
        with mock.patch.dict(sys.modules, {"evdev": None}):
            w = self._win()
            self.assertIn("evdev", w.status_label.get_text().lower())

    def test_open_errors(self):
        with mock.patch.object(self.evdev, "InputDevice",
                               side_effect=PermissionError()):
            w = self._win()
            self.assertIn("permiss", w.status_label.get_text().lower())
        with mock.patch.object(self.evdev, "InputDevice",
                               side_effect=OSError("x")):
            w = self._win()
            self.assertIn("Falha", w.status_label.get_text())

    def test_io_blocking_and_key(self):
        from evdev import ecodes
        w = self._win()
        ev = mock.Mock(type=ecodes.EV_KEY, code=ecodes.BTN_SOUTH, value=1)
        w._dev.read_one = mock.Mock(
            side_effect=[ev, BlockingIOError(), ev])
        self.assertTrue(w._on_io(w._dev.fd, None))
        self.assertTrue(w._state["a"])
        # evento inválido é ignorado sem quebrar (retorna True, sem mudar nada)
        w._dev.read_one = mock.Mock(
            side_effect=[mock.Mock(type=999, code=1, value=1), None])
        self.assertTrue(w._on_io(w._dev.fd, None))
        self.assertIn("A", w.status_label.get_text())
        ecodes = self.evdev.ecodes
        ev = mock.Mock(type=ecodes.EV_KEY, code=ecodes.BTN_SOUTH, value=1)
        w = self._win()
        w._dev._events = [ev]
        self.assertTrue(w._on_io(w._dev.fd, None))
        self.assertIn("A", w.status_label.get_text())
        w._state["hat"] = (1, 0)
        w._state["a"] = False
        w._update_labels()
        self.assertIn("D-Pad", w.status_label.get_text())
        w._state["hat"] = (0, 0)
        w._update_labels()
        self.assertEqual(w.status_label.get_text(),
                         "Nenhum botão pressionado")

    def test_abs_event_and_sync_dropped(self):
        ecodes = self.evdev.ecodes
        w = self._win()
        ev = mock.Mock(type=ecodes.EV_ABS, code=ecodes.ABS_X, value=20000)
        syn = mock.Mock(type=ecodes.EV_SYN, code=ecodes.SYN_DROPPED)
        w._dev._events = [ev, syn]
        self.assertTrue(w._on_io(w._dev.fd, None))
        self.assertNotEqual(w._state["lx"], 0.0)
        # SYN_DROPPED com dessincronia real -> resync muda o estado
        w._state["a"] = False
        w._dev.active_keys = lambda: [ecodes.BTN_SOUTH]
        w._dev._events = [syn]
        self.assertTrue(w._on_io(w._dev.fd, None))
        self.assertTrue(w._state["a"])

    def test_io_closed_and_error(self):
        w = self._win()
        w._stop()
        self.assertFalse(w._on_io(-1, None))
        w2 = self._win()

        def boom():
            raise RuntimeError("x")
        w2._dev.read_one = boom
        self.assertFalse(w2._on_io(w2._dev.fd, None))

    def test_deadzone_handler(self):
        w = self._win()
        w.dz_scale.set_value(0.2)
        w._on_deadzone(w.dz_scale)
        self.assertAlmostEqual(w._deadzone(), 0.2)
        bad = mock.Mock()
        bad.get_double.side_effect = RuntimeError("x")
        old = w._prefs
        w._prefs = bad
        try:
            self.assertEqual(w._deadzone(), 0.0)
        finally:
            w._prefs = old
        badscale = mock.Mock()
        badscale.get_value.side_effect = RuntimeError("x")
        w._on_deadzone(badscale)


if __name__ == "__main__":
    unittest.main()
