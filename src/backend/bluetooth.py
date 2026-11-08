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


def _bt(mac: str) -> str | None:
    if not _MAC_RE.fullmatch(mac or ""):
        return None
    return mac.upper()


def _bluetoothctl(*args: str, timeout: int = 30) -> tuple[bool, str]:
    bt = shutil.which("bluetoothctl")
    if not bt:
        return False, _("bluetoothctl não encontrado")
    try:
        r = subprocess.run([bt, *args], capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, _("timeout no bluetoothctl")
    except OSError as e:
        return False, _("falha ao chamar bluetoothctl: {e}").format(e=e)
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if r.returncode == 0 and "uccess" in out:
        return True, out
    return False, out.splitlines()[-1] if out else _("bluetoothctl saiu {c}").format(c=r.returncode)


def paired_devices() -> list[dict]:
    """Controles/headsats já pareados no BlueZ."""
    bt = shutil.which("bluetoothctl")
    if not bt:
        return []
    try:
        r = subprocess.run([bt, "devices", "Paired"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return []
    out = []
    for line in (r.stdout or "").splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3 and parts[0] == "Device":
            out.append({"mac": parts[1].upper(), "name": parts[2],
                        "xbox": bool(re.search(r"xbox|controller|gamepad|headset",
                                               parts[2], re.I))})
    return out


def xbox_devices() -> list[dict]:
    return [d for d in paired_devices() if d["xbox"]]


def pair(mac: str) -> tuple[bool, str]:
    mac = _bt(mac)
    if not mac:
        return False, _("MAC inválido")
    ok, out = _bluetoothctl("pair", mac, timeout=60)
    return ok, out or _("{mac} pareado").format(mac=mac)


def trust(mac: str) -> tuple[bool, str]:
    mac = _bt(mac)
    if not mac:
        return False, _("MAC inválido")
    ok, out = _bluetoothctl("trust", mac)
    return ok, out or _("{mac} confiável").format(mac=mac)


def connect(mac: str) -> tuple[bool, str]:
    mac = _bt(mac)
    if not mac:
        return False, _("MAC inválido")
    ok, out = _bluetoothctl("connect", mac, timeout=45)
    return ok, out or _("{mac} conectado").format(mac=mac)


def remove(mac: str) -> tuple[bool, str]:
    mac = _bt(mac)
    if not mac:
        return False, _("MAC inválido")
    ok, out = _bluetoothctl("remove", mac)
    return ok, out or _("{mac} removido").format(mac=mac)


def scan(timeout: int = 8) -> tuple[bool, str]:
    try:
        secs = max(1, min(30, int(timeout)))
    except (TypeError, ValueError):
        secs = 8
    ok, out = _bluetoothctl("--timeout", str(secs), "scan", "on",
                            timeout=secs + 10)
    return ok, out or _("varredura concluída")


def disconnect(path: str) -> tuple[bool, str]:
    mac = mac_of(path)
    if not mac:
        return False, _("dispositivo não é Bluetooth (sem MAC no phys)")
    ok, out = _bluetoothctl("disconnect", mac)
    if ok:
        return True, _("{mac} desconectado").format(mac=mac)
    return False, out
