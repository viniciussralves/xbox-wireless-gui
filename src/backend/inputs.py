"""Monitor de botões/eixos via evdev + estado normalizado p/ o testador.

Separado do rumble.py para manter a lógica de eventos testável sem GTK.
"""
from __future__ import annotations


BUTTONS = ("a", "b", "x", "y", "lb", "rb", "back", "start",
           "xbox", "l3", "r3", "share")


def new_state(name: str = "", path: str = "") -> dict:
    st = {b: False for b in BUTTONS}
    st.update({
        "lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0,
        "lt": 0.0, "rt": 0.0,
        "hat": (0, 0),
        # botões que o xone/xpadneo expuserem e não estejam no mapa fixo
        "extra": {},
        "name": name, "path": path,
        "connected": False,
    })
    return st


def code_name(code: int) -> str:
    """Nome legível de um código EV_KEY (para log e botões extras)."""
    try:
        from evdev import ecodes
        val = ecodes.bytype.get(ecodes.EV_KEY, {}).get(code, str(code))
        if isinstance(val, (tuple, list)):
            val = val[-1] if val else str(code)
        return str(val)
    except ImportError:
        return str(code)


def key_map() -> dict[int, str]:
    """Mapeia ecodes EV_KEY -> nome do botão do testador."""
    try:
        from evdev import ecodes
    except ImportError:
        return {}
    out = {
        ecodes.BTN_SOUTH: "a",
        ecodes.BTN_EAST: "b",
        ecodes.BTN_NORTH: "x",
        ecodes.BTN_WEST: "y",
        ecodes.BTN_TL: "lb",
        ecodes.BTN_TR: "rb",
        ecodes.BTN_SELECT: "back",
        ecodes.BTN_START: "start",
        ecodes.BTN_MODE: "xbox",
        ecodes.BTN_THUMBL: "l3",
        ecodes.BTN_THUMBR: "r3",
    }
    # O Share varia entre xpadneo/xone/terceiros; aceita os códigos usuais
    # sem quebrar o mapa fixo caso o driver não os exponha.
    for attr in ("BTN_C", "KEY_RECORD", "BTN_TRIGGER_HAPPY1"):
        code = getattr(ecodes, attr, None)
        if code is not None:
            out.setdefault(code, "share")
    return out


def _norm_stick(value: int, lo: int, hi: int, deadzone: float = 0.0) -> float:
    if hi <= lo:
        return 0.0
    mid = (hi + lo) / 2.0
    span = (hi - lo) / 2.0
    v = (value - mid) / span
    v = max(-1.0, min(1.0, v))
    # zona morta: ignora tremor perto do centro (preferência do testador)
    if deadzone > 0 and abs(v) < deadzone:
        return 0.0
    return v


def _norm_trigger(value: int, lo: int, hi: int) -> float:
    if hi <= lo:
        return 0.0
    v = (value - lo) / (hi - lo)
    return max(0.0, min(1.0, v))


def apply_key(state: dict, code: int, pressed: bool) -> bool:
    name = key_map().get(code)
    if not name:
        # Guarda botões desconhecidos para o testador mostrar (Share,
        # paddles do Elite, botões de volantes etc.) sem inventar mapa.
        extra = state.setdefault("extra", {})
        label = code_name(code)
        if pressed:
            extra[label] = True
        else:
            extra.pop(label, None)
        return False
    state[name] = bool(pressed)
    return True


