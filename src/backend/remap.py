"""Integração com input-remapper (remapeamento/macros sem reinventar).

Não capturamos o evdev nem criamos uinput: abrimos a ferramenta
consolidada do ecossistema e deixamos o mapeamento para ela.
"""
from __future__ import annotations
import shutil
import subprocess

from backend.i18n import _

BINARIES = ("input-remapper-gtk", "input-remapper", "input-remapper-control")
DOCS = "https://github.com/sezanzeb/input-remapper"


def available() -> str | None:
    for name in BINARIES:
        path = shutil.which(name)
        if path:
            return path
    return None


def open_tool() -> tuple[bool, str]:
    path = available()
    if not path:
        return False, _("input-remapper não instalado")
    try:
        subprocess.Popen([path], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return True, _("input-remapper aberto")
    except OSError as e:
        return False, _("falha ao abrir input-remapper: {e}").format(e=e)


def hint() -> str:
    return _("Instale input-remapper para remapear botões/macros "
             "(https://github.com/sezanzeb/input-remapper)")
