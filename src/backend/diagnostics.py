"""Relatório de diagnóstico para suporte (copiável e sem dados sensíveis).

Reúne o estado do kernel, driver, dongle, firmware, permissões, UPower,
evdev e áudio. O objetivo é transformar “não funciona” em um relatório
que o mantenedor consegue ler sem pedir 10 comandos ao usuário.
"""
from __future__ import annotations
import os
import platform
import subprocess

from backend import __version__, battery, detector, firmware, permissions
from backend import audio, rumble, xow


def _read(path: str, default: str = "") -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return default


def _cmd(args: list[str], timeout: int = 5) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return ((r.stdout or "") + (r.stderr or "")).strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def os_release() -> dict:
    out: dict[str, str] = {}
    for line in _read("/etc/os-release").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v.strip().strip('"')
    return out


def secure_boot() -> str:
    txt = _cmd(["mokutil", "--sb-state"], timeout=3).lower()
    if "enabled" in txt:
        return "enabled"
    if "disabled" in txt:
        return "disabled"
    return "desconhecido"


def module_path(name: str = "xone_dongle") -> str:
    base = f"/lib/modules/{platform.release()}"
    for root, _dirs, files in os.walk(os.path.join(base, "extra")):
        for f in files:
            if f.startswith(name + ".ko"):
                return os.path.join(root, f)
    return _cmd(["modinfo", "-n", name], timeout=3)


def evdev_summary() -> list[dict]:
    out = []
    try:
        for p in rumble.find_gamepads():
            out.append({"name": p.get("name", ""), "path": p.get("path", ""),
                        "phys": p.get("phys", ""),
                        "has_rumble": p.get("has_rumble", False)})
    except Exception:  # noqa: BLE001
        pass
    return out


def collect() -> dict:
    """Coleta tudo; cada bloco é isolado para um erro não derrubar o resto."""
    info = detector.detect()
    data: dict = {
        "app_version": __version__,
        "kernel": platform.release(),
        "os": os_release(),
        "driver": {
            "name": info.name,
            "state": info.state,
            "detail": info.detail,
            "xone_loaded": info.xone_loaded,
            "xone_version": info.xone_version,
            "xow_installed": info.xow_installed,
            "xow_active": info.xow_active,
            "module_path": module_path(),
            "secure_boot": secure_boot(),
        },
        "dongles": info.usb_dongles,
        "dongle_sysfs": info.dongle_sysfs,
        "active_clients": {},
        "firmware": {},
        "permissions": {},
        "xow": {},
        "audio": {},
        "evdev": [],
        "batteries": [],
    }
    try:
        data["active_clients"] = detector.dongle_active_clients(info.dongle_sysfs)
        data["active_clients"].pop("raw", None)
    except Exception:  # noqa: BLE001
        pass
    try:
        data["firmware"] = firmware.status(info.name)
        data["firmware"].pop("files", None)
    except Exception:  # noqa: BLE001
        pass
    try:
        data["permissions"] = permissions.status()
    except Exception:  # noqa: BLE001
        pass
    try:
        data["xow"] = {"active": xow.service_active(),
                       "hint": xow.firmware_hint()}
    except Exception:  # noqa: BLE001
        pass
    try:
        data["audio"] = audio.status()
    except Exception:  # noqa: BLE001
        pass
    try:
        data["evdev"] = evdev_summary()
    except Exception:  # noqa: BLE001
        pass
    try:
        data["batteries"] = [
            {k: b.get(k) for k in ("device", "percentage", "level",
                                   "level_en", "serial", "power_supply")}
            for b in battery.list_batteries()
        ]
    except Exception:  # noqa: BLE001
        pass
    return data


def format_markdown(data: dict | None = None) -> str:
    d = data or collect()
    osd = d.get("os", {})
    drv = d.get("driver", {})
    ac = d.get("active_clients", {})
    fw = d.get("firmware", {})
    perm = d.get("permissions", {})
    lines = [
        "## Diagnóstico — Xbox Wireless GUI",
        f"- App: {d.get('app_version', '?')}",
        f"- Kernel: {d.get('kernel', '?')}",
        f"- Distro: {osd.get('PRETTY_NAME', '?')}",
        f"- Driver: {drv.get('name', '?')} ({drv.get('state', '?')})",
        f"- xone carregado: {drv.get('xone_loaded')} versão {drv.get('xone_version') or '?'}",
        f"- Secure Boot: {drv.get('secure_boot', '?')}",
        f"- Módulo: {drv.get('module_path') or 'não encontrado'}",
        f"- Dongle sysfs: {d.get('dongle_sysfs') or 'nenhum'}",
        f"- Clientes ativos: {ac.get('count', '?')} slots={sorted(ac.get('slots', []))}",
        f"- xow: instalado={drv.get('xow_installed')} ativo={drv.get('xow_active')}",
        f"- Firmware: {fw.get('state', '?')} — {fw.get('detail', '?')}",
        f"- Permissões: {perm.get('detail', '?')}",
        "",
        "### Dongles USB",
    ]
    dongles = d.get("dongles") or []
    if dongles:
        for u in dongles:
            lines.append(f"- {u.get('id')} em {u.get('path')} "
                         f"(driver={u.get('driver') or 'nenhum'})")
    else:
        lines.append("- nenhum adaptador 045e:02e6/02d1/02f9/02fe/091e")
    lines += ["", "### evdev"]
    for e in d.get("evdev") or []:
        lines.append(f"- {e.get('name')} ({e.get('path')}) phys={e.get('phys')} "
                     f"rumble={e.get('has_rumble')}")
    lines += ["", "### Baterias"]
    for b in d.get("batteries") or []:
        lines.append(f"- {b.get('device')}: {b.get('percentage')}% "
                     f"nível={b.get('level')} serial={b.get('serial')}")
    lines += ["", "### Áudio (xone)"]
    aud = d.get("audio") or {}
    lines.append(f"- cards={aud.get('cards') or []}")
    lines.append(f"- sinks={aud.get('sinks') or []}")
    lines.append(f"- sources={aud.get('sources') or []}")
    return "\n".join(lines) + "\n"
