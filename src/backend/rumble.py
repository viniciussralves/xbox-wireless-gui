"""Teste de vibração via evdev (ff-rumble)."""
from __future__ import annotations

from backend.i18n import _


def find_gamepads() -> list[dict]:
    try:
        from evdev import InputDevice, list_devices
    except ImportError:
        return []
    out = []
    for path in list_devices():
        try:
            d = InputDevice(path)
            name = d.name or ""
            if any(k in name.lower() for k in ("xbox", "x-box", "microsoft", "gip", "gamepad", "controller")):
                caps = d.capabilities()
                out.append({"path": path, "name": name,
                            "has_rumble": 0x15 in caps or any("FF_" in str(c) for c in caps)})
        except OSError:
            continue
    # controle real primeiro; "X-Box 360 pad" (compat virtual) por último
    out.sort(key=lambda p: ("360" in p["name"], p["path"]))
    return out


def rumble(path: str, duration_ms: int = 600, strong: int = 0x8000, weak: int = 0x8000) -> tuple[bool, str]:
    try:
        from evdev import InputDevice, ff, ecodes
        import time
        dev = InputDevice(path)
        r = ff.Rumble(strong_magnitude=strong, weak_magnitude=weak)
        effect = ff.Effect(ecodes.FF_RUMBLE, -1, 0,
                           ff.Trigger(0, 0),
                           ff.Replay(duration_ms, 0),
                           ff.EffectType(ff_rumble=r))
        eid = dev.upload_effect(effect)
        dev.write(ecodes.EV_FF, eid, 1)
        time.sleep(duration_ms / 1000 + 0.2)
        dev.write(ecodes.EV_FF, eid, 0)
        dev.erase_effect(eid)
        return True, _("vibração enviada em {path}").format(path=path)
    except PermissionError:
        return False, _("sem permissão em {path} (adicione udev rule input ou rode com sudo)").format(path=path)
    except Exception as e:  # noqa: BLE001
        return False, str(e)
