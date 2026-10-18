"""Preferências persistidas via GSettings, com fallback em memória.

O schema `com.github.xbox-wireless-gui` é instalado em
`/usr/share/glib-2.0/schemas`. No checkout dev (schema não instalado),
usa fallback em memória para nunca quebrar o `./run.sh`.
"""
from __future__ import annotations

SCHEMA_ID = "com.github.xbox-wireless-gui"

DEFAULTS = {
    "rumble-duration": 600,   # ms, 100-2000
    "rumble-strong": 50,      # %, 0-100
    "rumble-weak": 50,        # %, 0-100
    "tester-deadzone": 0.08,  # 0.0-0.5
    "selected-dongle": "",    # sysfs do dongle preferido ("": automático)
    "check-updates": True,
}


class Prefs:
    def __init__(self) -> None:
        self._settings = None
        self._mem = dict(DEFAULTS)
        # Gio.Settings.new() com schema ausente aborta o processo
        # (GLib-GIO-ERROR, não capturável): verifica antes.
        try:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio
            source = Gio.SettingsSchemaSource.get_default()
            if source is not None and source.lookup(SCHEMA_ID, True) is not None:
                self._settings = Gio.Settings.new(SCHEMA_ID)
        except Exception:  # noqa: BLE001
            self._settings = None

    @property
    def backend(self) -> str:
        return "gsettings" if self._settings is not None else "memory"

    def get_int(self, key: str) -> int:
        if self._settings is not None:
            try:
                return int(self._settings.get_int(key))
            except Exception:  # noqa: BLE001
                pass
        return int(self._mem.get(key, DEFAULTS[key]))

    def get_double(self, key: str) -> float:
        if self._settings is not None:
            try:
                return float(self._settings.get_double(key))
            except Exception:  # noqa: BLE001
                pass
        return float(self._mem.get(key, DEFAULTS[key]))

    def get_string(self, key: str) -> str:
        if self._settings is not None:
            try:
                return str(self._settings.get_string(key))
            except Exception:  # noqa: BLE001
                pass
        return str(self._mem.get(key, DEFAULTS[key]))

    def get_bool(self, key: str) -> bool:
        if self._settings is not None:
            try:
                return bool(self._settings.get_boolean(key))
            except Exception:  # noqa: BLE001
                pass
        return bool(self._mem.get(key, DEFAULTS[key]))

    def set_int(self, key: str, value: int) -> None:
        self._mem[key] = int(value)
        if self._settings is not None:
            try:
                self._settings.set_int(key, int(value))
            except Exception:  # noqa: BLE001
                pass

    def set_double(self, key: str, value: float) -> None:
        self._mem[key] = float(value)
        if self._settings is not None:
            try:
                self._settings.set_double(key, float(value))
            except Exception:  # noqa: BLE001
                pass

    def set_string(self, key: str, value: str) -> None:
        self._mem[key] = str(value)
        if self._settings is not None:
            try:
                self._settings.set_string(key, str(value))
            except Exception:  # noqa: BLE001
                pass

    def set_bool(self, key: str, value: bool) -> None:
        self._mem[key] = bool(value)
        if self._settings is not None:
            try:
                self._settings.set_boolean(key, bool(value))
            except Exception:  # noqa: BLE001
                pass


_prefs: Prefs | None = None


def get_prefs() -> Prefs:
    global _prefs
    if _prefs is None:
        _prefs = Prefs()
    return _prefs


def rumble_magnitudes(prefs: Prefs | None = None) -> tuple[int, int]:
    """(strong, weak) em 0-0xFFFF a partir dos % persistidos."""
    p = prefs or get_prefs()
    conv = lambda v: max(0, min(0xFFFF, round(v / 100 * 0xFFFF)))
    return conv(p.get_int("rumble-strong")), conv(p.get_int("rumble-weak"))
