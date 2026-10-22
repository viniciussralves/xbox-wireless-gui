"""Controles Bluetooth (ex.: xpadneo): identifica e desconecta ("esquecer").

O evdev expõe o MAC no campo `phys` do dispositivo
(ex.: "AA:BB:CC:DD:EE:FF"), o que identifica com segurança qual
dispositivo Bluetooth desconectar — sem risco de pegar o dongle xone.
"""
from __future__ import annotations
import re
import shutil
import subprocess

from backend.i18n import _

_MAC_RE = re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")


def phys_of(path: str) -> str | None:
    try:
        from evdev import InputDevice
        dev = InputDevice(path)
        try:
            return dev.phys or None
        finally:
            try:
                dev.close()
            except OSError:
                pass
    except (ImportError, OSError):
        return None


def mac_of(path: str) -> str | None:
    phys = phys_of(path) or ""
    m = _MAC_RE.search(phys)
    return m.group(0).upper() if m else None


def is_bluetooth(path: str) -> bool:
    return mac_of(path) is not None


def disconnect(path: str) -> tuple[bool, str]:
    mac = mac_of(path)
    if not mac:
        return False, _("dispositivo não é Bluetooth (sem MAC no phys)")
    bt = shutil.which("bluetoothctl")
    if not bt:
        return False, _("bluetoothctl não encontrado")
    try:
        r = subprocess.run([bt, "disconnect", mac],
                           capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return False, _("timeout no bluetoothctl")
    except OSError as e:
        return False, _("falha ao chamar bluetoothctl: {e}").format(e=e)
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if r.returncode == 0 and "uccess" in out:
        return True, _("{mac} desconectado").format(mac=mac)
    return False, out.splitlines()[-1] if out else _("bluetoothctl saiu {c}").format(c=r.returncode)
