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


def service_enabled() -> bool:
    try:
        r = subprocess.run(["systemctl", "is-enabled", "xow"],
                           capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return r.stdout.strip() == "enabled"


def service_control(action: str) -> tuple[bool, str]:
    """start/stop/restart do xow via helper/pkexec (precisa root)."""
    if action not in ("start", "stop", "restart", "enable", "disable"):
        return False, _("ação inválida")
    helper = "/usr/libexec/xbox-wireless-gui-helper"
    if os.path.isfile(helper) and os.access(helper, os.X_OK):
        try:
            st = os.stat(helper)
            if st.st_uid == 0 and not (st.st_mode & 0o022):
                pkexec = _pkexec()
                if pkexec:
                    r = subprocess.run([pkexec, helper, "xow", action],
                                       capture_output=True, text=True, timeout=60)
                    if r.returncode == 0:
                        return True, _("xow {a}").format(a=action)
                    return False, (r.stderr or r.stdout or "").strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    pkexec = _pkexec()
    if not pkexec:
        return False, _("pkexec não encontrado")
    try:
        r = subprocess.run([pkexec, "systemctl", action, "xow"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            return True, _("xow {a}").format(a=action)
        return False, (r.stderr or r.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)


def logs(lines: int = 80) -> str:
    try:
        n = max(10, min(500, int(lines)))
    except (TypeError, ValueError):
        n = 80
    try:
        r = subprocess.run(["journalctl", "-u", "xow", "-n", str(n),
                            "--no-pager"], capture_output=True, text=True,
                           timeout=10)
        return ((r.stdout or "") + (r.stderr or "")).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return str(e)


def firmware_hint() -> str:
    return "sudo xow-get-firmware.sh  (firmware proprietário do dongle)"
