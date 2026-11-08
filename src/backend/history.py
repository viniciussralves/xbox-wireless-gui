"""Histórico de bateria dos controles via UPower (GetHistory).

O UPower mantém histórico por dispositivo; usamos o native_path (ex.:
``gip0.0``) para achar o objeto e pedir as amostras. Sem UPower/D-Bus,
retorna lista vazia — a UI mostra “sem histórico”.
"""
from __future__ import annotations
import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

UPOWER = "org.freedesktop.UPower"
UPOWER_PATH = "/org/freedesktop/UPower"
DEVICE_IFACE = "org.freedesktop.UPower.Device"


def _client():
    gi.require_version("UPowerGlib", "1.0")
    from gi.repository import UPowerGlib
    return UPowerGlib.Client.new()


def device_path(native_path: str) -> str | None:
    if not native_path:
        return None
    try:
        client = _client()
        for dev in client.get_devices():
            if (dev.props.native_path or "").strip() == native_path:
                return dev.get_object_path()
    except Exception:  # noqa: BLE001
        return None
    return None


def _call(native_path: str, kind: str, timespan: int,
          resolution: int) -> list[tuple[int, float, int]]:
    path = device_path(native_path)
    if not path:
        return []
    conn = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    params = GLib.Variant("(suu)", (kind, int(timespan), int(resolution)))
    reply = conn.call_sync(
        UPOWER, path, DEVICE_IFACE, "GetHistory", params,
        GLib.VariantType.new("(a(udu))"),
        Gio.DBusCallFlags.NONE, 10, None)
    return list(reply.unpack()[0])


def get_history(native_path: str, hours: int = 24,
                resolution: int = 300,
                kind: str = "percentage") -> list[dict]:
    try:
        span = max(60, min(7 * 24 * 3600, int(hours) * 3600))
        res = max(60, min(3600, int(resolution)))
        rows = _call(native_path, kind, span, res)
    except Exception:  # noqa: BLE001
        return []
    return [{"time": int(t), "value": float(v), "state": int(s)}
            for t, v, s in rows]


def summarize(rows: list[dict]) -> dict:
    if not rows:
        return {"count": 0, "min": -1, "max": -1, "last": -1, "first": -1}
    vals = [r["value"] for r in rows]
    return {"count": len(rows), "min": min(vals), "max": max(vals),
            "last": vals[-1], "first": vals[0]}
