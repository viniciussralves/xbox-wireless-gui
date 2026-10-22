"""Backend xow (legado): pairing via SIGUSR1 no serviço systemd."""
from __future__ import annotations
import os
import shutil
import subprocess

from backend.i18n import _


def available() -> bool:
    return shutil.which("xow") is not None


def service_active() -> bool:
    try:
        r = subprocess.run(["systemctl", "is-active", "xow"],
                           capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return r.stdout.strip() == "active"


def _pkexec() -> str | None:
    for p in ("/usr/bin/pkexec", "/bin/pkexec"):
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def set_pairing() -> tuple[bool, str]:
    """xow entra em pairing com: systemctl kill -s SIGUSR1 xow (precisa sudo)."""
    pkexec = _pkexec()
    if not pkexec:
        return False, _("pkexec não encontrado")
    cmd = [pkexec, "systemctl", "kill", "-s", "SIGUSR1", "xow"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            return True, _("xow em modo pairing (20s). Ligue o controle.")
        return False, (r.stderr or r.stdout).strip()
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def firmware_hint() -> str:
    return "sudo xow-get-firmware.sh  (firmware proprietário do dongle)"
