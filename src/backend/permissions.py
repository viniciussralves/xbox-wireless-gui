"""Permissões: regra udev + grupo dedicado para evitar pkexec a cada clique.

Sem a regra, os attrs sysfs (leds gip*/brightness|mode e o pairing do
dongle) são root-only e cada Aplicar/pairing cai no pkexec. A regra
instalada dá acesso ao grupo ``xboxwireless`` (não ao grupo ``input``,
que também lê teclados) e o ``uaccess`` do logind libera os gamepads
para o usuário da sessão.
"""
from __future__ import annotations
import glob
import grp
import os
import pwd
import re
import shlex
import subprocess

from backend.i18n import _

RULE_NAME = "71-xbox-wireless-gui.rules"
RULE_DIRS = ("/usr/lib/udev/rules.d", "/etc/udev/rules.d")
CONTROL_GROUP = "xboxwireless"
_USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")

# A regra é gerada a partir desta constante (e não de um arquivo do
# checkout do usuário): assim o conteúdo enviado ao root é fixo e
# auditável, mesmo quando o app roda em modo desenvolvimento.
RULE_CONTENT = """\
# Xbox Wireless GUI — permite ao grupo xboxwireless gerenciar pairing e LEDs
# sem pkexec a cada clique. Instalado pelo RPM ou por install_fix().
# O grupo `input` NÃO é usado: ele também dá leitura a teclados.

# LEDs dos controles (xone): escrita em mode/brightness
ACTION=="add|change", SUBSYSTEM=="leds", KERNEL=="gip*", RUN+="/bin/sh -c 'chgrp xboxwireless /sys%p/brightness /sys%p/mode 2>/dev/null; chmod g+w /sys%p/brightness /sys%p/mode 2>/dev/null'"

# Dongle xone: escrita no pairing
ACTION=="add|change", DRIVER=="xone-dongle", RUN+="/bin/sh -c 'chgrp xboxwireless /sys/bus/usb/drivers/xone-dongle/*/pairing 2>/dev/null; chmod g+w /sys/bus/usb/drivers/xone-dongle/*/pairing 2>/dev/null'"

# Gamepads: ACL do logind para o usuário da sessão (evdev sem grupo input)
ACTION=="add|change", SUBSYSTEM=="input", ENV{ID_INPUT_JOYSTICK}=="1", TAG+="uaccess"
"""


