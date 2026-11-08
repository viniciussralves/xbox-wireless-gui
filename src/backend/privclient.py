"""Cliente do helper D-Bus privilegiado (polkit dedicado).

Se o serviço instalado estiver disponível, usa a ação polkit
``com.github.xbox-wireless-gui.helper``; caso contrário devolve ``None``
e o chamador cai no fluxo antigo via pkexec/helper.
"""
from __future__ import annotations
import os

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

BUS_NAME = "com.github.xbox-wireless-gui.Helper"
OBJECT_PATH = "/com/github/xboxwirelessgui/Helper"
INTERFACE = "com.github.xboxwirelessgui.Helper1"
UNIT = "/usr/lib/systemd/system/com.github.xbox-wireless-gui.helper.service"


def installed() -> bool:
    return os.path.isfile(UNIT) or os.environ.get("XWG_DBUS_HELPER") == "1"


def _call(method: str, params: GLib.Variant,
          timeout: int = 60) -> tuple[bool, str] | None:
    if not installed():
        return None
    try:
        conn = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        reply = conn.call_sync(
            BUS_NAME, OBJECT_PATH, INTERFACE, method, params,
            GLib.VariantType.new("(bs)"), Gio.DBusCallFlags.NONE,
            timeout, None)
        ok, msg = reply.unpack()
        return bool(ok), str(msg)
    except GLib.Error as e:
        msg = str(e.message or e)
        low = msg.lower()
        if "accessdenied" in low or "access denied" in low \
                or "not authorized" in low or "não autorizado" in low:
            return False, msg
        return None
    except Exception:  # noqa: BLE001
        return None


def set_pairing(enable: bool, path: str):
    return _call("Pairing", GLib.Variant("(ss)",
                                        ("on" if enable else "off", path)))


def set_led(cid: str, mode: str, brightness: str):
    return _call("Led", GLib.Variant("(sss)", (cid, mode, str(brightness))))


def poweroff(path: str, index: int):
    return _call("Poweroff", GLib.Variant("(si)", (path, int(index))))


def set_wakeup(path: str, enable: bool):
    return _call("Wakeup", GLib.Variant("(ss)",
                                        (path, "on" if enable else "off")))


def fix_permissions(user: str):
    return _call("FixPermissions", GLib.Variant("(s)", (user,)))


def xow_action(action: str):
    return _call("Xow", GLib.Variant("(s)", (action,)))
