"""Firmware do dongle (xone/xow): detecta presença e instala via script oficial.

Histórico dos nomes (não inventar caminhos novos):
- xone antigo (`install/firmware.sh`): extrai `FW_ACC_00U.bin` para
  `/lib/firmware/xow_dongle.bin` (dmesg reclama
  "Direct firmware load for xow_dongle.bin failed" quando falta).
- empacotamentos recentes (ex.: COPR + lpf no Fedora): instalam
  `/usr/lib/firmware/xone_dongle_<PID>.bin` (02e6, 02d1, 02f9, 02fe, 091e…).
- xow usa `xow_dongle.bin`.

Só executamos scripts instalados em diretórios root-owned e não
graváveis por grupo/outros. Nunca usamos um script encontrado no
checkout do usuário ou em `~/.local/bin`.
"""
from __future__ import annotations
import glob
import os
import shutil
import subprocess

from backend.i18n import _

FIRMWARE_DIRS = ("/usr/lib/firmware", "/lib/firmware")
FIRMWARE_PATTERNS = ("xone_dongle_*.bin", "xow_dongle.bin")
DRIVER_PATTERNS = {
    "xone": ("xone_dongle_*.bin", "xow_dongle.bin"),
    "xow": ("xow_dongle.bin",),
}
SCRIPTS = {"xone": "xone-get-firmware.sh", "xow": "xow-get-firmware.sh"}
TRUSTED_BIN_DIRS = ("/usr/bin", "/usr/sbin", "/usr/libexec",
                    "/usr/local/bin", "/usr/local/sbin")
# O script oficial pede Enter (disclaimer da MS) salvo com --skip-disclaimer.
SKIP_FLAG = "--skip-disclaimer"


def _trusted_script(path: str | None) -> str | None:
    """Resolve e valida um script que será executado como root."""
    if not path:
        return None
    real = os.path.realpath(path)
    if not os.path.isfile(real) or not os.access(real, os.X_OK):
        return None
    if not any(real.startswith(d + os.sep) for d in TRUSTED_BIN_DIRS):
        return None
    try:
        st = os.stat(real)
        if st.st_uid != 0 or st.st_mode & 0o022:
            return None
        # o arquivo e todos os diretórios até / precisam ser root-owned
        # e não graváveis por grupo/outros (evita troca por rename)
        parent = os.path.dirname(real)
        while parent not in ("", "/"):
            pst = os.stat(parent)
            if pst.st_uid != 0 or pst.st_mode & 0o022:
                return None
            parent = os.path.dirname(parent)
    except OSError:
        return None
    return real


def _pkexec() -> str | None:
    for p in ("/usr/bin/pkexec", "/bin/pkexec"):
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def installed_files(driver: str | None = None) -> list[str]:
    patterns = DRIVER_PATTERNS.get(driver or "", FIRMWARE_PATTERNS)
    out: list[str] = []
    for d in FIRMWARE_DIRS:
        if os.path.isdir(d):
            for pat in patterns:
                out.extend(sorted(glob.glob(os.path.join(d, pat))))
    # /lib costuma ser symlink de /usr/lib: deduplica pelo nome
    seen: dict[str, str] = {}
    for p in out:
        seen.setdefault(os.path.basename(p), p)
    return sorted(seen.values())


def script_for(driver: str) -> str | None:
    name = SCRIPTS.get(driver or "")
    if not name:
        return None
    return _trusted_script(shutil.which(name))


def status(driver: str) -> dict:
    files = installed_files(driver)
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
        detail_parts.append(_("nenhum binário de firmware para {driver}").format(
            driver=driver or "xone/xow"))
    if script:
        detail_parts.append(_("script: {s}").format(s=script))
    else:
        detail_parts.append(_("script xone/xow-get-firmware.sh não está no PATH seguro"))
    state = "installed" if files else "missing"
    return {"state": state, "files": files, "script": script,
            "detail": " • ".join(detail_parts)}


def install(driver: str) -> tuple[bool, str]:
    """Roda o script oficial com pkexec (pede o disclaimer da MS antes, na UI)."""
    script = script_for(driver or "")
    if not script:
        return False, _("script de firmware não encontrado (instale o xone/xow primeiro)")
    pkexec = _pkexec()
    if not pkexec:
        return False, _("pkexec não encontrado")
    try:
        r = subprocess.run([pkexec, script, SKIP_FLAG],
                           capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return False, _("timeout instalando firmware (>10min)")
    except OSError as e:
        return False, _("falha ao chamar firmware: {e}").format(e=e)
    out = (r.stdout or "") + (r.stderr or "")
    tail = "\n".join(out.strip().splitlines()[-5:]) if out.strip() else ""
    if r.returncode == 0:
        # revalida: o arquivo esperado para este driver apareceu?
        files = installed_files(driver)
        if files:
            return True, _("firmware instalado: {files}").format(
                files=", ".join(os.path.basename(f) for f in files))
        return False, _("script concluiu, mas nenhum firmware de {driver} "
                        "apareceu em /usr/lib/firmware").format(
                            driver=driver or "xone/xow") + (f" — {tail}" if tail else "")
    return False, tail or _("script saiu com código {c}").format(c=r.returncode)