def _rule_source() -> str | None:
    """Arquivo da regra (dev ou instalação). Mantido para diagnóstico."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = (
        os.path.join(here, "..", "..", "data", RULE_NAME),
        os.path.join("/usr/share/xbox-wireless-gui", RULE_NAME),
        os.path.join("/usr/lib/udev/rules.d", RULE_NAME),
        os.path.join("/etc/udev/rules.d", RULE_NAME),
    )
    for cand in candidates:
        cand = os.path.normpath(cand)
        if os.path.isfile(cand):
            return cand
    return None


def rule_installed() -> str | None:
    for d in RULE_DIRS:
        p = os.path.join(d, RULE_NAME)
        if os.path.isfile(p):
            return p
    return None


def _user_in_group(group: str) -> bool:
    try:
        user = pwd.getpwuid(os.getuid())
        for g in grp.getgrall():
            if g.gr_name != group:
                continue
            if user.pw_name in g.gr_mem:
                return True
            if getattr(user, "pw_gid", None) == getattr(g, "gr_gid", None):
                return True
    except (KeyError, OSError):
        return False
    return False


def in_input_group() -> bool:
    """Compatibilidade: aceita o grupo novo ou o legado ``input``."""
    return _user_in_group(CONTROL_GROUP) or _user_in_group("input")


def in_control_group() -> bool:
    return _user_in_group(CONTROL_GROUP)


def _effective_group(group: str) -> bool:
    try:
        gid = grp.getgrnam(group).gr_gid
        return gid == os.getgid() or gid in os.getgroups()
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
        from evdev import InputDevice
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
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def status() -> dict:
    rule = rule_installed()
    ingroup = in_control_group()
    effective = _effective_group(CONTROL_GROUP)
    leds_ok, leds_bad = leds_writable()
    pair_ok, pair_bad = pairing_writable()
    ev_ok, ev_info = evdev_readable()
    problems: list[str] = []
    if not rule:
        problems.append(_("regra udev ausente"))
    if not ingroup:
        problems.append(_("usuário fora do grupo {g}").format(g=CONTROL_GROUP))
    elif not effective:
        problems.append(_("sessão sem o grupo {g} (entre de novo)").format(
            g=CONTROL_GROUP))
    if not leds_ok:
        problems.append(_("LED sem escrita ({n})").format(n=len(leds_bad)))
    if not pair_ok:
        problems.append(_("pairing sem escrita ({n})").format(n=len(pair_bad)))
    if not ev_ok:
        problems.append(_("evdev sem leitura ({info})").format(info=ev_info))
    return {"ok": not problems, "rule": rule, "in_input_group": ingroup,
            "in_control_group": ingroup,
            "leds_ok": leds_ok, "pairing_ok": pair_ok,
            "evdev_ok": ev_ok, "evdev_info": ev_info,
            "problems": problems,
            "detail": _("tudo certo") if not problems else " • ".join(problems)}


def _login_user() -> str:
    """Usuário a adicionar ao grupo.

    Só aceita SUDO_UID/PKEXEC_UID quando o processo roda como root
    (ex.: app iniciado via sudo). Em execução normal, o ambiente é
    ignorado para impedir que um usuário escolha outra conta.
    """
    if os.geteuid() == 0:
        for var in ("SUDO_UID", "PKEXEC_UID"):
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


def _pkexec() -> str | None:
    for p in ("/usr/bin/pkexec", "/bin/pkexec"):
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


HELPER = "/usr/libexec/xbox-wireless-gui-helper"


def _helper() -> str | None:
    if not (os.path.isfile(HELPER) and os.access(HELPER, os.X_OK)):
        return None
    try:
        st = os.stat(HELPER)
    except OSError:
        return None
    if st.st_uid != 0 or st.st_mode & 0o022:
        return None
    return HELPER


def _finish_fix() -> tuple[bool, str]:
    st = status()
    if not st["in_control_group"]:
        extra = _(" (entre de novo no grupo {g} no próximo login)").format(
            g=CONTROL_GROUP)
    elif not st["ok"]:
        extra = _(" (saia e entre de novo para o grupo valer)")
    else:
        extra = ""
    if st["ok"]:
        return True, _("permissões corrigidas") + extra
    return True, _("regra instalada; pendente: {d}").format(d=st["detail"]) + extra


def install_fix() -> tuple[bool, str]:
    """Instala a regra udev + grupo + recarrega e adiciona o usuário.

    Com o helper instalado pelo RPM, usa subcomandos fixos. No checkout
    dev (sem helper) usa um script constante, sem interpolação de dados
    do checkout ou do PATH do usuário.
    """
    user = _login_user()
    if not user or not _USER_RE.match(user):
        return False, _("usuário inválido para o grupo")
    pkexec = _pkexec()
    if not pkexec:
        return False, _("pkexec não encontrado")
    helper = _helper()
    if helper:
        try:
            r = subprocess.run([pkexec, helper, "permissions", user],
                               capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return False, _("timeout instalando a regra")
        except OSError as e:
            return False, _("falha ao chamar pkexec: {e}").format(e=e)
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()
            return False, err or _("pkexec saiu {c}").format(c=r.returncode)
        return _finish_fix()
    rule_path = os.path.join("/etc/udev/rules.d", RULE_NAME)
    script = f"""set -eu
getent group {CONTROL_GROUP} >/dev/null 2>&1 || groupadd -r {CONTROL_GROUP}
cat > {rule_path} <<'XWG_RULE'
{RULE_CONTENT}XWG_RULE
chmod 644 {rule_path}
udevadm control --reload-rules
udevadm trigger --action=add --subsystem-match=leds
udevadm trigger --action=add --subsystem-match=input
usermod -aG {CONTROL_GROUP} {shlex.quote(user)}
chgrp {CONTROL_GROUP} /sys/class/leds/gip*/brightness /sys/class/leds/gip*/mode \
/sys/bus/usb/drivers/xone-dongle/*/pairing 2>/dev/null || true
chmod g+w /sys/class/leds/gip*/brightness /sys/class/leds/gip*/mode \
/sys/bus/usb/drivers/xone-dongle/*/pairing 2>/dev/null || true
"""
    try:
        r = subprocess.run([pkexec, "sh", "-c", script],
                           capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return False, _("timeout instalando a regra")
    except OSError as e:
        return False, _("falha ao chamar pkexec: {e}").format(e=e)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        return False, err or _("pkexec saiu {c}").format(c=r.returncode)
    return _finish_fix()
