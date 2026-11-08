"""Testes dos módulos 0.3: log, monitores, histórico, API, helper e background."""
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests import _env  # noqa: F401

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backend import api, background, history, log, monitor, privclient, privhelper, remap


class TestLog(unittest.TestCase):
    def tearDown(self):
        logger = logging.getLogger(log.APP)
        for h in list(logger.handlers):
            logger.removeHandler(h)
            try:
                h.close()
            except Exception:  # noqa: BLE001
                pass
        log._configured = False

    def test_setup_and_tail(self):
        log._configured = False
        logger = logging.getLogger(log.APP)
        for h in list(logger.handlers):
            logger.removeHandler(h)
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.dict(os.environ, {"XDG_STATE_HOME": td}):
            path = log.log_path()
            logger = log.setup(verbose=True)
            logger.debug("teste 123")
            for h in logger.handlers:
                h.flush()
            self.assertTrue(os.path.isfile(path))
            self.assertIn("teste 123", log.tail(5))
            self.assertTrue(log.get_logger("x").name.endswith(".x"))
            self.assertIn("xbox-wireless-gui", log.log_path())
            self.assertIn("teste 123", log.tail("x"))
            log._configured = False
            logger2 = log.setup(filename=path)
            self.assertIs(logger2, logger)
            logger2.setLevel(logging.DEBUG)

    def test_tail_missing(self):
        with mock.patch("builtins.open", side_effect=OSError("x")):
            self.assertEqual(log.tail(), "")


class FakeMonitor:
    def __init__(self):
        self.cb = None
        self.cancelled = False

    def connect(self, _sig, cb):
        self.cb = cb

    def cancel(self):
        self.cancelled = True


class FakeFile:
    def __init__(self, mon):
        self.mon = mon

    def monitor_directory(self, *_a):
        return self.mon


class TestMonitor(unittest.TestCase):
    def test_fs_monitor(self):
        fake = FakeMonitor()
        fm = monitor.FsMonitor(lambda: None, paths=["/tmp"])
        with mock.patch("backend.monitor.Gio.File.new_for_path",
                        return_value=FakeFile(fake)):
            self.assertEqual(fm.start(), 1)
            self.assertEqual(fm.start(), 1)
            fake.cb(None, None, None)
            self.assertIsNotNone(fm._timeout_id)
            fm._fire()
            fm.stop()
            self.assertTrue(fake.cancelled)
        with mock.patch("backend.monitor.Gio.File.new_for_path",
                        side_effect=RuntimeError("x")):
            self.assertEqual(monitor.FsMonitor(lambda: None,
                                               paths=["/tmp"]).start(), 0)

    def test_upower_failure_and_stop(self):
        up = monitor.UPowerMonitor(lambda: None)
        with mock.patch("backend.monitor.gi.require_version",
                        side_effect=RuntimeError("x")):
            self.assertFalse(up.start())
        up.stop()

    def test_upower_success(self):
        client = mock.Mock()
        client.connect.side_effect = [1, 2, RuntimeError("x")]
        with mock.patch("backend.monitor._upower_client", return_value=client):
            up = monitor.UPowerMonitor(lambda: None)
            self.assertTrue(up.start())
            up._emit()
            up.stop()
        client.connect.side_effect = None
        client.connect.return_value = 1
        client.disconnect.side_effect = RuntimeError("x")
        with mock.patch("backend.monitor._upower_client", return_value=client):
            up = monitor.UPowerMonitor(lambda: None)
            self.assertTrue(up.start())
            up.stop()

    def test_monitor_branches(self):
        fm = monitor.FsMonitor(lambda: None, paths=["/nao-existe"])
        self.assertEqual(fm.start(), 0)
        fm._active = False
        fm._on_changed()
        fm._active = True
        fm._timeout_id = 123
        with mock.patch("backend.monitor.GLib.source_remove",
                        side_effect=RuntimeError("x")):
            fm._on_changed()
        fm.callback = mock.Mock(side_effect=RuntimeError("x"))
        fm._fire()
        fm._timeout_id = 456
        with mock.patch("backend.monitor.GLib.source_remove",
                        side_effect=RuntimeError("x")):
            fm.stop()
        bad = FakeMonitor()
        bad.cancel = mock.Mock(side_effect=RuntimeError("x"))
        fm._monitors = [bad]
        fm.stop()
        with mock.patch("backend.monitor.Gio.File.new_for_path",
                        side_effect=RuntimeError("x")):
            self.assertEqual(monitor.FsMonitor(
                lambda: None, paths=["/tmp"]).start(), 0)


