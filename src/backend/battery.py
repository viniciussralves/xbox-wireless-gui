"""Bateria via UPower (funciona p/ xone/xpadneo) + fallback sysfs.

UPower >= 1.90 expõe UPowerGlib.Device só via propriedades GObject
(props.model, props.percentage, ...), sem os antigos get_model() etc.
"""
from __future__ import annotations

from backend.i18n import _


def _kind_str(kind_int: int) -> str:
    try:
        import gi
        gi.require_version("UPowerGlib", "1.0")
        from gi.repository import UPowerGlib
        return UPowerGlib.Device.kind_to_string(kind_int) or str(kind_int)
    except Exception:  # noqa: BLE001
        return str(kind_int)


_STATE_PT = {
    "charging": _("Carregando"),
    "discharging": _("Descarregando"),
    "empty": _("Vazia"),
    "fully-charged": _("Carregada"),
    "fully charged": _("Carregada"),
    "full": _("Carregada"),
    "pending-charge": _("Carga pendente"),
    "pending-discharge": _("Descarga pendente"),
    "unknown": _("Desconhecida"),
}

_LEVEL_ICON = {
    "critical": "battery-caution-symbolic",
    "low": "battery-low-symbolic",
    "warning": "battery-low-symbolic",
    "normal": "battery-good-symbolic",
    "high": "battery-good-symbolic",
    "full": "battery-full-symbolic",
}


def _state_str(state_int: int) -> str:
    try:
        import gi
        gi.require_version("UPowerGlib", "1.0")
        from gi.repository import UPowerGlib
        return UPowerGlib.Device.state_to_string(state_int)
    except Exception:  # noqa: BLE001
        return str(state_int)


def translate_state(state_en: str) -> str:
    s = (state_en or "").strip().lower()
    return _STATE_PT.get(s, state_en or "")


def _level_pt(level_en: str) -> str:
    m = {
        "unknown": _("desconhecido"),
        "none": "—",
        "low": _("baixo"),
        "warning": _("baixo"),
        "critical": _("crítico"),
        "normal": _("normal"),
        "high": _("alto"),
        "full": _("cheio"),
    }
    return m.get((level_en or "").strip().lower(), level_en or "?")


def icon_for(pct: int, state_en: str, level_en: str) -> str:
    """Ícone calculado localmente: não confia no icon_name do UPower,
    que reporta battery-low a 55%% em alguns gamepads xone."""
    st = (state_en or "").lower()
    # "discharging" contém "charg" — checar descarga primeiro;
    # "fully-charged" contém "charg" — checar cheio antes de carregando
    if "discharg" in st:
        pass  # cai na lógica por percentual abaixo
    elif "full" in st:
        return "battery-full-charged-symbolic"
    elif "charg" in st:
        return "battery-good-charging-symbolic"
    if pct >= 0:
        if pct <= 15:
            return "battery-empty-symbolic"
        if pct <= 30:
            return "battery-low-symbolic"
        if pct >= 95:
            return "battery-full-symbolic"
        return "battery-good-symbolic"
    lvl = (level_en or "").lower()
    return _LEVEL_ICON.get(lvl, "battery-missing-symbolic")


def list_batteries() -> list[dict]:
    try:
        import gi
        gi.require_version("UPowerGlib", "1.0")
        from gi.repository import UPowerGlib
        client = UPowerGlib.Client.new()
        out = []
        for dev in client.get_devices():
            try:
                p = dev.props
                # pula o agregado DisplayDevice e fontes AC
                obj_path = dev.get_object_path() or ""
                if "DisplayDevice" in obj_path:
                    continue
                model = (p.model or "").strip()
                vendor = (p.vendor or "").strip()
                native = (p.native_path or "").strip()
                kind = _kind_str(p.kind) or ""
                text = f"{vendor} {model}".strip()
                is_gamepad = (
                    "gaming" in kind.lower()
                    or "gip" in native.lower()
                    or any(k in text.lower() for k in ("xbox", "gamepad", "controller"))
                )
                if not is_gamepad:
                    continue
                try:
                    import gi
                    gi.require_version("UPowerGlib", "1.0")
                    from gi.repository import UPowerGlib
                    level = UPowerGlib.Device.level_to_string(p.battery_level)
                except Exception:  # noqa: BLE001
                    level = str(p.battery_level)
                out.append({
                    "device": text or native or _("controle"),
                    "percentage": round(float(p.percentage)),
                    "state": translate_state(_state_str(p.state)),
                    "state_en": _state_str(p.state),
                    "kind": kind,
                    "level": _level_pt(level),
                    "level_en": level,
                    "native_path": native,
                    "serial": (p.serial or "").strip(),
                    "icon": icon_for(round(float(p.percentage)),
                                     _state_str(p.state), level),
                    "time_empty": int(p.time_to_empty or 0),
                    "time_full": int(p.time_to_full or 0),
                })
            except Exception:  # noqa: BLE001 (um dispositivo ruim não derruba os outros)
                continue
        return out
    except Exception as e:  # noqa: BLE001
        return [{"device": _("UPower indisponível"), "percentage": -1,
                 "state": str(e), "kind": "?", "level": "?",
                 "native_path": "", "serial": "", "icon": "",
                 "time_empty": 0, "time_full": 0}]
