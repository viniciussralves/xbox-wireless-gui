"""Perfis por controle (nome, LED e preferências) persistidos em JSON.

GSettings é ótimo para preferências fixas, mas não para chaves dinâmicas
por serial. Este módulo guarda um dicionário pequeno e legível em
``$XDG_CONFIG_HOME/xbox-wireless-gui/profiles.json``.
"""
from __future__ import annotations
import json
import os
import tempfile

APP_DIR = "xbox-wireless-gui"
FILE_NAME = "profiles.json"


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    return os.path.join(base, APP_DIR)


def profiles_path() -> str:
    return os.path.join(config_dir(), FILE_NAME)


def load() -> dict:
    path = profiles_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data: dict) -> bool:
    """Escrita atômica; nunca deixa um JSON truncado no disco."""
    path = profiles_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".profiles-", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        return True
    except OSError:
        return False


def _key(serial: str | None) -> str:
    return (serial or "").strip() or "default"


def get(serial: str | None) -> dict:
    data = load()
    value = data.get(_key(serial), {})
    return value if isinstance(value, dict) else {}


def update(serial: str | None, **values) -> dict:
    data = load()
    key = _key(serial)
    current = data.get(key)
    if not isinstance(current, dict):
        current = {}
    current.update(values)
    data[key] = current
    save(data)
    return current


def name_of(serial: str | None) -> str:
    return str(get(serial).get("name") or "")


def set_name(serial: str | None, name: str) -> bool:
    update(serial, name=name.strip())
    return True


def led_of(serial: str | None) -> dict:
    val = get(serial).get("led")
    return val if isinstance(val, dict) else {}


def set_led(serial: str | None, mode: str, brightness: int) -> bool:
    update(serial, led={"mode": str(mode), "brightness": int(brightness)})
    return True