class FakeDev:
    def __init__(self, native, path="/org/dev"):
        self.props = mock.Mock(native_path=native)
        self._path = path

    def get_object_path(self):
        return self._path


class TestHistory(unittest.TestCase):
    def test_device_path(self):
        client = mock.Mock()
        client.get_devices.return_value = [FakeDev("gip0.0")]
        with mock.patch("backend.history._client", return_value=client):
            self.assertEqual(history.device_path("gip0.0"), "/org/dev")
            self.assertIsNone(history.device_path(""))
            self.assertIsNone(history.device_path("x"))
        with mock.patch("backend.history._client", side_effect=RuntimeError("x")):
            self.assertIsNone(history.device_path("x"))

    def test_get_history(self):
        with mock.patch("backend.history._call",
                        return_value=[(1, 50.0, 2), (2, 40.0, 2)]):
            rows = history.get_history("gip0.0", hours=24)
        self.assertEqual(rows[0]["value"], 50.0)
        self.assertEqual(history.summarize(rows)["min"], 40.0)
        self.assertEqual(history.summarize([])["count"], 0)
        with mock.patch("backend.history._call", side_effect=RuntimeError("x")):
            self.assertEqual(history.get_history("x"), [])

    def test_call(self):
        reply = mock.Mock()
        reply.unpack.return_value = ([(1, 50.0, 2)],)
        conn = mock.Mock()
        conn.call_sync.return_value = reply
        with mock.patch("backend.history.device_path", return_value="/d"), \
             mock.patch("backend.history.Gio.bus_get_sync", return_value=conn):
            self.assertEqual(history._call("gip", "percentage", 10, 5),
                             [(1, 50.0, 2)])
        with mock.patch("backend.history.device_path", return_value=None):
            self.assertEqual(history._call("x", "percentage", 10, 5), [])


class TestRemap(unittest.TestCase):
    def test_available_and_open(self):
        with mock.patch("shutil.which", side_effect=lambda x: "/bin/" + x):
            self.assertEqual(remap.available(), "/bin/input-remapper-gtk")
            with mock.patch("backend.remap.subprocess.Popen") as p:
                self.assertTrue(remap.open_tool()[0])
                p.assert_called_once()
        with mock.patch("shutil.which", return_value=None):
            self.assertIsNone(remap.available())
            self.assertFalse(remap.open_tool()[0])
        with mock.patch("shutil.which", return_value="/bin/x"), \
             mock.patch("backend.remap.subprocess.Popen",
                        side_effect=OSError("x")):
            self.assertFalse(remap.open_tool()[0])
        self.assertIn("input-remapper", remap.hint())


class TestApi(unittest.TestCase):
    def callbacks(self):
        return {
            "status": lambda: {"driver": "xone"},
            "refresh": mock.Mock(),
            "present": mock.Mock(),
            "pairing": lambda b: (True, "ok"),
            "led": lambda a, b, c: (True, "ok"),
            "poweroff": lambda i: (True, "ok"),
        }

    def test_methods(self):
        a = api.Api(self.callbacks())
        self.assertIn("xone", a.handle_method_call(
            None, "", "", "", "GetStatus", None).unpack()[0])
        self.assertTrue(a.handle_method_call(
            None, "", "", "", "Refresh", None).unpack()[0])
        self.assertTrue(a.handle_method_call(
            None, "", "", "", "Present", None).unpack()[0])
        self.assertEqual(a.handle_method_call(
            None, "", "", "", "SetPairing",
            api.GLib.Variant("(b)", (True,))).unpack(), (True, "ok"))
        self.assertEqual(a.handle_method_call(
            None, "", "", "", "SetLed",
            api.GLib.Variant("(sss)", ("g", "1", "2"))).unpack(),
            (True, "ok"))
        self.assertEqual(a.handle_method_call(
            None, "", "", "", "Poweroff",
            api.GLib.Variant("(i)", (1,))).unpack(), (True, "ok"))
        self.assertFalse(a.handle_method_call(
            None, "", "", "", "Nope", None).unpack()[0])
        self.assertFalse(api.Api({}).handle_method_call(
            None, "", "", "", "GetStatus", None).unpack()[0])
        self.assertFalse(api.Api({}).handle_method_call(
            None, "", "", "", "Refresh", None).unpack()[0])

    def test_names_are_valid(self):
        self.assertNotIn("-", api.INTERFACE)
        self.assertNotIn("-", api.OBJECT_PATH)
        self.assertTrue(api.OBJECT_PATH.startswith("/"))
        self.assertNotIn("-", privhelper.INTERFACE)
        self.assertNotIn("-", privhelper.OBJECT_PATH)

    def test_register(self):
        conn = mock.Mock()
        a = api.register(conn, self.callbacks())
        self.assertIsInstance(a, api.Api)
        conn.register_object.assert_called_once()

    def test_invocation(self):
        inv = mock.Mock()
        a = api.Api(self.callbacks())
        self.assertIsNone(a.handle_method_call(
            None, "", "", "", "GetStatus", None, inv))
        inv.return_value.assert_called_once()


