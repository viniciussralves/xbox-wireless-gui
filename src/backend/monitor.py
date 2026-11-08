"""Atualização orientada a eventos (udev/devtmpfs + UPower).

O polling continua como fallback, mas conexões/desconexões de controles
e mudanças de bateria disparam um refresh imediato. Em sysfs o inotify
pode não funcionar; nesse caso o timeout periódico continua valendo.
"""
from __future__ import annotations
import os

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

DEFAULT_PATHS = (
    "/dev/input",
    "/sys/class/leds",
    "/sys/bus/usb/drivers/xone-dongle",
)


class FsMonitor:
    """Monitora diretórios com Gio.FileMonitor e faz debounce do callback."""

    def __init__(self, callback, debounce_ms: int = 350,
                 paths: tuple[str, ...] | list[str] | None = None):
        self.callback = callback
        self.debounce_ms = max(50, int(debounce_ms))
        self.paths = list(paths or DEFAULT_PATHS)
        self._monitors: list[Gio.FileMonitor] = []
        self._timeout_id: int | None = None
        self._active = False

    def start(self) -> int:
        if self._active:
            return len(self._monitors)
        self._active = True
        for path in self.paths:
            if not os.path.isdir(path):
                continue
            try:
                mon = Gio.File.new_for_path(path).monitor_directory(
                    Gio.FileMonitorFlags.WATCH_MOVES, None)
                mon.connect("changed", self._on_changed)
                self._monitors.append(mon)
            except Exception:  # noqa: BLE001
                continue
        return len(self._monitors)

    def _on_changed(self, *_args):
        if not self._active:
            return
        if self._timeout_id is not None:
            try:
                GLib.source_remove(self._timeout_id)
            except Exception:  # noqa: BLE001
                pass
        self._timeout_id = GLib.timeout_add(self.debounce_ms, self._fire)

    def _fire(self):
        self._timeout_id = None
        if self._active:
            try:
                self.callback()
            except Exception:  # noqa: BLE001
                pass
        return False

    def stop(self):
        self._active = False
        if self._timeout_id is not None:
            try:
                GLib.source_remove(self._timeout_id)
            except Exception:  # noqa: BLE001
                pass
            self._timeout_id = None
        for mon in self._monitors:
            try:
                mon.cancel()
            except Exception:  # noqa: BLE001
                pass
        self._monitors.clear()


def _upower_client():
    gi.require_version("UPowerGlib", "1.0")
    from gi.repository import UPowerGlib
    return UPowerGlib.Client.new()


class UPowerMonitor:
    """Escuta sinais do UPower para bateria/estado sem polling."""

    def __init__(self, callback):
        self.callback = callback
        self._client = None
        self._ids: list[int] = []

    def start(self) -> bool:
        try:
            self._client = _upower_client()
            for sig in ("device-added", "device-removed", "device-changed"):
                try:
                    self._ids.append(self._client.connect(
                        sig, lambda *a: self._emit()))
                except Exception:  # noqa: BLE001
                    continue
            return True
        except Exception:  # noqa: BLE001
            self._client = None
            return False

    def _emit(self):
        try:
            self.callback()
        except Exception:  # noqa: BLE001
            pass

    def stop(self):
        client = self._client
        self._client = None
        if client is None:
            return
        for cid in self._ids:
            try:
                client.disconnect(cid)
            except Exception:  # noqa: BLE001
                pass
        self._ids.clear()
