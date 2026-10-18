"""Backend xone: pairing via sysfs + lista controles via leds gip* + evdev."""
from __future__ import annotations
import glob
import os
import re
import shlex
import subprocess

_LED_ID_RE = re.compile(r"^[A-Za-z0-9._:+\-]+$")
_SYSFS_PAIRING_PREFIX = "/sys/bus/usb/drivers/xone-dongle/"
_SYSFS_LEDS_PREFIX = "/sys/class/leds/"


def get_pairing_file() -> str | None:
    files = glob.glob("/sys/bus/usb/drivers/xone-dongle/*/pairing")
    return sorted(files)[0] if files else None


def get_pairing() -> bool | None:
    pf = get_pairing_file()
    if not pf:
        return None
    try:
        with open(pf) as f:
            return f.read().strip() == "1"
    except OSError:
        return None


def _valid_pairing_file(pf: str | None) -> str | None:
    # pf vem do nosso próprio glob; valida o formato sem realpath
    # (o sysfs usa symlinks -> /sys/devices, realpath quebraria o prefixo).
    if not pf or os.path.basename(pf) != "pairing":
        return None
    if not pf.startswith(_SYSFS_PAIRING_PREFIX):
        return None
    if ".." in pf or "//" in pf.replace("://", ""):
        return None
    return pf


def _run_pkexec_shell(snippet: str) -> subprocess.CompletedProcess:
    # snippet já vem com valores validados/quotados pelo chamador.
    return subprocess.run(["pkexec", "sh", "-c", snippet],
                          capture_output=True, text=True, timeout=60)


def set_pairing(enable: bool) -> tuple[bool, str]:
    """Precisa de root. Tenta escrita direta, senão pkexec (polkit)."""
    pf = _valid_pairing_file(get_pairing_file())
    if not pf:
        return False, "arquivo pairing não encontrado (dongle desplugado?)"
    val = "1" if enable else "0"
    try:
        with open(pf, "w") as f:
            f.write(val + "\n")
        return True, f"pairing={'ativado' if enable else 'desativado'}"
    except PermissionError:
        pass  # cai para pkexec abaixo
    except OSError as e:
        return False, f"falha ao escrever pairing: {e}"
    cmd = f"echo {val} > {shlex.quote(pf)}"
    try:
        r = _run_pkexec_shell(cmd)
        if r.returncode == 0:
            return True, f"pairing={'ativado' if enable else 'desativado'}"
        return False, (r.stderr or r.stdout or f"pkexec saiu {r.returncode}").strip()
    except subprocess.TimeoutExpired:
        return False, "timeout no pkexec"
    except FileNotFoundError:
        return False, "pkexec não encontrado"


def list_controllers() -> list[dict]:
    """Combina /sys/class/leds/gip* (LED/mode) + UPower é feito em battery.py.
    Retorna [{'id': 'gip0', 'mode': ..., 'brightness': ...}, ...]"""
    out = []
    for led in sorted(glob.glob("/sys/class/leds/gip*")):
        cid = os.path.basename(led)
        info: dict = {"id": cid, "sysfs": led}
        for attr in ("mode", "brightness", "max_brightness"):
            try:
                with open(os.path.join(led, attr)) as f:
                    info[attr] = f.read().strip()
            except OSError:
                info[attr] = "?"
        out.append(info)
    return out


def set_led(cid: str, mode: str, brightness: str) -> tuple[bool, str]:
    if not cid or not _LED_ID_RE.match(cid):
        return False, f"{cid} inválido"
    if mode not in ("0", "1", "2"):
        return False, f"mode {mode} inválido (use 0-2)"
    try:
        bval = int(brightness)
    except (ValueError, TypeError):
        return False, f"brilho {brightness} inválido"
    base = f"/sys/class/leds/{cid}"
    # sysfs usa symlinks (realpath -> /sys/devices), então valida a string
    # + existência, não o prefixo do realpath.
    if not base.startswith(_SYSFS_LEDS_PREFIX) or not os.path.isdir(base):
        return False, f"{cid} não existe"
    # valida faixa contra max_brightness quando legível
    try:
        with open(os.path.join(base, "max_brightness")) as f:
            mx = int(f.read().strip())
        if not 0 <= bval <= mx:
            return False, f"brilho fora da faixa 0-{mx}"
    except (OSError, ValueError):
        if not 0 <= bval <= 255:
            return False, "brilho fora da faixa"
    # tenta escrita direta (roda como root / udev rule), senão pkexec
    try:
        with open(os.path.join(base, "mode"), "w") as f:
            f.write(mode + "\n")
        with open(os.path.join(base, "brightness"), "w") as f:
            f.write(str(bval) + "\n")
        return True, "LED atualizado"
    except PermissionError:
        pass
    except OSError as e:
        return False, f"falha ao escrever LED: {e}"
    cmd = (f"echo {shlex.quote(mode)} > {shlex.quote(base + '/mode')}; "
           f"echo {shlex.quote(str(bval))} > {shlex.quote(base + '/brightness')}")
    try:
        r = _run_pkexec_shell(cmd)
        if r.returncode == 0:
            return True, "LED atualizado"
        return False, (r.stderr or r.stdout or f"pkexec saiu {r.returncode}").strip()
    except Exception as e:  # noqa: BLE001
        return False, str(e)