class TestPrivClient(unittest.TestCase):
    def test_installed(self):
        with mock.patch("backend.privclient.os.path.isfile", return_value=True):
            self.assertTrue(privclient.installed())
        with mock.patch("backend.privclient.os.path.isfile", return_value=False), \
             mock.patch.dict(os.environ, {"XWG_DBUS_HELPER": "1"}):
            self.assertTrue(privclient.installed())
        with mock.patch("backend.privclient.os.path.isfile", return_value=False), \
             mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(privclient.installed())

    def test_call_success_and_missing(self):
        reply = mock.Mock()
        reply.unpack.return_value = (True, "ok")
        conn = mock.Mock()
        conn.call_sync.return_value = reply
        with mock.patch.object(privclient, "installed", return_value=True), \
             mock.patch("backend.privclient.Gio.bus_get_sync", return_value=conn):
            self.assertEqual(privclient._call("Ping", api.GLib.Variant("()", ())),
                             (True, "ok"))
        with mock.patch.object(privclient, "installed", return_value=False):
            self.assertIsNone(privclient._call("Ping", None))
        with mock.patch.object(privclient, "installed", return_value=True), \
             mock.patch("backend.privclient.Gio.bus_get_sync",
                        side_effect=RuntimeError("x")):
            self.assertIsNone(privclient._call("Ping", None))
        err = privclient.GLib.Error.new_literal(
            privclient.Gio.DBusError.quark(), "AccessDenied", 0)
        conn.call_sync.side_effect = err
        with mock.patch.object(privclient, "installed", return_value=True), \
             mock.patch("backend.privclient.Gio.bus_get_sync", return_value=conn):
            self.assertFalse(privclient._call("Ping", None)[0])
        conn.call_sync.side_effect = privclient.GLib.Error.new_literal(
            privclient.GLib.quark_from_string("test"), "offline", 0)
        with mock.patch.object(privclient, "installed", return_value=True), \
             mock.patch("backend.privclient.Gio.bus_get_sync", return_value=conn):
            self.assertIsNone(privclient._call("Ping", None))

    def test_typed(self):
        with mock.patch.object(privclient, "_call", return_value=(True, "ok")) as c:
            self.assertEqual(privclient.set_pairing(True, "/p"), (True, "ok"))
            self.assertEqual(privclient.set_led("g", "1", "2"), (True, "ok"))
            self.assertEqual(privclient.poweroff("/p", 1), (True, "ok"))
            self.assertEqual(privclient.set_wakeup("/w", False), (True, "ok"))
            self.assertEqual(privclient.fix_permissions("u"), (True, "ok"))
            self.assertEqual(privclient.xow_action("start"), (True, "ok"))
            self.assertEqual(c.call_count, 6)