def apply_abs(state: dict, code: int, value: int,
              limits: dict[int, tuple[int, int]],
              deadzone: float = 0.0) -> bool:
    """Aplica evento EV_ABS. limits: {code: (min, max)} do dispositivo."""
    try:
        from evdev import ecodes
    except ImportError:
        return False
    stick_codes = (ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_RX, ecodes.ABS_RY)
    gas = getattr(ecodes, "ABS_GAS", None)
    brake = getattr(ecodes, "ABS_BRAKE", None)
    trigger_codes = (ecodes.ABS_Z, ecodes.ABS_RZ, gas, brake)
    lo, hi = limits.get(code, (0, 0))
    if hi <= lo:
        if code in stick_codes:
            lo, hi = -32768, 32767
        elif code in trigger_codes:
            lo, hi = 0, 255
    if code == ecodes.ABS_X:
        state["lx"] = _norm_stick(value, lo, hi, deadzone)
    elif code == ecodes.ABS_Y:
        state["ly"] = _norm_stick(value, lo, hi, deadzone)
    elif code == ecodes.ABS_RX:
        state["rx"] = _norm_stick(value, lo, hi, deadzone)
    elif code == ecodes.ABS_RY:
        state["ry"] = _norm_stick(value, lo, hi, deadzone)
    elif code in (ecodes.ABS_Z, gas):
        state["lt"] = _norm_trigger(value, lo, hi)
    elif code in (ecodes.ABS_RZ, brake):
        state["rt"] = _norm_trigger(value, lo, hi)
    elif code == ecodes.ABS_HAT0X:
        state["hat"] = (int(value), state["hat"][1])
    elif code == ecodes.ABS_HAT0Y:
        state["hat"] = (state["hat"][0], int(value))
    else:
        return False
    return True


def pressed_names(state: dict) -> list[str]:
    names = [b for b in BUTTONS if state.get(b)]
    names.extend(k for k, v in (state.get("extra") or {}).items() if v)
    return names


def resync(state: dict, dev, limits: dict[int, tuple[int, int]],
           deadzone: float = 0.0) -> bool:
    """Ressincroniza após SYN_DROPPED (buffer evdev transbordou).

    Rele `active_keys()` + `absinfo()` e corrige botões "grudados"
    por eventos perdidos. Retorna True se algo mudou.
    """
    try:
        pressed = set(dev.active_keys())
    except (AttributeError, OSError, IOError):
        return False
    changed = False
    known = key_map()
    for code, name in known.items():
        want = code in pressed
        if state.get(name) is not want:
            state[name] = want
            changed = True
    extras = {code_name(c): True for c in pressed if c not in known}
    if extras != (state.get("extra") or {}):
        state["extra"] = extras
        changed = True
    for code in limits:
        try:
            val = dev.absinfo(code).value
        except (AttributeError, OSError, IOError):
            continue
        before = (state.get("hat"), state.get("lx"), state.get("ly"),
                  state.get("rx"), state.get("ry"),
                  state.get("lt"), state.get("rt"))
        apply_abs(state, code, val, limits, deadzone)
        after = (state.get("hat"), state.get("lx"), state.get("ly"),
                 state.get("rx"), state.get("ry"),
                 state.get("lt"), state.get("rt"))
        if before != after:
            changed = True
    return changed


def list_devices() -> list[dict]:
    """Gamepads com limites ABS (p/ normalizar sticks/gatilhos)."""
    try:
        from evdev import InputDevice, ecodes
        from backend import rumble
    except ImportError:
        return []
    out = []
    for p in rumble.find_gamepads():
        d = None
        try:
            d = InputDevice(p["path"])
            limits: dict[int, tuple[int, int]] = {}
            for code, info in d.capabilities(absinfo=True).get(ecodes.EV_ABS, []):
                limits[code] = (info.min, info.max)
            out.append({"path": p["path"], "name": p["name"],
                        "phys": getattr(d, "phys", "") or "",
                        "has_rumble": p.get("has_rumble", False),
                        "limits": limits})
        except OSError:
            out.append({"path": p["path"], "name": p["name"],
                        "phys": getattr(d, "phys", "") if d is not None else "",
                        "has_rumble": p.get("has_rumble", False),
                        "limits": {}})
        finally:
            if d is not None:
                try:
                    d.close()
                except OSError:
                    pass
    # real primeiro, virtual 360 por último (mesma regra do rumble)
    out.sort(key=lambda p: (rumble.is_virtual_pad(p["name"]), p["path"]))
    return out
