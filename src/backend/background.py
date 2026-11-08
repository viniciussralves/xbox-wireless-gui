"""Modo segundo plano: notificações + perfis de LED sem janela aberta.

Instalado como serviço de usuário (``xbox-wireless-gui --background``).
Usa monitoramento por eventos com fallback periódico.
"""
from __future__ import annotations
import shutil
import signal
import subprocess
import time

import gi

gi.require_version("Gio", "2.0")
from gi.repository import GLib  # noqa: E402

from backend import battery, detector, log, monitor, prefs, profiles, rumble, xone
from backend.i18n import _

INTERVAL = 30


def notify(title: str, body: str = "") -> bool:
    exe = shutil.which("notify-send")
    if not exe:
        log.get_logger("background").info("%s: %s", title, body)
        return False
    try:
        subprocess.run([exe, title, body], timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def _pads_by_serial() -> dict[str, dict]:
    out = {}
    try:
        for p in rumble.find_gamepads():
            serial = (p.get("uniq") or "").strip()
            if serial:
                out[serial] = p
    except Exception:  # noqa: BLE001
        pass
    return out


def _apply_profiles(applied: set[str]):
    try:
        ctrls = xone.list_controllers()
    except Exception:  # noqa: BLE001
        return
    pads = _pads_by_serial()
    for c in ctrls:
        cid = c.get("id") or ""
        base = cid.split(":")[0]
        serial = ""
        for s, p in pads.items():
            if (p.get("phys") or "").split("/")[0] == base:
                serial = s
                break
        if not serial or serial in applied:
            continue
        led = profiles.led_of(serial)
        mode = str(led.get("mode") or "")
        try:
            bright = int(led.get("brightness", -1))
        except (TypeError, ValueError):
            bright = -1
        if mode in xone.VALID_LED_MODES and bright >= 0:
            try:
                xone.set_led(cid, mode, str(bright))
                applied.add(serial)
                log.get_logger("background").info("perfil LED aplicado em %s", cid)
            except Exception:  # noqa: BLE001
                pass


def check_once(state: dict | None = None) -> dict:
    st = state if state is not None else {
        "connected": None, "applied": set(), "low": set(), "last_check": 0.0}
    info = detector.detect()
    pads = rumble.find_gamepads()
    serials = {(p.get("uniq") or p.get("name") or "") for p in pads}
    serials.discard("")
    if st["connected"] is not None:
        added = serials - st["connected"]
        removed = st["connected"] - serials
        if added:
            notify(_("Controle conectado"), ", ".join(sorted(added)))
        if removed:
            notify(_("Controle desconectado"), ", ".join(sorted(removed)))
    st["connected"] = serials
    if info.name == "xone":
        _apply_profiles(st["applied"])
    try:
        for b in battery.list_batteries():
            key = b.get("serial") or b.get("device") or "?"
            level = (b.get("level_en") or "").lower()
            low = level in ("low", "critical")
            if b.get("is_reliable"):
                try:
                    low = int(b.get("percentage", 100)) <= 20
                except (TypeError, ValueError):
                    low = False
            if low and key not in st["low"]:
                st["low"].add(key)
                notify(_("Bateria baixa"),
                       _("{d}: {l}").format(d=b.get("device", "?"),
                                            l=b.get("level") or "?"))
            elif not low:
                st["low"].discard(key)
    except Exception:  # noqa: BLE001
        pass
    st["last_check"] = time.time()
    return st


def main() -> int:
    log.setup()
    logger = log.get_logger("background")
    p = prefs.get_prefs()
    st = {"connected": None, "applied": set(), "low": set(), "last_check": 0.0}

    def tick():
        try:
            check_once(st)
        except Exception as e:  # noqa: BLE001
            logger.warning("check falhou: %s", e)
        return True

    loop = GLib.MainLoop()
    fs = monitor.FsMonitor(lambda: tick())
    fs.start()
    up = monitor.UPowerMonitor(lambda: tick())
    up.start()
    GLib.timeout_add_seconds(INTERVAL, tick)
    for sig in (signal.SIGTERM, signal.SIGINT):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: loop.quit() or False)
    logger.info("background iniciado (intervalo %ss, notificações=%s)",
                INTERVAL, p.get_bool("notifications"))
    try:
        loop.run()
    finally:
        fs.stop()
        up.stop()
    return 0