class TestPrivHelper(unittest.TestCase):
    def test_helper(self):
        with mock.patch("backend.privhelper.subprocess.run",
                        return_value=mock.Mock(returncode=0, stdout="ok",
                                               stderr="")):
            self.assertEqual(privhelper._helper("x"), (True, "ok"))
        with mock.patch("backend.privhelper.subprocess.run",
                        return_value=mock.Mock(returncode=1, stdout="",
                                               stderr="erro")):
            self.assertEqual(privhelper._helper("x"), (False, "erro"))
        with mock.patch("backend.privhelper.subprocess.run",
                        side_effect=OSError("x")):
            self.assertFalse(privhelper._helper("x")[0])
        with mock.patch("backend.privhelper.subprocess.run",
                        side_effect=subprocess.TimeoutExpired("x", 1)):
            self.assertFalse(privhelper._helper("x")[0])

    def test_authorized(self):
        conn = mock.Mock()
        conn.call_sync.side_effect = [
            mock.Mock(unpack=mock.Mock(return_value=(123,))),
            mock.Mock(unpack=mock.Mock(return_value=(True, False, {}))),
        ]
        self.assertTrue(privhelper._authorized(conn, ":1.1"))
        conn.call_sync.side_effect = RuntimeError("x")
        self.assertFalse(privhelper._authorized(conn, ":1.1"))

    def test_handle(self):
        conn = mock.Mock()
        with mock.patch.object(privhelper, "_authorized", return_value=True), \
             mock.patch.object(privhelper, "_helper", return_value=(True, "ok")):
            self.assertTrue(privhelper.handle(
                conn, ":1", "", "", "Ping", None).unpack()[0])
            self.assertEqual(privhelper.handle(
                conn, ":1", "", "", "Pairing",
                api.GLib.Variant("(ss)", ("on", "/x/pairing"))).unpack(),
                (True, "ok"))
            self.assertEqual(privhelper.handle(
                conn, ":1", "", "", "Led",
                api.GLib.Variant("(sss)", ("g", "1", "2"))).unpack(),
                (True, "ok"))
            self.assertEqual(privhelper.handle(
                conn, ":1", "", "", "Poweroff",
                api.GLib.Variant("(si)", ("/x/poweroff", 1))).unpack(),
                (True, "ok"))
            self.assertEqual(privhelper.handle(
                conn, ":1", "", "", "Wakeup",
                api.GLib.Variant("(ss)", ("/x/power/wakeup", "on"))).unpack(),
                (True, "ok"))
            self.assertEqual(privhelper.handle(
                conn, ":1", "", "", "FixPermissions",
                api.GLib.Variant("(s)", ("user",))).unpack(), (True, "ok"))
            self.assertEqual(privhelper.handle(
                conn, ":1", "", "", "Xow",
                api.GLib.Variant("(s)", ("start",))).unpack(), (True, "ok"))
            self.assertFalse(privhelper.handle(
                conn, ":1", "", "", "Pairing",
                api.GLib.Variant("(ss)", ("bad", "/x"))).unpack()[0])
            self.assertFalse(privhelper.handle(
                conn, ":1", "", "", "Led",
                api.GLib.Variant("(sss)", ("bad id", "1", "2"))).unpack()[0])
            self.assertFalse(privhelper.handle(
                conn, ":1", "", "", "Poweroff",
                api.GLib.Variant("(si)", ("/x/poweroff", 99))).unpack()[0])
            self.assertFalse(privhelper.handle(
                conn, ":1", "", "", "Wakeup",
                api.GLib.Variant("(ss)", ("/x", "on"))).unpack()[0])
            self.assertFalse(privhelper.handle(
                conn, ":1", "", "", "FixPermissions",
                api.GLib.Variant("(s)", ("-x",))).unpack()[0])
            self.assertFalse(privhelper.handle(
                conn, ":1", "", "", "Xow",
                api.GLib.Variant("(s)", ("bad",))).unpack()[0])
            self.assertFalse(privhelper.handle(
                conn, ":1", "", "", "Nope", None).unpack()[0])
            inv = mock.Mock()
            self.assertIsNone(privhelper.handle(
                conn, ":1", "", "", "Ping", None, inv))
            inv.return_value.assert_called_once()
        with mock.patch.object(privhelper, "_authorized", return_value=False):
            self.assertTrue(privhelper.handle(
                conn, ":1", "", "", "Ping", None).unpack()[0])
            self.assertFalse(privhelper.handle(
                conn, ":1", "", "", "Pairing",
                api.GLib.Variant("(ss)", ("on", "/x/pairing"))).unpack()[0])

    def test_register(self):
        conn = mock.Mock()
        privhelper.register(conn)
        conn.register_object.assert_called_once()

    def test_main_non_root(self):
        with mock.patch("backend.privhelper.os.geteuid", return_value=1000):
            self.assertEqual(privhelper.main(), 1)


