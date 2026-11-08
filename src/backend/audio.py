"""Áudio do adaptador Xbox Wireless (xone expõe ALSA/PipeWire).

O xone suporta captura/playback e headsets; o app apenas consulta e
ajusta o roteamento via pactl (PipeWire/PulseAudio). Sem pactl, mostra
os cards do ALSA e não quebra.
"""
from __future__ import annotations
import re
import shutil
import subprocess

KEYS = ("xbox", "xone", "gip", "wireless headset", "controller")


def _run(args: list[str], timeout: int = 8) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def looks_like_xbox(name: str) -> bool:
    low = (name or "").lower()
    return any(k in low for k in KEYS)


def list_cards() -> list[dict]:
    """Cards do ALSA que parecem ser do adaptador/headset Xbox."""
    out: list[dict] = []
    path = "/proc/asound/cards"
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return out
    for line in lines:
        m = re.match(r"\s*(\d+)\s+\[([^\]]+)\]:\s*(.*)", line)
        if not m:
            continue
        num, short, desc = m.groups()
        if looks_like_xbox(short) or looks_like_xbox(desc):
            out.append({"id": num, "short": short.strip(),
                        "name": desc.strip()})
    return out


def _pactl_list(kind: str) -> list[dict]:
    if not shutil.which("pactl"):
        return []
    out = []
    for line in _run(["pactl", "list", "short", kind]).splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            out.append({"id": parts[0], "name": parts[1],
                        "driver": parts[2],
                        "state": parts[4] if len(parts) > 4 else ""})
    return out


def status() -> dict:
    sinks = _pactl_list("sinks")
    sources = _pactl_list("sources")
    cards = list_cards()
    return {
        "available": bool(shutil.which("pactl")),
        "cards": cards,
        "sinks": [s for s in sinks if looks_like_xbox(s["name"])],
        "sources": [s for s in sources if looks_like_xbox(s["name"])],
        "all_sinks": sinks,
        "all_sources": sources,
    }


def _valid_name(name: str) -> bool:
    return bool(name) and len(name) < 512 and "\n" not in name and "\x00" not in name


def set_default(kind: str, name: str) -> tuple[bool, str]:
    if kind not in ("sink", "source"):
        return False, "tipo inválido"
    if not _valid_name(name):
        return False, "nome inválido"
    if not shutil.which("pactl"):
        return False, "pactl não encontrado"
    out = _run(["pactl", f"set-default-{kind}", name])
    ok = not out.lower().startswith("failure")
    return ok, out or "ok"


def set_volume(kind: str, name: str, percent: int) -> tuple[bool, str]:
    if kind not in ("sink", "source") or not _valid_name(name):
        return False, "parâmetros inválidos"
    try:
        val = max(0, min(150, int(percent)))
    except (TypeError, ValueError):
        return False, "volume inválido"
    if not shutil.which("pactl"):
        return False, "pactl não encontrado"
    out = _run(["pactl", f"set-{kind}-volume", name, f"{val}%"])
    return (not out.lower().startswith("failure")), out or "ok"


def set_mute(kind: str, name: str, muted: bool) -> tuple[bool, str]:
    if kind not in ("sink", "source") or not _valid_name(name):
        return False, "parâmetros inválidos"
    if not shutil.which("pactl"):
        return False, "pactl não encontrado"
    out = _run(["pactl", f"set-{kind}-mute", name, "1" if muted else "0"])
    return (not out.lower().startswith("failure")), out or "ok"


def has_xone_audio() -> bool:
    return bool(list_cards()) or bool(status()["sinks"]) or bool(status()["sources"])


def alsa_card_for(device_name: str) -> str | None:
    """Mapeia um nome de dispositivo para o card ALSA correspondente."""
    low = (device_name or "").lower()
    for card in list_cards():
        if card["short"].lower() in low or card["name"].lower() in low:
            return card["id"]
    return None
