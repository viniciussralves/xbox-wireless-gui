"""Teste de vibração via evdev (ff-rumble)."""
from __future__ import annotations

from backend.i18n import _


def is_virtual_pad(name: str | None) -> bool:
    """Distingue o “Microsoft X-Box 360 pad” virtual do xone de um real."""
    return (name or "").startswith("Microsoft X-Box 360 pad")


def find_gamepads() -> list[dict]:
    try:
        from evdev import InputDevice, list_devices
    except ImportError:
        return []
    out = []
    try:
        paths = list(list_devices())
    except OSError:
        return []
    for path in paths:
        try:
            d = InputDevice(path)
        except OSError:
            continue
        try:
            name = d.name or ""
            if not any(k in name.lower() for k in
                       ("xbox", "x-box", "microsoft", "gip", "gamepad", "controller")):
                continue
            caps = d.capabilities()
            out.append({"path": path, "name": name,
                        "phys": getattr(d, "phys", "") or "",
                        "has_rumble": 0x15 in caps or any("FF_" in str(c) for c in caps)})
        except OSError:
            continue
        finally:
            try:
                d.close()
            except OSError:
                pass
    # controle real primeiro; “X-Box 360 pad” (compat virtual) por último
    out.sort(key=lambda p: (is_virtual_pad(p["name"]), p["path"]))
    return out


def rumble(path: str, duration_ms: int = 600, strong: int = 0x8000, weak: int = 0x8000) -> tuple[bool, str]:
    try:
        from evdev import InputDevice, ff, ecodes
        import time
        dev = InputDevice(path)
        try:
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
        finally:
            try:
                dev.close()
            except OSError:
                pass
        return True, _("vibração enviada em {path}").format(path=path)
    except PermissionError:
        return False, _("sem permissão em {path} (regra udev/uaccess ou grupo xboxwireless)").format(path=path)
    except Exception as e:  # noqa: BLE001
        return False, str(e)