class TestBackground(unittest.TestCase):
    def test_notify(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(background.notify("t", "b"))
        with mock.patch("shutil.which", return_value="/bin/notify-send"), \
             mock.patch("backend.background.subprocess.run") as r:
            self.assertTrue(background.notify("t", "b"))
            r.assert_called_once()
        with mock.patch("shutil.which", return_value="/bin/notify-send"), \
             mock.patch("backend.background.subprocess.run",
                        side_effect=OSError("x")):
            self.assertFalse(background.notify("t", "b"))

    def test_apply_profiles(self):
        ctrls = [{"id": "gip0.0:white:status"}]
        pads = [{"uniq": "S", "phys": "gip0.0/input0"}]
        with mock.patch("backend.background.xone.list_controllers",
                        return_value=ctrls), \
             mock.patch("backend.background.rumble.find_gamepads",
                        return_value=pads), \
             mock.patch("backend.background.profiles.led_of",
                        return_value={"mode": "1", "brightness": 20}), \
             mock.patch("backend.background.xone.set_led",
                        return_value=(True, "ok")) as s:
            applied = set()
            background._apply_profiles(applied)
            self.assertIn("S", applied)
            s.assert_called_once()
            background._apply_profiles(applied)
            self.assertEqual(s.call_count, 1)
        with mock.patch("backend.background.xone.list_controllers",
                        side_effect=RuntimeError("x")):
            background._apply_profiles(set())
        with mock.patch("backend.background.xone.list_controllers",
                        return_value=ctrls), \
             mock.patch("backend.background.rumble.find_gamepads",
                        return_value=pads), \
             mock.patch("backend.background.profiles.led_of",
                        return_value={"mode": "x", "brightness": "x"}), \
             mock.patch("backend.background.xone.set_led",
                        side_effect=RuntimeError("x")):
            background._apply_profiles(set())
        with mock.patch("backend.background.rumble.find_gamepads",
                        side_effect=RuntimeError("x")):
            self.assertEqual(background._pads_by_serial(), {})

    def test_main_loop(self):
        class Loop:
            def __init__(self):
                self.quit_called = False

            def run(self):
                pass

            def quit(self):
                self.quit_called = True

        loop = Loop()
        timers = []

        def add_timer(_secs, cb):
            timers.append(cb)
            return 1

        with mock.patch("backend.background.log.setup"), \
             mock.patch("backend.background.log.get_logger",
                        return_value=mock.Mock()), \
             mock.patch("backend.background.prefs.get_prefs",
                        return_value=mock.Mock()), \
             mock.patch("backend.background.monitor.FsMonitor") as fs, \
             mock.patch("backend.background.monitor.UPowerMonitor") as up, \
             mock.patch("backend.background.GLib.MainLoop",
                        return_value=loop), \
             mock.patch("backend.background.GLib.timeout_add_seconds",
                        side_effect=add_timer), \
             mock.patch("backend.background.GLib.unix_signal_add",
                        return_value=1), \
             mock.patch("backend.background.check_once") as check:
            self.assertEqual(background.main(), 0)
            self.assertTrue(timers)
            self.assertTrue(timers[0]())
            check.assert_called()
            fs.return_value.start.assert_called()
            up.return_value.start.assert_called()
            fs.return_value.stop.assert_called()
            up.return_value.stop.assert_called()
        with mock.patch("backend.background.log.setup"), \
             mock.patch("backend.background.log.get_logger",
                        return_value=mock.Mock()), \
             mock.patch("backend.background.prefs.get_prefs",
                        return_value=mock.Mock()), \
             mock.patch("backend.background.monitor.FsMonitor"), \
             mock.patch("backend.background.monitor.UPowerMonitor"), \
             mock.patch("backend.background.GLib.MainLoop",
                        return_value=Loop()), \
             mock.patch("backend.background.GLib.timeout_add_seconds",
                        side_effect=add_timer), \
             mock.patch("backend.background.GLib.unix_signal_add",
                        return_value=1), \
             mock.patch("backend.background.check_once",
                        side_effect=RuntimeError("x")):
            self.assertEqual(background.main(), 0)
            self.assertTrue(timers[-1]())

    def test_check_once(self):
        pads = [{"uniq": "S", "name": "Pad"}]
        with mock.patch("backend.background.detector.detect") as d, \
             mock.patch("backend.background.rumble.find_gamepads",
                        return_value=pads), \
             mock.patch("backend.background.battery.list_batteries",
                        return_value=[{"serial": "S", "device": "Pad",
                                       "level_en": "low", "level": "baixo",
                                       "percentage": 10, "is_reliable": True}]), \
             mock.patch("backend.background.notify") as n:
            d.return_value = mock.Mock(name="xone")
            st = background.check_once()
            self.assertTrue(n.called)
            background.check_once(st)
        with mock.patch("backend.background.detector.detect",
                        return_value=mock.Mock(name="nenhum")), \
             mock.patch("backend.background.rumble.find_gamepads",
                        return_value=[]), \
             mock.patch("backend.background.battery.list_batteries",
                        side_effect=RuntimeError("x")):
            background.check_once()


if __name__ == "__main__":
    unittest.main()
