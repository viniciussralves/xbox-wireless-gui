"""Backend xone: pairing via sysfs + lista controles via leds gip* + evdev."""
from __future__ import annotations
import glob
import os
import re
import shlex
import subprocess

from backend.i18n import _

_LED_ID_RE = re.compile(r"^[A-Za-z0-9._:+\-]+$")
_SYSFS_PAIRING_PREFIX = "/sys/bus/usb/drivers/xone-dongle/"
_SYSFS_LEDS_PREFIX = "/sys/class/leds/"

# Modos válidos do enum gip_led_mode do xone (driver/common.c e
# bus/protocol.h): off, on, blink fast/normal/slow, fade slow/fast.
VALID_LED_MODES = ("0", "1", "2", "3", "4", "8", "9")


def list_dongles() -> list[str]:
    """Todos os dongles ligados (suporte a múltiplos adaptadores)."""
    return sorted(glob.glob("/sys/bus/usb/drivers/xone-dongle/*:*"))


def get_pairing_file(dongle: str | None = None) -> str | None:
    if dongle is not None:
        if not dongle.startswith(_SYSFS_PAIRING_PREFIX) or ".." in dongle:
            return None
        cand = os.path.join(dongle, "pairing")
        return cand if os.path.isfile(cand) else None
    files = glob.glob("/sys/bus/usb/drivers/xone-dongle/*/pairing")
    return sorted(files)[0] if files else None


def get_pairing(dongle: str | None = None) -> bool | None:
    pf = get_pairing_file(dongle)
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
    # Usa a ação padrão org.freedesktop.policykit.exec: o pkexec atual
    # não aceita --action-id; um helper com anotações exec.* seria o
    # próximo passo para autorizações granulares.
    pkexec = _pkexec()
    if not pkexec:
        raise FileNotFoundError("pkexec")
    return subprocess.run([pkexec, "sh", "-c", snippet],
                          capture_output=True, text=True, timeout=60)


def _pkexec() -> str | None:
    for p in ("/usr/bin/pkexec", "/bin/pkexec"):
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


HELPER = "/usr/libexec/xbox-wireless-gui-helper"


def _helper() -> str | None:
    """Helper root-owned instalado pelo RPM (não o checkout do usuário)."""
    if not (os.path.isfile(HELPER) and os.access(HELPER, os.X_OK)):
        return None
    try:
        st = os.stat(HELPER)
    except OSError:
        return None
    if st.st_uid != 0 or st.st_mode & 0o022:
        return None
    return HELPER


def _run_helper(*args: str) -> subprocess.CompletedProcess | None:
    helper = _helper()
    pkexec = _pkexec()
    if not helper or not pkexec:
        return None
    try:
        return subprocess.run([pkexec, helper, *args],
                              capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return None


def _helper_error(r: subprocess.CompletedProcess) -> str:
    return (r.stderr or r.stdout or f"helper saiu {r.returncode}").strip()


def set_pairing(enable: bool, dongle: str | None = None) -> tuple[bool, str]:
    """Precisa de root. Tenta escrita direta, senão pkexec (polkit)."""
    pf = _valid_pairing_file(get_pairing_file(dongle))
    if not pf:
        return False, _("arquivo pairing não encontrado (dongle desplugado?)")
    val = "1" if enable else "0"
    try:
        with open(pf, "w") as f:
            f.write(val + "\n")
        return True, _("pairing=ativado") if enable else _("pairing=desativado")
    except PermissionError:
        pass  # cai para o helper/pkexec abaixo
    except OSError as e:
        return False, _("falha ao escrever pairing: {e}").format(e=e)
    r = _run_helper("pairing", "on" if enable else "off", pf)
    if r is not None:
        if r.returncode == 0:
            return True, _("pairing=ativado") if enable else _("pairing=desativado")
        return False, _helper_error(r)
    cmd = f"echo {val} > {shlex.quote(pf)}"
    try:
        r = _run_pkexec_shell(cmd)
        if r.returncode == 0:
            return True, _("pairing=ativado") if enable else _("pairing=desativado")
        return False, (r.stderr or r.stdout or f"pkexec saiu {r.returncode}").strip()
    except subprocess.TimeoutExpired:
        return False, _("timeout no pkexec")
    except FileNotFoundError:
        return False, _("pkexec não encontrado")


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
    if not cid or not _LED_ID_RE.match(cid) or ".." in cid or cid in (".", ".."):
        return False, _("{cid} inválido").format(cid=cid)
    if mode not in VALID_LED_MODES:
        return False, _("mode {mode} inválido (use {modes})").format(
            mode=mode, modes=", ".join(VALID_LED_MODES))
    try:
        bval = int(brightness)
    except (ValueError, TypeError):
        return False, _("brilho {brilho} inválido").format(brilho=brightness)
    base = f"/sys/class/leds/{cid}"
    # sysfs usa symlinks (realpath -> /sys/devices), então valida a string
    # + existência, não o prefixo do realpath.
    if not base.startswith(_SYSFS_LEDS_PREFIX) or not os.path.isdir(base):
        return False, _("{cid} não existe").format(cid=cid)
    # valida faixa contra max_brightness quando legível
    try:
        with open(os.path.join(base, "max_brightness")) as f:
            mx = int(f.read().strip())
        if not 0 <= bval <= mx:
            return False, _("brilho fora da faixa 0-{mx}").format(mx=mx)
    except (OSError, ValueError):
        if not 0 <= bval <= 255:
            return False, _("brilho fora da faixa")
    # tenta escrita direta (roda como root / udev rule), senão pkexec
    try:
        with open(os.path.join(base, "mode"), "w") as f:
            f.write(mode + "\n")
        with open(os.path.join(base, "brightness"), "w") as f:
            f.write(str(bval) + "\n")
        return True, _("LED atualizado")
    except PermissionError:
        pass
    except OSError as e:
        return False, _("falha ao escrever LED: {e}").format(e=e)
    r = _run_helper("led", cid, mode, str(bval))
    if r is not None:
        if r.returncode == 0:
            return True, _("LED atualizado")
        return False, _helper_error(r)
    cmd = (f"echo {shlex.quote(mode)} > {shlex.quote(base + '/mode')}; "
           f"echo {shlex.quote(str(bval))} > {shlex.quote(base + '/brightness')}")
    try:
        r = _run_pkexec_shell(cmd)
        if r.returncode == 0:
            return True, _("LED atualizado")
        return False, (r.stderr or r.stdout or f"pkexec saiu {r.returncode}").strip()
    except Exception as e:  # noqa: BLE001
        return False, str(e)
