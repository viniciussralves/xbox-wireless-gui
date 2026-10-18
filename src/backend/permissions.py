"""Permissões: regra udev + grupo input para evitar pkexec a cada clique.

Sem a regra, os attrs sysfs (leds gip*/brightness|mode e o pairing do
dongle) são root-only e cada Aplicar/pairing cai no pkexec. Com a regra
instalada + usuário no grupo `input`, a escrita direta funciona.
"""
from __future__ import annotations
import glob
import grp
import os
import pwd
import shutil
import subprocess

from backend.i18n import _

RULE_NAME = "71-xbox-wireless-gui.rules"
RULE_DIRS = ("/usr/lib/udev/rules.d", "/etc/udev/rules.d")


def _rule_source() -> str | None:
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "..", "..", "data", RULE_NAME),
                 os.path.join("/usr/share/xbox-wireless-gui", RULE_NAME)):
        if os.path.isfile(cand):
            return os.path.normpath(cand)
    return None


def rule_installed() -> str | None:
    for d in RULE_DIRS:
        p = os.path.join(d, RULE_NAME)
        if os.path.isfile(p):
            return p
    return None


def in_input_group() -> bool:
    try:
        return "input" in [g.gr_name for g in grp.getgrall()
                           if pwd.getpwuid(os.getuid()).pw_name in g.gr_mem]
    except (KeyError, OSError):
        return False


def _writable_sysfs(patterns: list[str]) -> tuple[bool, list[str]]:
    targets: list[str] = []
    for pat in patterns:
        targets.extend(sorted(glob.glob(pat)))
    if not targets:
        return True, []  # sem dispositivo: nada a exigir
    bad = [t for t in targets if not os.access(t, os.W_OK)]
    return (len(bad) == 0), bad


def leds_writable() -> tuple[bool, list[str]]:
    return _writable_sysfs(["/sys/class/leds/gip*/brightness",
                            "/sys/class/leds/gip*/mode"])


def pairing_writable() -> tuple[bool, list[str]]:
    return _writable_sysfs(["/sys/bus/usb/drivers/xone-dongle/*/pairing"])


def evdev_readable() -> tuple[bool, str]:
    try:
        from evdev import InputDevice, list_devices
        from backend import rumble
        pads = rumble.find_gamepads()
        if not pads:
            return True, _("sem gamepad para testar")
        for p in pads:
            try:
                InputDevice(p["path"]).close()
                return True, p["path"]
            except (PermissionError, OSError):
                continue
        return False, pads[0]["path"]
    except ImportError:
        return True, _("python3-evdev ausente (leitura não testada)")


def status() -> dict:
    rule = rule_installed()
    ingroup = in_input_group()
    leds_ok, leds_bad = leds_writable()
    pair_ok, pair_bad = pairing_writable()
    ev_ok, ev_info = evdev_readable()
    problems: list[str] = []
    if not rule:
        problems.append(_("regra udev ausente"))
    if not ingroup:
        problems.append(_("usuário fora do grupo input"))
    if not leds_ok:
        problems.append(_("LED sem escrita ({n})").format(n=len(leds_bad)))
    if not pair_ok:
        problems.append(_("pairing sem escrita ({n})").format(n=len(pair_bad)))
    if not ev_ok:
        problems.append(_("evdev sem leitura ({info})").format(info=ev_info))
    return {"ok": not problems, "rule": rule, "in_input_group": ingroup,
            "leds_ok": leds_ok, "pairing_ok": pair_ok,
            "evdev_ok": ev_ok, "evdev_info": ev_info,
            "problems": problems,
            "detail": _("tudo certo") if not problems else " • ".join(problems)}


def _login_user() -> str:
    for var in ("PKEXEC_UID", "SUDO_UID"):
        try:
            uid = int(os.environ.get(var, "") or -1)
            if uid >= 0:
                return pwd.getpwuid(uid).pw_name
        except (ValueError, KeyError):
            continue
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return ""


def install_fix() -> tuple[bool, str]:
    """Instala a regra udev + recarrega + põe o usuário no grupo input."""
    src = _rule_source()
    if not src:
        return False, _("arquivo da regra não encontrado na instalação")
    if shutil.which("pkexec") is None:
        return False, _("pkexec não encontrado")
    user = _login_user()
    script = (
        f"install -m644 {src} /etc/udev/rules.d/{RULE_NAME} && "
        "udevadm control --reload-rules && udevadm trigger --subsystem-match=leds && "
        f"usermod -aG input {user} && "
        "sh -c 'chgrp input /sys/class/leds/gip*/brightness /sys/class/leds/gip*/mode "
        "/sys/bus/usb/drivers/xone-dongle/*/pairing 2>/dev/null; "
        "chmod g+w /sys/class/leds/gip*/brightness /sys/class/leds/gip*/mode "
        "/sys/bus/usb/drivers/xone-dongle/*/pairing 2>/dev/null; true'"
    )
    try:
        r = subprocess.run(["pkexec", "sh", "-c", script],
                           capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return False, _("timeout instalando a regra")
    except OSError as e:
        return False, _("falha ao chamar pkexec: {e}").format(e=e)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        return False, err or _("pkexec saiu {c}").format(c=r.returncode)
    st = status()
    extra = "" if st["in_input_group"] else _(" (entre de novo no grupo input no próximo login)")
    if st["ok"]:
        return True, _("permissões corrigidas") + extra
    return True, _("regra instalada; pendente: {d}").format(d=st["detail"]) + extra
