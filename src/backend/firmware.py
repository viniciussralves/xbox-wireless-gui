"""Firmware do dongle (xone/xow): detecta presença e instala via script oficial.

Histórico dos nomes (não inventar caminhos novos):
- xone antigo (`install/firmware.sh`): extrai `FW_ACC_00U.bin` para
  `/lib/firmware/xow_dongle.bin` (dmesg reclama
  "Direct firmware load for xow_dongle.bin failed" quando falta).
- empacotamentos recentes (ex.: COPR + lpf no Fedora): instalam
  `/usr/lib/firmware/xone_dongle_<PID>.bin` (02e6, 02d1, 02f9, 02fe, 091e…).
"""
from __future__ import annotations
import glob
import os
import shutil
import subprocess

from backend.i18n import _

FIRMWARE_DIRS = ("/usr/lib/firmware", "/lib/firmware")
FIRMWARE_PATTERNS = ("xone_dongle_*.bin", "xow_dongle.bin")
SCRIPTS = {"xone": "xone-get-firmware.sh", "xow": "xow-get-firmware.sh"}
# O script oficial pede Enter (disclaimer da MS) salvo com --skip-disclaimer.
SKIP_FLAG = "--skip-disclaimer"


def installed_files() -> list[str]:
    out: list[str] = []
    for d in FIRMWARE_DIRS:
        if os.path.isdir(d):
            for pat in FIRMWARE_PATTERNS:
                out.extend(sorted(glob.glob(os.path.join(d, pat))))
    # /lib costuma ser symlink de /usr/lib: deduplica pelo nome
    seen: dict[str, str] = {}
    for p in out:
        seen.setdefault(os.path.basename(p), p)
    return sorted(seen.values())


def script_for(driver: str) -> str | None:
    name = SCRIPTS.get(driver or "")
    if name:
        found = shutil.which(name)
        if found:
            return found
    # fallback: qualquer um dos dois scripts no PATH
    for n in SCRIPTS.values():
        found = shutil.which(n)
        if found:
            return found
    return None


def status(driver: str) -> dict:
    files = installed_files()
    script = script_for(driver or "")
    detail_parts = []
    if files:
        sizes = []
        for f in files:
            try:
                sizes.append(f"{os.path.basename(f)} ({os.path.getsize(f) // 1024} KiB)")
            except OSError:
                sizes.append(os.path.basename(f))
        detail_parts.append(_("instalado: {files}").format(files=", ".join(sizes)))
    else:
        detail_parts.append(_("nenhum binário xone_dongle_*.bin/xow_dongle.bin em /usr/lib/firmware"))
    if script:
        detail_parts.append(_("script: {s}").format(s=script))
    else:
        detail_parts.append(_("script xone/xow-get-firmware.sh não está no PATH"))
    state = "installed" if files else "missing"
    return {"state": state, "files": files, "script": script,
            "detail": " • ".join(detail_parts)}


def install(driver: str) -> tuple[bool, str]:
    """Roda o script oficial com pkexec (pede o disclaimer da MS antes, na UI)."""
    script = script_for(driver or "")
    if not script:
        return False, _("script de firmware não encontrado (instale o xone/xow primeiro)")
    if shutil.which("pkexec") is None:
        return False, _("pkexec não encontrado")
    try:
        r = subprocess.run(["pkexec", script, SKIP_FLAG],
                           capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return False, _("timeout instalando firmware (>10min)")
    except OSError as e:
        return False, _("falha ao chamar firmware: {e}").format(e=e)
    out = (r.stdout or "") + (r.stderr or "")
    tail = "\n".join(out.strip().splitlines()[-5:]) if out.strip() else ""
    if r.returncode == 0:
        # revalida: o .bin apareceu?
        files = installed_files()
        if files:
            return True, _("firmware instalado: {files}").format(
                files=", ".join(os.path.basename(f) for f in files))
        return True, _("script concluiu") + (f" — {tail}" if tail else "")
    return False, tail or _("script saiu com código {c}").format(c=r.returncode)
