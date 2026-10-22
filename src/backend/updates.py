"""Verificação de atualizações contra os releases do GitHub."""
from __future__ import annotations
import json
import re
import urllib.request

REPO = "viniciussralves/xbox-wireless-gui"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

_CORE_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*$")


def _parse(tag: str) -> tuple[tuple[int, ...], tuple, bool]:
    """Parse de versão simples (v1.2.3, 1.2, 1.2.3-rc1).

    Retorna (números, pré-release, tem_pré-release). Levanta ValueError
    para tags que não são versões numéricas — nesse caso não anunciamos
    atualização, em vez de comparar strings.
    """
    t = (tag or "").strip()
    if t[:1] in ("v", "V"):
        t = t[1:]
    t = t.split("+", 1)[0]
    core, sep, pre = t.partition("-")
    if not core or not _CORE_RE.match(core):
        raise ValueError(f"versão inválida: {tag!r}")
    nums = tuple(int(p) for p in core.split("."))
    nums = nums + (0,) * max(0, 3 - len(nums))
    pre_parts: list[tuple[int, object]] = []
    if sep:
        for part in pre.split("."):
            if part.isdigit():
                pre_parts.append((0, int(part)))
            else:
                pre_parts.append((1, part))
    return nums, tuple(pre_parts), bool(sep)


def is_newer(latest: str, current: str) -> bool:
    """True somente se ``latest`` for uma versão numérica mais nova.

    Pré-releases são mais antigas que a versão final correspondente.
    Tags não parseáveis são tratadas como “não há atualização”.
    """
    try:
        lnums, lpre, lispre = _parse(latest)
        cnums, cpre, cispre = _parse(current)
    except (TypeError, ValueError):
        return False
    if lnums != cnums:
        return lnums > cnums
    if lispre != cispre:
        return not lispre  # final > pré-release
    if not lispre:
        return False
    return lpre > cpre


def latest_release(timeout: int = 8) -> dict:
    req = urllib.request.Request(API_URL, headers={"User-Agent": "xbox-wireless-gui"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        data = json.loads(resp.read().decode("utf-8", "replace"))
    return {"tag": data.get("tag_name", "") or "",
            "url": data.get("html_url") or f"https://github.com/{REPO}/releases"}


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
