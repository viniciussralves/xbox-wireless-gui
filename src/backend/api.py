"""API D-Bus de sessão para controlar/consultar o app.

Interface ``com.github.xbox-wireless-gui.Control1`` no caminho
``/com/github/xbox-wireless-gui/Control``. Permite Waybar, Stream Deck,
scripts e extensões sem depender da janela aberta.
"""
from __future__ import annotations
import json

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

INTERFACE = "com.github.xboxwirelessgui.Control1"
OBJECT_PATH = "/com/github/xboxwirelessgui/Control"

INTROSPECTION_XML = """<node>
  <interface name="com.github.xboxwirelessgui.Control1">
    <method name="GetStatus"><arg type="s" direction="out"/></method>
    <method name="Refresh"><arg type="b" direction="out"/></method>
    <method name="Present"><arg type="b" direction="out"/></method>
    <method name="SetPairing"><arg type="b" direction="in"/><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
    <method name="SetLed"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
    <method name="Poweroff"><arg type="i" direction="in"/><arg type="b" direction="out"/><arg type="s" direction="out"/></method>
  </interface>
</node>"""


class Api:
    def __init__(self, callbacks: dict):
        self.callbacks = callbacks

    def _call(self, name: str, args=()):
        fn = self.callbacks.get(name)
        if fn is None:
            return GLib.Variant("(bs)", (False, f"método {name} indisponível"))
        return fn(*args)

    def handle_method_call(self, _conn, _sender, _path, _iface,
                           method: str, params, invocation=None):
        result = self._dispatch(method, params)
        if invocation is not None:
            invocation.return_value(result)
            return None
        return result

    def _dispatch(self, method: str, params):
        try:
            if method == "GetStatus":
                data = self.callbacks["status"]()
                if not isinstance(data, str):
                    data = json.dumps(data, ensure_ascii=False, default=str)
                return GLib.Variant("(s)", (data,))
            if method == "Refresh":
                fn = self.callbacks.get("refresh")
                fn() if fn else None
                return GLib.Variant("(b)", (fn is not None,))
            if method == "Present":
                fn = self.callbacks.get("present")
                fn() if fn else None
                return GLib.Variant("(b)", (fn is not None,))
            if method == "SetPairing":
                enabled = bool(params.unpack()[0])
                return GLib.Variant("(bs)", self._call("pairing", (enabled,)))
            if method == "SetLed":
                cid, mode, bright = params.unpack()
                return GLib.Variant("(bs)", self._call("led", (cid, mode, bright)))
            if method == "Poweroff":
                index = int(params.unpack()[0])
                return GLib.Variant("(bs)", self._call("poweroff", (index,)))
        except Exception as e:  # noqa: BLE001
            return GLib.Variant("(bs)", (False, str(e)))
        return GLib.Variant("(bs)", (False, f"método {method} desconhecido"))


def register(connection: Gio.DBusConnection, callbacks: dict) -> Api:
    api = Api(callbacks)
    node = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)
    connection.register_object(OBJECT_PATH, node.interfaces[0],
                               api.handle_method_call, None, None)
    return api
