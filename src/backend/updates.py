"""Verificação de atualizações contra os releases do GitHub."""
from __future__ import annotations
import json
import urllib.request

REPO = "viniciussralves/xbox-wireless-gui"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"


def _norm(tag: str) -> tuple:
    t = (tag or "").strip().lstrip("v")
    parts: list = []
    for chunk in t.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(chunk)
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    try:
        return _norm(latest) > _norm(current)
    except TypeError:
        return str(latest) != str(current)


def latest_release(timeout: int = 8) -> dict:
    req = urllib.request.Request(API_URL, headers={"User-Agent": "xbox-wireless-gui"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        data = json.loads(resp.read().decode("utf-8", "replace"))
    return {"tag": data.get("tag_name", ""),
            "url": data.get("html_url", f"https://github.com/{REPO}/releases")}


def check(current: str, timeout: int = 8) -> dict:
    """{'newer': bool, 'tag': str, 'url': str} — nunca levanta exceção."""
    try:
        rel = latest_release(timeout=timeout)
        tag = rel.get("tag", "")
        if tag and is_newer(tag, current):
            return {"newer": True, "tag": tag, "url": rel.get("url", "")}
        return {"newer": False, "tag": tag, "url": rel.get("url", "")}
    except Exception as e:  # noqa: BLE001 (offline etc.: silencioso na UI)
        return {"newer": False, "tag": "", "url": "", "error": str(e)}
