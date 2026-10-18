"""i18n via gettext (pt-BR padrão, en disponível).

msgids em pt-BR (idioma original da UI). Traduções compiladas em:
- instalado: /usr/share/locale/<lang>/LC_MESSAGES/xbox-wireless-gui.mo
- dev: <repo>/locale/<lang>/LC_MESSAGES/xbox-wireless-gui.mo
Sem .mo ou sem locale: cai no NullTranslations (mostra o msgid).
"""
from __future__ import annotations
import gettext
import locale
import os

APP = "xbox-wireless-gui"


def _localedirs() -> list[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    return [
        "/usr/share/locale",
        os.path.normpath(os.path.join(here, "..", "..", "locale")),
    ]


def _pick_language() -> str | None:
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        val = (os.environ.get(var, "") or "").split(":")[0]
        if val and val.lower() != "c":
            return val
    try:
        loc = locale.getdefaultlocale()[0]
    except Exception:  # noqa: BLE001
        loc = None
    return loc


def get_translation() -> gettext.NullTranslations:
    lang = _pick_language()
    if not lang:
        return gettext.NullTranslations()
    for localedir in _localedirs():
        try:
            tr = gettext.translation(APP, localedir=localedir,
                                     languages=[lang, lang.split("_")[0]])
            return tr
        except (FileNotFoundError, OSError):
            continue
    return gettext.NullTranslations()


_translation = get_translation()
_ = _translation.gettext
N_ = lambda s: s  # noqa: E731  (marca msgid para extração sem traduzir)
