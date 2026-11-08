#!/usr/bin/env python3
"""Helper D-Bus root com autorização polkit dedicada.

Roda como serviço de sistema (systemd Type=dbus). Cada chamada é
autorizada pela ação ``com.github.xbox-wireless-gui.helper`` e então
delegada ao helper shell já auditado, com argumentos fixos/validados.
"""
from __future__ import annotations
import os
import re
import subprocess
import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

BUS_NAME = "com.github.xbox-wireless-gui.Helper"
OBJECT_PATH = "/com/github/xboxwirelessgui/Helper"
INTERFACE = "com.github.xboxwirelessgui.Helper1"
ACTION_ID = "com.github.xbox-wireless-gui.helper"
HELPER = "/usr/libexec/xbox-wireless-gui-helper"
_LED_RE = re.compile(r"^[A-Za-z0-9._:+\-]+$")
_USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_MODES = {"0", "1", "2", "3", "4", "8", "9"}

INTROSPECTION_XML = """<node>
  <interface name="com.github.xboxwirelessgui.Helper1">
    <method name="Ping"><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
    <method name="Pairing"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
    <method name="Led"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
    <method name="Poweroff"><arg type="s" direction="in"/><arg type="i" direction="in"/><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
    <method name="Wakeup"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
    <method name="FixPermissions"><arg type="s" direction="in"/><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
    <method name="Xow"><arg type="s" direction="in"/><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
  </interface>
</node>"""


def _helper(*args: str) -> tuple[bool, str]:
    try:
        r = subprocess.run([HELPER, *args], capture_output=True,
                           text=True, timeout=120)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return r.returncode == 0, out or ("ok" if r.returncode == 0 else "erro")
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)


def _authorized(conn: Gio.DBusConnection, sender: str) -> bool:
    try:
        pid_reply = conn.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus",
            "org.freedesktop.DBus", "GetConnectionUnixProcessID",
            GLib.Variant("(s)", (sender,)), GLib.VariantType.new("(u)"),
            Gio.DBusCallFlags.NONE, 5, None)
        pid = int(pid_reply.unpack()[0])
        params = GLib.Variant(
            "(sa{sv}sa{ss}us)",
            ("unix-process", {"pid": GLib.Variant("u", pid)},
             ACTION_ID, {}, 1, ""))
        reply = conn.call_sync(
            "org.freedesktop.PolicyKit1", "/org/freedesktop/PolicyKit1/Authority",
            "org.freedesktop.PolicyKit1.Authority", "CheckAuthorization",
            params, GLib.VariantType.new("(bba{ss})"),
            Gio.DBusCallFlags.NONE, 10, None)
        return bool(reply.unpack()[0])
    except Exception:  # noqa: BLE001
        return False


def _bad_path(path: str, suffix: str) -> bool:
    return (not path or ".." in path or not path.endswith(suffix))


def handle(conn, sender, _path, _iface, method: str, params,
           invocation=None):
    result = _dispatch(conn, sender, method, params)
    if invocation is not None:
        invocation.return_value(result)
        return None
    return result


def _dispatch(conn, sender, method: str, params):
    if method == "Ping":
        return GLib.Variant("(bs)", (True, "pong"))
    if not _authorized(conn, sender):
        return GLib.Variant("(bs)", (False, "não autorizado pelo polkit"))
    try:
        if method == "Pairing":
            state, path = params.unpack()
            if state not in ("on", "off") or _bad_path(path, "/pairing"):
                return GLib.Variant("(bs)", (False, "parâmetros inválidos"))
            return GLib.Variant("(bs)", _helper("pairing", state, path))
        if method == "Led":
            cid, mode, brightness = params.unpack()
            if not _LED_RE.match(cid or "") or mode not in _MODES \
                    or not str(brightness).isdigit():
                return GLib.Variant("(bs)", (False, "parâmetros inválidos"))
            return GLib.Variant("(bs)", _helper("led", cid, mode,
                                                str(brightness)))
        if method == "Poweroff":
            path, index = params.unpack()
            if _bad_path(path, "/poweroff") or not -1 <= int(index) <= 15:
                return GLib.Variant("(bs)", (False, "parâmetros inválidos"))
            return GLib.Variant("(bs)", _helper("poweroff", path, str(index)))
        if method == "Wakeup":
            path, state = params.unpack()
            if _bad_path(path, "/power/wakeup") or state not in ("on", "off"):
                return GLib.Variant("(bs)", (False, "parâmetros inválidos"))
            return GLib.Variant("(bs)", _helper("wakeup", path, state))
        if method == "FixPermissions":
            user = params.unpack()[0]
            if not _USER_RE.match(user or ""):
                return GLib.Variant("(bs)", (False, "usuário inválido"))
            return GLib.Variant("(bs)", _helper("permissions", user))
        if method == "Xow":
            action = params.unpack()[0]
            if action not in ("start", "stop", "restart", "enable", "disable"):
                return GLib.Variant("(bs)", (False, "ação inválida"))
            return GLib.Variant("(bs)", _helper("xow", action))
    except Exception as e:  # noqa: BLE001
        return GLib.Variant("(bs)", (False, str(e)))
    return GLib.Variant("(bs)", (False, f"método {method} desconhecido"))


def register(conn: Gio.DBusConnection):
    node = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)
    conn.register_object(OBJECT_PATH, node.interfaces[0], handle, None, None)


def main() -> int:
    if os.geteuid() != 0:
        print("privhelper precisa rodar como root", file=sys.stderr)
        return 1
    conn = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    Gio.bus_own_name_on_connection(conn, BUS_NAME,
                                   Gio.BusNameOwnerFlags.NONE, None, None)
    register(conn)
    GLib.MainLoop().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
