"""Logging do app: stderr + arquivo rotativo em XDG_STATE_HOME.

A GUI usa ``toast`` para o usuário e este módulo para diagnóstico. O
arquivo fica em ``~/.local/state/xbox-wireless-gui/app.log`` por padrão.
"""
from __future__ import annotations
import logging
import os
from logging.handlers import RotatingFileHandler

APP = "xbox-wireless-gui"
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_configured = False


def state_dir() -> str:
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, APP)


def log_path() -> str:
    return os.path.join(state_dir(), "app.log")


def setup(verbose: bool = False, filename: str | None = None) -> logging.Logger:
    """Configura uma única vez; nunca derruba o app se o disco falhar."""
    global _configured
    logger = logging.getLogger(APP)
    if _configured:
        if verbose:
            logger.setLevel(logging.DEBUG)
        return logger
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False
    fmt = logging.Formatter(_FORMAT)

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    path = filename or log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fh = RotatingFileHandler(path, maxBytes=512 * 1024,
                                 backupCount=2, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        pass
    # journald/syslog nativo quando /dev/log existe (Fedora/Debian)
    try:
        if os.path.exists("/dev/log"):
            from logging.handlers import SysLogHandler
            sh = SysLogHandler(address="/dev/log")
            sh.setFormatter(fmt)
            logger.addHandler(sh)
    except OSError:
        pass
    _configured = True
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(f"{APP}.{name}" if name else APP)


def tail(lines: int = 80) -> str:
    try:
        n = max(1, min(500, int(lines)))
    except (TypeError, ValueError):
        n = 80
    try:
        with open(log_path(), encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-n:])
    except OSError:
        return ""
