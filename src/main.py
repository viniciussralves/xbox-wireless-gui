#!/usr/bin/env python3
"""Xbox Wireless GUI — GTK4 + Libadwaita, backend xone + xow (Fedora)."""
from __future__ import annotations
import argparse
import json
import math
import os
import sys
import threading
import time
from collections import deque
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib, Gdk  # noqa: E402

from backend import bluetooth, detector, firmware, permissions, prefs, updates
from backend import xone, xow, battery, rumble, inputs, audio, diagnostics, profiles
from backend import api, history, log, monitor, remap
from backend.rumble import is_virtual_pad
from backend.xone import VALID_LED_MODES
from backend import __version__ as APP_VERSION
from backend.i18n import _

APP_ID = "com.github.xbox-wireless-gui"
LOG = log.get_logger("main")


CSS = b"""
levelbar block { border-radius: 4px; min-height: 10px; }
levelbar block.filled { background: @success_bg_color; }
levelbar.warn block.filled { background: @warning_bg_color; }
levelbar.crit block.filled { background: @error_bg_color; }
.bat-pct { font-size: 14pt; font-weight: 800; }
.dim { font-size: 10pt; opacity: .75; }
.btn-std { min-width: 140px; min-height: 34px; border-radius: 9px; }
.btn-icon { min-width: 34px; min-height: 34px; border-radius: 9px; }

/* --- identidade visual / dashboard --- */
.hero {
    background-image: linear-gradient(135deg, alpha(@accent_bg_color, 0.20),
                                      alpha(@accent_bg_color, 0.03));
    border: 1px solid alpha(@accent_bg_color, 0.28);
    border-radius: 20px;
    padding: 22px;
}
.hero-icon {
    background: alpha(@accent_bg_color, 0.18);
    border-radius: 16px;
    padding: 12px;
}
.hero-title { font-size: 22pt; font-weight: 800; }
.hero-subtitle { font-size: 10.5pt; opacity: .78; }
.status-pill {
    border-radius: 999px;
    padding: 5px 12px;
    font-size: 9pt;
    font-weight: 700;
}
.status-pill.neutral { background: alpha(@card_bg_color, 0.85); }
.status-pill.ok { background: alpha(@success_bg_color, 0.20); color: @success_color; }
.status-pill.warn { background: alpha(@warning_bg_color, 0.22); color: @warning_color; }
.status-pill.err { background: alpha(@error_bg_color, 0.20); color: @error_color; }
.stat-card {
    background: alpha(@card_bg_color, 0.80);
    border: 1px solid alpha(@borders, 0.55);
    border-radius: 12px;
    padding: 10px 14px;
    min-width: 120px;
}
.stat-value { font-size: 16pt; font-weight: 800; }
.stat-label { font-size: 9pt; opacity: .70; }
.empty-card {
    background: alpha(@card_bg_color, 0.55);
    border: 1px dashed alpha(@borders, 0.85);
    border-radius: 18px;
    padding: 18px;
}
.battery-chip {
    border-radius: 999px;
    padding: 3px 9px;
    font-size: 9pt;
    font-weight: 700;
    background: alpha(@success_bg_color, 0.16);
}
.battery-chip.low { background: alpha(@warning_bg_color, 0.20); color: @warning_color; }
.battery-chip.crit { background: alpha(@error_bg_color, 0.20); color: @error_color; }
.quick-action { border-radius: 999px; padding: 8px 16px; font-weight: 700; }
.notification-bar {
    margin: 10px 18px 0 18px;
    padding: 11px 14px;
    border-radius: 12px;
    background: alpha(@card_bg_color, 0.96);
    border: 1px solid alpha(@borders, 0.65);
}
.notification-bar.info { border-left: 4px solid @accent_bg_color; }
.notification-bar.ok { border-left: 4px solid @success_color; }
.notification-bar.warn { border-left: 4px solid @warning_color; }
.notification-bar.err { border-left: 4px solid @error_color; }
.notification-title { font-weight: 700; }
.notification-detail { font-size: 9.5pt; opacity: .78; }
.panel {
    background: alpha(@card_bg_color, 0.65);
    border: 1px solid alpha(@borders, 0.55);
    border-radius: 16px;
    padding: 14px;
}
"""

# Escala única de fontes da interface: cada papel, um tamanho.
UI_FONT_CANVAS = 12      # todos os rótulos do desenho do controle
WINDOW_MARGIN = 18       # respiro externo padrão de janelas e páginas
WINDOW_SPACING = 12      # espaçamento vertical padrão
CONTENT_WIDTH = 860      # largura máxima do conteúdo principal


def window_header(title: str, subtitle: str = "") -> Adw.HeaderBar:
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title=title, subtitle=subtitle))
    return header


def content_clamp(child: Gtk.Widget, width: int = 760,
                  margin: int = WINDOW_MARGIN) -> Adw.Clamp:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                  spacing=WINDOW_SPACING)
    box.set_margin_top(margin)
    box.set_margin_bottom(margin)
    box.set_margin_start(margin)
    box.set_margin_end(margin)
    box.append(child)
    clamp = Adw.Clamp()
    clamp.set_maximum_size(width)
    clamp.set_tightening_threshold(max(320, width - 180))
    clamp.set_child(box)
    return clamp


def fmt_duration(sec: int) -> str:
    if sec is None or sec <= 0:
        return ""
    h, rem = divmod(int(sec), 3600)
    m = rem // 60
    if h:
        return f"{h}h{m:02d}"
    if m:
        return f"{m}min"
    return f"{int(sec)}s"


def bat_time_text(b: dict) -> str:
    st_en = (b.get("state_en") or b.get("state") or "").lower()
    st_pt = b.get("state") or ""
    # "discharging" contém "charg" — checar descarga primeiro
    if "discharg" in st_en and b.get("time_empty"):
        return _("{t} restantes").format(t=fmt_duration(b['time_empty']))
    if "full" in st_en:
        return _("carregado")
    if "charg" in st_en and b.get("time_full"):
        return _("cheio em {t}").format(t=fmt_duration(b['time_full']))
    # sem tempo estimado: mostra só o estado já traduzido
    return st_pt or ""


_LEVEL_PCT = {
    "full": 100,
    "high": 80,
    "normal": 60,
    "low": 30,
    "critical": 10,
    "none": 0,
}
_LEVEL_TEXT = {
    "full": _("cheio"),
    "high": _("alto"),
    "normal": _("normal"),
    "low": _("baixo"),
    "critical": _("crítico"),
}


def battery_is_reliable(b: dict) -> bool:
    try:
        return bool(b.get("is_reliable") or b.get("power_supply")) and \
            int(b.get("percentage", -1)) >= 0
    except (TypeError, ValueError):
        return False


def battery_pct(b: dict) -> int:
    """% exato quando confiável; estimativa pelo nível caso contrário."""
    try:
        pct = int(b.get("percentage", -1))
    except (TypeError, ValueError):
        pct = -1
    if battery_is_reliable(b):
        return pct
    est = _LEVEL_PCT.get((b.get("level_en") or "").strip().lower(), -1)
    return est if est >= 0 else pct


def battery_level_text(b: dict) -> str:
    lvl = (b.get("level_en") or "").strip().lower()
    return b.get("level") or _LEVEL_TEXT.get(lvl, "")


def connection_kind(pad_path: str | None, led_id: str | None) -> str:
    if led_id:
        return _("Dongle xone")
    if pad_path:
        try:
            if bluetooth.is_bluetooth(pad_path):
                return _("Bluetooth")
        except Exception:  # noqa: BLE001
            pass
        return _("USB/evdev")
    return _("desconhecido")


def power_index(led_id: str | None) -> int | None:
    """Extrai o índice do cliente xone de 'gip0.1:white:status' -> 1."""
    base = (led_id or "").split(":")[0]
    if not base.startswith("gip"):
        return None
    nums = base[3:].split(".")
    try:
        return int(nums[1]) if len(nums) >= 2 else int(nums[0])
    except (ValueError, IndexError):
        return None


def led_mode_label(mode: str) -> str:
    return {
        "0": _("Desligado"),
        "1": _("Ligado"),
        "2": _("Piscar rápido"),
        "3": _("Piscar normal"),
        "4": _("Piscar lento"),
        "8": _("Fade lento"),
        "9": _("Fade rápido"),
    }.get(mode, mode)


def a11y_label(widget, text: str):
    """Rótulo acessível para botões só de ícone."""
    try:
        widget.update_property([Gtk.AccessibleProperty.LABEL], [text])
    except Exception:  # noqa: BLE001
        pass


def style_bat_bar(bar: Gtk.LevelBar, pct: int):
    bar.set_value(pct)
    bar.remove_css_class("warn")
    bar.remove_css_class("crit")
    if pct <= 20:
        bar.add_css_class("crit")
    elif pct <= 50:
        bar.add_css_class("warn")


class NotificationBar(Gtk.Revealer):
    """Barra de notificação detalhada, com título, detalhe e ação."""

    KINDS = {
        "info": "dialog-information-symbolic",
        "ok": "emblem-ok-symbolic",
        "warn": "dialog-warning-symbolic",
        "err": "dialog-error-symbolic",
    }

    def __init__(self):
        super().__init__()
        self.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.set_transition_duration(180)
        self._timeout_id: int | None = None
        self._action_cb = None
        self._action_visible = False

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.add_css_class("notification-bar")
        box.add_css_class("info")
        self._box = box
        self._icon = Gtk.Image.new_from_icon_name(self.KINDS["info"])
        self._icon.set_pixel_size(20)
        self._icon.set_valign(Gtk.Align.START)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.set_hexpand(True)
        self._title = Gtk.Label()
        self._title.add_css_class("notification-title")
        self._title.set_halign(Gtk.Align.START)
        self._detail = Gtk.Label()
        self._detail.add_css_class("notification-detail")
        self._detail.set_halign(Gtk.Align.START)
        self._detail.set_wrap(True)
        self._detail.set_visible(False)
        text.append(self._title)
        text.append(self._detail)
        self._action = Gtk.Button()
        self._action.add_css_class("btn-std")
        self._action.set_valign(Gtk.Align.CENTER)
        self._action.set_visible(False)
        self._action.connect("clicked", self._on_action)
        close = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close.add_css_class("btn-icon")
        close.set_valign(Gtk.Align.CENTER)
        close.set_tooltip_text(_("Fechar"))
        a11y_label(close, _("Fechar notificação"))
        close.connect("clicked", lambda _b: self.set_revealed(False))
        box.append(self._icon)
        box.append(text)
        box.append(self._action)
        box.append(close)
        self.set_child(box)

    def _on_action(self, _b):
        if self._action_cb is not None:
            self._action_cb()
        self.set_revealed(False)

    def set_action(self, callback):
        self._action_cb = callback

    def set_button_label(self, label: str | None):
        self._action_visible = bool(label)
        self._action.set_visible(self._action_visible)
        if label:
            self._action.set_label(label)

    def set_title(self, text: str):
        self._title.set_text(text)

    def set_detail(self, text: str):
        self._detail.set_text(text)
        self._detail.set_visible(bool(text))

    def set_kind(self, kind: str):
        kind = kind if kind in self.KINDS else "info"
        for cls in ("info", "ok", "warn", "err"):
            self._box.remove_css_class(cls)
        self._box.add_css_class(kind)
        self._icon.set_from_icon_name(self.KINDS[kind])

    def set_revealed(self, revealed: bool):
        if self._timeout_id is not None:
            try:
                GLib.source_remove(self._timeout_id)
            except Exception:  # noqa: BLE001
                pass
            self._timeout_id = None
        self.set_reveal_child(bool(revealed))

    def get_revealed(self) -> bool:
        return bool(self.get_reveal_child())

    def show(self, title: str, detail: str = "", kind: str = "info",
             action_label: str | None = None, callback=None,
             timeout: int | None = None):
        self.set_kind(kind)
        self.set_title(title)
        self.set_detail(detail)
        self.set_button_label(action_label)
        if callback is not None:
            self.set_action(callback)
        self.set_revealed(True)
        if timeout:
            self._timeout_id = GLib.timeout_add_seconds(timeout, self._auto_hide)

    def _auto_hide(self):
        self._timeout_id = None
        self.set_reveal_child(False)
        return False


class ControllerCard(Adw.ExpanderRow):
    """Cartão expansível por controle: bateria + LED + vibração."""

    def __init__(self, title: str, subtitle: str, led_id: str | None,
                 window: "MainWindow", pad_path: str | None = None,
                 led_info: dict | None = None, serial: str | None = None,
                 connection: str | None = None,
                 custom_name: str | None = None):
        super().__init__(title=custom_name or title, subtitle=subtitle)
        self._win = window
        self.led_id = led_id
        self.pad_path = pad_path
        self.serial = (serial or "").strip()
        self.connection = connection or connection_kind(pad_path, led_id)
        self.power_index = power_index(led_id)
        self.add_prefix(Gtk.Image.new_from_icon_name("input-gaming-symbolic"))
        self.bat_chip = Gtk.Label(label="—")
        self.bat_chip.add_css_class("battery-chip")
        self.bat_chip.set_valign(Gtk.Align.CENTER)
        self.add_suffix(self.bat_chip)
        self.set_expanded(False)

        # --- informações / identificação ---
        info_parts = [self.connection]
        if self.serial:
            info_parts.append(_("serial {s}").format(s=self.serial))
        if pad_path:
            info_parts.append(pad_path)
        self.info_row = Adw.ActionRow(title=_("Informações"),
                                      subtitle=" • ".join(info_parts))
        self.info_row.set_activatable(False)
        if self.serial:
            rename_btn = Gtk.Button(label=_("Renomear"))
            rename_btn.add_css_class("btn-std")
            rename_btn.set_valign(Gtk.Align.CENTER)
            rename_btn.connect("clicked", self._on_rename)
            self.info_row.add_suffix(rename_btn)
        copy_btn = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        copy_btn.add_css_class("btn-icon")
        copy_btn.set_tooltip_text(_("Copiar informações do controle"))
        a11y_label(copy_btn, _("Copiar informações do controle"))
        copy_btn.add_css_class("btn-icon")
        copy_btn.set_valign(Gtk.Align.CENTER)
        copy_btn.connect("clicked", self._on_copy_info)
        self.info_row.add_suffix(copy_btn)
        self.add_row(self.info_row)

        # --- bateria ---
        self.bat_icon = Gtk.Image.new_from_icon_name("battery-missing-symbolic")
        self.bat_icon.set_pixel_size(28)
        self.bat_bar = Gtk.LevelBar(min_value=0, max_value=100)
        self.bat_bar.set_hexpand(True)
        self.bat_bar.set_valign(Gtk.Align.CENTER)
        self.bat_label = Gtk.Label()
        self.bat_label.add_css_class("bat-pct")
        self.bat_label.set_markup('<b>—</b>')
        bat_box = Gtk.Box(spacing=10)
        bat_box.append(self.bat_icon)
        bat_box.append(self.bat_bar)
        bat_box.append(self.bat_label)
        self.battery_native = ""
        hist_btn = Gtk.Button.new_from_icon_name("document-open-recent-symbolic")
        hist_btn.add_css_class("btn-icon")
        hist_btn.set_tooltip_text(_("Histórico de bateria"))
        a11y_label(hist_btn, _("Histórico de bateria"))
        hist_btn.add_css_class("btn-icon")
        hist_btn.set_valign(Gtk.Align.CENTER)
        hist_btn.connect("clicked", self._on_battery_history)
        bat_box.append(hist_btn)
        self.bat_row = Adw.ActionRow(title=_("Bateria"), subtitle=_("via UPower"))
        self.bat_row.add_suffix(bat_box)
        self.bat_row.set_activatable(False)
        self.add_row(self.bat_row)

        # --- LED (só xone com gip*) ---
        if led_id:
            info = led_info or next(
                (c for c in xone.list_controllers() if c["id"] == led_id), {})
            try:
                cur = int(info.get("brightness") or 0)
                mx = int(info.get("max_brightness") or 5)
            except ValueError:
                cur, mx = 0, 5
            cur_mode = str(info.get("mode") or "2")
            if cur_mode not in VALID_LED_MODES:
                cur_mode = "2"
            self.led_mode_list = Gtk.StringList.new(
                [led_mode_label(m) for m in VALID_LED_MODES])
            self.led_mode = Gtk.DropDown(model=self.led_mode_list)
            self.led_mode.set_selected(VALID_LED_MODES.index(cur_mode))
            self.led_mode.set_tooltip_text(
                _("Modo do LED (preserva o atual por padrão)"))
            self.led_mode.set_valign(Gtk.Align.CENTER)
            self.led_scale = Gtk.Scale.new_with_range(
                Gtk.Orientation.HORIZONTAL, 0, max(mx, 1), 1)
            self.led_scale.set_value(cur)
            self.led_scale.set_size_request(180, -1)
            self.led_scale.set_valign(Gtk.Align.CENTER)
            self.led_scale.set_draw_value(True)
            apply_btn = Gtk.Button(label=_("Aplicar"))
            apply_btn.add_css_class("suggested-action")
            apply_btn.add_css_class("btn-std")
            apply_btn.set_valign(Gtk.Align.CENTER)
            apply_btn.connect("clicked", self._on_led_apply)
            self.apply_btn = apply_btn
            led_box = Gtk.Box(spacing=8)
            led_box.append(self.led_mode)
            led_box.append(self.led_scale)
            led_box.append(apply_btn)
            led_row = Adw.ActionRow(
                title=_("Brilho do LED Xbox"),
                subtitle=_("mode atual: {mode} • ajuste modo + brilho e clique em Aplicar").format(
                    mode=info.get('mode', '?')))
            led_row.add_suffix(led_box)
            led_row.set_activatable(False)
            self.add_row(led_row)

        # --- energia: desligar o controle pelo sysfs do xone ---
        if self.power_index is not None:
            off_btn = Gtk.Button(label=_("Desligar"))
            off_btn.add_css_class("destructive-action")
            off_btn.add_css_class("btn-std")
            off_btn.set_valign(Gtk.Align.CENTER)
            off_btn.connect("clicked", self._on_poweroff)
            off_row = Adw.ActionRow(
                title=_("Desligar controle"),
                subtitle=_("envia poweroff ao dongle; religue com o botão Xbox"))
            off_row.add_suffix(off_btn)
            off_row.set_activatable(False)
            self.add_row(off_row)

        # --- vibração (teste dos dois motores separadamente) ---
        vib_btn = Gtk.Button(label=_("Vibrar"))
        vib_btn.add_css_class("btn-std")
        vib_btn.set_valign(Gtk.Align.CENTER)
        vib_btn.connect("clicked", self._on_vibrate)
        vib_box = Gtk.Box(spacing=6)
        vib_box.append(vib_btn)
        for motor, label in (("strong", _("Forte")), ("weak", _("Fraco"))):
            b = Gtk.Button(label=label)
            b.add_css_class("btn-std")
            b.set_valign(Gtk.Align.CENTER)
            b.connect("clicked", lambda _b, m=motor: self._on_vibrate_motor(m))
            vib_box.append(b)
        vib_row = Adw.ActionRow(title=_("Vibração"),
                                subtitle=_("testa os motores via evdev (ff-rumble)"))
        vib_row.add_suffix(vib_box)
        vib_row.set_activatable(False)
        self.add_row(vib_row)
        self._vib_btn = vib_btn

        # --- testador de botões (desenho do controle) ---
        test_btn = Gtk.Button(label=_("Testar botões"))
        test_btn.add_css_class("pill")
        test_btn.add_css_class("btn-std")
        test_btn.set_valign(Gtk.Align.CENTER)
        test_btn.connect("clicked", self._on_test_buttons)
        test_row = Adw.ActionRow(title=_("Testar botões"),
                                 subtitle=_("abre o desenho do controle ao vivo"))
        test_row.add_suffix(test_btn)
        test_row.set_activatable(False)
        self.add_row(test_row)

        # --- Bluetooth: desconectar ("esquecer") via MAC do phys ---
        if pad_path and bluetooth.is_bluetooth(pad_path):
            disc_btn = Gtk.Button(label=_("Desconectar"))
            disc_btn.add_css_class("btn-std")
            disc_btn.set_valign(Gtk.Align.CENTER)
            disc_btn.connect("clicked", self._on_disconnect)
            disc_row = Adw.ActionRow(title=_("Bluetooth"),
                                     subtitle=_("desconecta este controle (pode parear de novo depois)"))
            disc_row.add_suffix(disc_btn)
            disc_row.set_activatable(False)
            self.add_row(disc_row)

    def set_battery_info(self, b: dict):
        self.battery_native = (b.get("native_path") or b.get("serial") or "")
        pct = battery_pct(b)
        if pct < 0:
            self.bat_label.set_markup('<b>—</b>')
            self.bat_chip.set_text("—")
            self.bat_row.set_subtitle(_("sem dados"))
            return
        reliable = battery_is_reliable(b)
        style_bat_bar(self.bat_bar, pct)
        level_txt = battery_level_text(b)
        self.bat_chip.remove_css_class("low")
        self.bat_chip.remove_css_class("crit")
        if pct <= 20 or (b.get("level_en") or "").lower() in ("low", "critical"):
            self.bat_chip.add_css_class("crit" if pct <= 10 else "low")
        if reliable:
            self.bat_label.set_markup(f'<b>{pct}%</b>')
            self.bat_chip.set_text(f"{pct}%")
        else:
            self.bat_label.set_markup(f'<b>{level_txt or f"≈{pct}%"}</b>')
            self.bat_chip.set_text(level_txt or f"≈{pct}%")
        icon = b.get("icon") or "battery-good-symbolic"
        self.bat_icon.set_from_icon_name(icon)
        self.bat_icon.set_pixel_size(28)
        detail = bat_time_text(b)
        lvl = b.get("level") or ""
        state = b.get("state", "")
        # evita "Descarregando • nível normal • Descarregando"
        parts = [state, _("nível {lvl}").format(lvl=lvl)] if lvl and lvl != "—" else [state]
        if detail and detail != state:
            parts.append(detail)
        if not reliable:
            parts.append(_("estimativa pelo nível"))
        sub = " • ".join(s for s in parts if s)
        self.bat_row.set_subtitle(sub or _("via UPower"))

    def set_battery(self, pct: int, state: str):
        self.set_battery_info({"percentage": pct, "state": state,
                               "state_en": state, "is_reliable": True,
                               "level_en": "full" if pct >= 95 else "normal"})
        return

    def _on_led_apply(self, _b):
        if not self.led_id:
            return
        val = str(int(self.led_scale.get_value()))
        mode = None
        try:
            idx = int(self.led_mode.get_selected())
            if 0 <= idx < len(VALID_LED_MODES):
                mode = VALID_LED_MODES[idx]
        except Exception:  # noqa: BLE001
            mode = None
        if mode not in VALID_LED_MODES:
            # fallback: preserva o mode atual do sysfs em vez de forçar "2"
            try:
                cur = next((c for c in xone.list_controllers()
                            if c["id"] == self.led_id), {}).get("mode")
                mode = cur if cur in VALID_LED_MODES else "2"
            except Exception:  # noqa: BLE001
                mode = "2"
        led_id, led_mode, led_val = self.led_id, mode, val
        self.apply_btn.set_sensitive(False)

        def work():
            try:
                _ok, msg = xone.set_led(led_id, led_mode, led_val)
            except Exception as e:  # noqa: BLE001
                msg = str(e)
            GLib.idle_add(self._led_done, msg, led_mode)
        threading.Thread(target=work, daemon=True).start()

    def _led_done(self, msg: str, mode: str | None = None):
        self.apply_btn.set_sensitive(True)
        if self.serial and mode in VALID_LED_MODES:
            try:
                profiles.set_led(self.serial, mode,
                                 int(self.led_scale.get_value()))
            except Exception:  # noqa: BLE001
                pass
        self._win.toast(msg)
        return False

    def apply_saved_profile(self):
        """Reaplica o LED salvo quando o controle reconecta (xone reseta)."""
        if not (self.led_id and self.serial):
            return
        saved = profiles.led_of(self.serial)
        try:
            mode = str(saved.get("mode")) if saved.get("mode") is not None else ""
            brightness = int(saved.get("brightness")) if saved.get("brightness") is not None else -1
        except (TypeError, ValueError):
            return
        if mode not in VALID_LED_MODES or brightness < 0:
            return
        try:
            idx = VALID_LED_MODES.index(mode)
            self.led_mode.set_selected(idx)
            self.led_scale.set_value(brightness)
        except Exception:  # noqa: BLE001
            return
        threading.Thread(
            target=lambda: xone.set_led(self.led_id, mode, str(brightness)),
            daemon=True).start()

    def _on_battery_history(self, _b):
        if self.battery_native:
            self._win.show_battery_history(self.battery_native,
                                           self.get_title())

    def _on_poweroff(self, _b):
        if self.power_index is not None:
            self._win.poweroff_controller(self.power_index, self.led_id,
                                          self.get_title())

    def _on_rename(self, _b):
        if self.serial:
            self._win.rename_controller(self.serial, self.get_title())

    def _on_copy_info(self, _b):
        text = "\n".join([
            _("Controle: {n}").format(n=self.get_title()),
            _("Conexão: {c}").format(c=self.connection),
            _("Serial: {s}").format(s=self.serial or "—"),
            _("evdev: {p}").format(p=self.pad_path or "—"),
            _("LED: {l}").format(l=self.led_id or "—"),
        ])
        self._win.copy_text(text)

    def _on_vibrate(self, _b):
        if self.pad_path:
            self._win.vibrate_path(self.pad_path)
        else:
            self._win.vibrate_first()

    def _on_vibrate_motor(self, motor: str):
        if self.pad_path:
            self._win.vibrate_path(self.pad_path, motor=motor)
        else:
            self._win.vibrate_first(motor=motor)

    def _on_test_buttons(self, _b):
        self._win.open_tester(self.pad_path)

    def _on_disconnect(self, _b):
        if self.pad_path:
            self._win.disconnect_bt(self.pad_path)


class TesterWindow(Adw.Window):
    """Testador de botões: desenho do controle Xbox com destaque ao vivo via evdev."""

    def __init__(self, parent: Gtk.Window, initial_path: str | None = None):
        super().__init__(transient_for=parent, title=_("Testar controle"))
        self.set_default_size(680, 640)
        self._dev = None
        self._limits: dict[int, tuple[int, int]] = {}
        self._state = inputs.new_state()
        self._watch_id: int | None = None
        self._devices: list[dict] = []
        self._raw: deque[str] = deque(maxlen=14)
        self._prefs = prefs.get_prefs()

        header = window_header(_("Testar controle"),
                               _("aperte os botões do controle"))
        reload_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        reload_btn.add_css_class("btn-icon")
        reload_btn.set_tooltip_text(_("Procurar gamepads novamente"))
        a11y_label(reload_btn, _("Procurar gamepads novamente"))
        reload_btn.connect("clicked", lambda *_a: self._reload_devices(None))
        header.pack_start(reload_btn)
        copy_btn = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        copy_btn.add_css_class("btn-icon")
        copy_btn.set_tooltip_text(_("Copiar estado atual"))
        a11y_label(copy_btn, _("Copiar estado atual"))
        copy_btn.connect("clicked", self._on_copy_state)
        header.pack_end(copy_btn)

        self.dev_list = Gtk.StringList()
        self.dropdown = Gtk.DropDown(model=self.dev_list)
        self.dropdown.set_tooltip_text(_("Dispositivo de entrada"))
        self._loading_devices = False
        self.dropdown.connect("notify::selected", self._on_device_selected)
        dev_row = Adw.ActionRow(title=_("Controle"))
        dev_row.add_suffix(self.dropdown)
        dev_row.set_activatable(False)

        self.area = Gtk.DrawingArea()
        self.area.set_content_width(520)
        self.area.set_content_height(360)
        self.area.set_hexpand(True)
        self.area.set_vexpand(False)
        self.area.set_halign(Gtk.Align.CENTER)
        self.area.set_valign(Gtk.Align.CENTER)
        self.area.set_draw_func(self._draw, None)
        self.area.set_accessible_role(Gtk.AccessibleRole.IMG)
        self.area.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [_("Desenho do controle Xbox com botões e eixos ao vivo")])
        self.area.update_property(
            [Gtk.AccessibleProperty.DESCRIPTION],
            [_("Use o testador para conferir botões, gatilhos e analógicos")])

        self.status_label = Gtk.Label(label=_("Nenhum botão pressionado"))
        self.status_label.add_css_class("dim")
        self.status_label.set_wrap(True)
        self.axis_label = Gtk.Label(label="LX 0.00  LY 0.00  •  RX 0.00  RY 0.00  •  LT 0%  RT 0%")
        self.axis_label.add_css_class("dim")
        self.axis_label.set_wrap(True)

        settings_group = Adw.PreferencesGroup(
            title=_("Leitura"),
            description=_("Escolha o controle e ajuste a zona morta"))
        settings_group.add(dev_row)
        # zona morta dos analógicos (só afeta o testador)
        self.dz_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.0, 0.5, 0.01)
        self.dz_scale.set_value(self._prefs.get_double("tester-deadzone"))
        self.dz_scale.set_draw_value(True)
        self.dz_scale.set_size_request(180, -1)
        self.dz_scale.set_valign(Gtk.Align.CENTER)
        self.dz_scale.set_tooltip_text(_("Ignora tremores pequenos dos analógicos"))
        self.dz_scale.connect("value-changed", self._on_deadzone)
        dz_row = Adw.ActionRow(title=_("Zona morta"),
                               subtitle=_("vale só para o desenho do testador"))
        dz_row.add_suffix(self.dz_scale)
        dz_row.set_activatable(False)
        settings_group.add(dz_row)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.append(settings_group)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        panel.add_css_class("panel")
        panel.append(self.area)
        panel.append(self.status_label)
        panel.append(self.axis_label)
        self.raw_label = Gtk.Label(label=_("eventos evdev aparecem aqui"))
        self.raw_label.add_css_class("dim")
        self.raw_label.set_wrap(True)
        self.raw_label.set_selectable(True)
        panel.append(self.raw_label)
        content.append(panel)
        # mapeamento evdev → botão (referência estática)
        try:
            from evdev import ecodes as _ec
            _rev: dict[int, str] = {}
            for _attr in dir(_ec):
                if _attr.startswith(("BTN_", "ABS_HAT")):
                    _rev.setdefault(getattr(_ec, _attr), _attr)
            map_exp = Adw.ExpanderRow(title=_("Mapeamento"),
                                      subtitle=_("código evdev → botão do desenho"))
            for _code, _name in sorted(inputs.key_map().items(),
                                       key=lambda kv: kv[1]):
                _row = Adw.ActionRow(title=_name.upper(),
                                     subtitle=str(_rev.get(_code, _code)))
                _row.set_activatable(False)
                map_exp.add_row(_row)
            map_group = Adw.PreferencesGroup(title=_("Referência evdev"))
            map_group.add(map_exp)
            content.append(map_group)
        except ImportError:
            pass
        hint = Gtk.Label(label=_("Dica: o dispositivo virtual “X-Box 360 pad” espelha o real — teste no “Microsoft Xbox Controller”."))
        hint.add_css_class("dim")
        hint.set_wrap(True)
        content.append(hint)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.append(header)
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(content_clamp(content, 760))
        body.append(scrolled)
        self.set_content(body)
        self.connect("close-request", self._on_close)

        self._reload_devices(initial_path)

    # ---- dispositivos ----
    def _reload_devices(self, initial_path: str | None = None):
        self._loading_devices = True  # ignora notify::selected durante a recarga
        try:
            self._devices = inputs.list_devices()
            self.dev_list.splice(0, self.dev_list.get_n_items(),
                                 [f"{d['name']}  ({d['path']})" for d in self._devices])
            idx = 0
            if initial_path:
                for i, d in enumerate(self._devices):
                    if d["path"] == initial_path:
                        idx = i
                        break
            else:
                for i, d in enumerate(self._devices):
                    if not is_virtual_pad(d.get("name")):
                        idx = i
                        break
            if self._devices:
                self.dropdown.set_selected(idx)
        finally:
            self._loading_devices = False
        # abertura única e explícita (set_selected acima foi ignorado de propósito)
        if self._devices:
            self._open(self._devices[idx]["path"])
        else:
            self._stop()
            self.status_label.set_text(_("Nenhum gamepad evdev encontrado (python3-evdev instalado?)"))

    def _on_device_selected(self, dd, _pspec):
        if self._loading_devices:
            return  # recarga em andamento; _reload_devices abre explicitamente
        i = dd.get_selected()
        if 0 <= i < len(self._devices):
            self._open(self._devices[i]["path"])

    def _deadzone(self) -> float:
        try:
            return max(0.0, min(0.5, float(self._prefs.get_double("tester-deadzone"))))
        except Exception:  # noqa: BLE001
            return 0.0

    def _on_deadzone(self, scale):
        try:
            self._prefs.set_double("tester-deadzone", float(scale.get_value()))
        except Exception:  # noqa: BLE001
            pass

    def _stop(self):
        if self._watch_id is not None:
            try:
                GLib.source_remove(self._watch_id)
            except Exception:  # noqa: BLE001
                pass
            self._watch_id = None
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:  # noqa: BLE001
                pass
            self._dev = None
        self._state["connected"] = False

    def _on_close(self, *_args):
        self._stop()
        return False

    def _open(self, path: str):
        self._stop()
        try:
            from evdev import InputDevice
        except ImportError:
            self.status_label.set_text(_("python3-evdev não instalado"))
            return
        try:
            dev = InputDevice(path)
            try:
                os.set_blocking(dev.fd, False)
            except Exception:  # noqa: BLE001
                pass
            limits = next((d["limits"] for d in self._devices if d["path"] == path), {})
            self._dev = dev
            self._limits = limits
            self._state = inputs.new_state(dev.name, path)
            self._state["connected"] = True
            # lê posição inicial dos eixos
            try:
                for code, (lo, hi) in limits.items():
                    try:
                        val = dev.absinfo(code).value
                    except OSError:
                        continue
                    inputs.apply_abs(self._state, code, val, limits,
                                     self._deadzone())
            except Exception:  # noqa: BLE001
                pass
            self._watch_id = GLib.io_add_watch(dev.fd, GLib.IO_IN, self._on_io)
            self.status_label.set_text(_("Lendo {name} — aperte os botões…").format(name=dev.name))
            self.area.queue_draw()
        except PermissionError:
            self.status_label.set_text(
                _("Sem permissão em {path} (uaccess/udev ou grupo xboxwireless)").format(path=path))
        except OSError as e:
            self.status_label.set_text(_("Falha ao abrir {path}: {e}").format(path=path, e=e))

    def _on_io(self, _fd, _cond):
        if self._dev is None:
            return False
        try:
            from evdev import ecodes
            changed = False
            logged = False
            # limita o lote para não monopolizar a thread da UI
            for _n in range(512):
                try:
                    ev = self._dev.read_one()
                except BlockingIOError:
                    break
                except OSError:
                    self.status_label.set_text(_("Dispositivo desconectado"))
                    self._state["connected"] = False
                    self._watch_id = None
                    try:
                        self._dev.close()
                    except OSError:
                        pass
                    self._dev = None
                    return False
                if ev is None:
                    break
                if ev.type == ecodes.EV_SYN:
                    # SYN_DROPPED = buffer transbordou, eventos perdidos:
                    # ressincroniza tudo em vez de deixar botão "grudado"
                    if ev.code == ecodes.SYN_DROPPED:
                        if inputs.resync(self._state, self._dev,
                                         self._limits, self._deadzone()):
                            changed = True
                    continue
                if ev.type == ecodes.EV_KEY:
                    name = inputs.code_name(ev.code)
                    self._raw.append(f"KEY {name}={ev.value}")
                    logged = True
                    if inputs.apply_key(self._state, ev.code, ev.value):
                        changed = True
                elif ev.type == ecodes.EV_ABS:
                    name = ecodes.bytype.get(ecodes.EV_ABS, {}).get(
                        ev.code, str(ev.code))
                    self._raw.append(f"ABS {name}={ev.value}")
                    logged = True
                    if inputs.apply_abs(self._state, ev.code, ev.value,
                                        self._limits, self._deadzone()):
                        changed = True
            if logged:
                self.raw_label.set_text("\n".join(self._raw))
            if changed:
                self._update_labels()
                self.area.queue_draw()
        except Exception as e:  # noqa: BLE001
            self.status_label.set_text(_("Erro de leitura: {e}").format(e=e))
            self._state["connected"] = False
            self._watch_id = None
            if self._dev is not None:
                try:
                    self._dev.close()
                except OSError:
                    pass
                self._dev = None
            return False
        return True

    def _update_labels(self):
        names = inputs.pressed_names(self._state)
        if names:
            self.status_label.set_text(_("Pressionados: {n}").format(
                n="  ".join(n.upper() for n in names)))
        else:
            hx, hy = self._state.get("hat", (0, 0))
            if hx or hy:
                self.status_label.set_text(
                    _("D-Pad: x={x:+d} y={y:+d}").format(x=hx, y=hy))
            else:
                self.status_label.set_text(_("Nenhum botão pressionado"))
        s = self._state
        self.axis_label.set_text(
            f"LX {s['lx']:+.2f}  LY {s['ly']:+.2f}  •  "
            f"RX {s['rx']:+.2f}  RY {s['ry']:+.2f}  •  "
            f"LT {s['lt']:.0%}  RT {s['rt']:.0%}")

    def _on_copy_state(self, _b):
        s = self._state
        text = "\n".join([
            _("Dispositivo: {n} ({p})").format(n=s.get("name", "?"),
                                               p=s.get("path", "?")),
            _("Pressionados: {n}").format(n=" ".join(inputs.pressed_names(s)) or "—"),
            f"LX {s['lx']:+.2f} LY {s['ly']:+.2f} "
            f"RX {s['rx']:+.2f} RY {s['ry']:+.2f} "
            f"LT {s['lt']:.0%} RT {s['rt']:.0%}",
            _("Últimos eventos:") + "\n" + ("\n".join(self._raw) or "—"),
        ])
        try:
            provider = Gdk.ContentProvider.new_for_bytes(
                "text/plain;charset=utf-8", GLib.Bytes.new(text.encode()))
            self.get_clipboard().set_content(provider)
        except Exception:  # noqa: BLE001
            pass

    # ---- desenho minimalista: grade quadrada, sem silhueta ----
    def _draw(self, _area, cr, w: int, h: int, _data):
        s = self._state
        # cor do tema (funciona no claro e no escuro)
        try:
            fg = _area.get_style_context().get_color()
            FR, FG, FB = fg.red, fg.green, fg.blue
        except Exception:  # noqa: BLE001
            FR, FG, FB = 0.55, 0.55, 0.57
        THIN, BOLD = 1.6, 3.2
        ON = (0.19, 0.82, 0.35)  # verde do botão acionado
        # padrão único: retangular, borda arredondada, simétrico
        BTN_W, BTN_H, BTN_R = 44, 32, 8

        scale = min(w / 520.0, h / 360.0)
        cr.save()
        cr.translate((w - 520 * scale) / 2.0, (h - 360 * scale) / 2.0)
        cr.scale(scale, scale)
        cr.set_line_cap(1)  # round
        cr.set_line_join(1)  # round

        def stroke(on: bool = False):
            if on:
                # botão acionado: halo translúcido + traço sólido (efeito "aceso")
                lw = cr.get_line_width()
                saved = cr.copy_path()
                cr.set_source_rgba(*ON, 0.22)
                cr.set_line_width(lw + 7)
                cr.stroke()
                cr.append_path(saved)
                cr.set_line_width(lw)
                cr.set_source_rgb(*ON)
                cr.stroke()
            else:
                cr.set_source_rgb(FR, FG, FB)
                cr.stroke()

        def text(x, y, label, size=UI_FONT_CANVAS, on: bool = False):
            cr.new_path()  # show_text deixa current-point; isola o caminho
            if on:
                cr.set_source_rgb(*ON)
            else:
                cr.set_source_rgb(FR, FG, FB)
            cr.set_font_size(size)
            ext = cr.text_extents(label)
            cr.move_to(x - ext.width / 2 - ext.x_bearing, y + ext.height / 2)
            cr.show_text(label)

        def rrect(x, y, w_, h_, r):
            """Retângulo padrão com borda arredondada."""
            r = min(r, w_ / 2.0, h_ / 2.0)
            cr.new_path()
            cr.move_to(x + r, y)
            cr.line_to(x + w_ - r, y)
            cr.arc(x + w_ - r, y + r, r, -math.pi / 2, 0)
            cr.line_to(x + w_, y + h_ - r)
            cr.arc(x + w_ - r, y + h_ - r, r, 0, math.pi / 2)
            cr.line_to(x + r, y + h_)
            cr.arc(x + r, y + h_ - r, r, math.pi / 2, math.pi)
            cr.line_to(x, y + r)
            cr.arc(x + r, y + r, r, math.pi, math.pi * 1.5)
            cr.close_path()

        def rbutton(x, y, w_=None, h_=None, label="", active=False, size=UI_FONT_CANVAS):
            """Botão retangular padrão; ativo ganha anel interno verde."""
            w_ = BTN_W if w_ is None else w_
            h_ = BTN_H if h_ is None else h_
            cr.new_path()
            cr.set_line_width(BOLD if active else THIN)
            rrect(x, y, w_, h_, BTN_R)
            stroke(active)
            if active:
                cr.set_line_width(1.2)
                rrect(x + 4, y + 4, w_ - 8, h_ - 8, max(BTN_R - 3, 2))
                stroke(True)
            text(x + w_ / 2, y + h_ / 2 + 0.5, label, size, active)

        # ---- LT / RT (barras arredondadas, simétricas) ----
        for i, (key, x) in enumerate((("lt", 40), ("rt", 370))):
            v = s["lt"] if key == "lt" else s["rt"]
            on = v > 0.05
            cr.new_path()
            cr.set_line_width(BOLD if on else THIN)
            rrect(x, 26, 110, 14, 7)
            stroke(on)
            if v > 0.01:
                cr.new_path()
                cr.set_line_width(2.0)
                cr.move_to(x + 6, 33)
                cr.line_to(x + 6 + 98 * v, 33)
                stroke(True)
            text(x + 55, 14, f"LT {s['lt']:.0%}" if i == 0 else f"RT {s['rt']:.0%}", UI_FONT_CANVAS, on)

        # ---- LB / View / Xbox / Menu / RB (padrão 44x32, simétricos) ----
        rbutton(60, 58, label="LB", active=s["lb"])
        rbutton(416, 58, label="RB", active=s["rb"])
        # Xbox: retangular + X centralizado
        cr.new_path()
        cr.set_line_width(BOLD if s["xbox"] else THIN)
        rrect(238, 58, BTN_W, BTN_H, BTN_R)
        stroke(s["xbox"])
        for x1, y1, x2, y2 in ((249, 66, 271, 82), (271, 66, 249, 82)):
            cr.new_path()
            cr.set_line_width(BOLD if s["xbox"] else THIN)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            stroke(s["xbox"])
        # View: retangular + dois quadradinhos
        cr.new_path()
        cr.set_line_width(BOLD if s["back"] else THIN)
        rrect(172, 62, BTN_W, BTN_H, BTN_R)
        stroke(s["back"])
        for qx, qy in ((187, 71), (191, 75)):
            cr.set_line_width(1.2)
            rrect(qx, qy, 7, 7, 2)
            stroke(s["back"])
        # Menu: retangular + hambúrguer
        cr.new_path()
        cr.set_line_width(BOLD if s["start"] else THIN)
        rrect(304, 62, BTN_W, BTN_H, BTN_R)
        stroke(s["start"])
        for yy in (71, 78, 85):
            cr.new_path()
            cr.set_line_width(1.4)
            cr.move_to(314, yy)
            cr.line_to(336, yy)
            stroke(s["start"])

        # ---- analógicos: poço + botão retangular padrão ----
        for key, wx, wy, ax, ay in (("l3", 40, 118, "lx", "ly"),
                                     ("r3", 200, 225, "rx", "ry")):
            on = bool(s[key])
            cr.new_path()
            cr.set_line_width(BOLD if on else THIN)
            cr.rectangle(wx, wy, 115, 115)
            stroke(on)
            cx, cy = wx + 57.5, wy + 57.5
            cr.new_path()  # mira central
            cr.set_line_width(1.0)
            cr.move_to(cx - 12, cy)
            cr.line_to(cx + 12, cy)
            cr.move_to(cx, cy - 12)
            cr.line_to(cx, cy + 12)
            stroke(on)
            kx = cx + s[ax] * 24
            ky = cy + s[ay] * 24
            cr.new_path()
            cr.set_line_width(2.2 if on else THIN)
            rrect(kx - 20, ky - 16, 40, 32, 8)
            stroke(on)

        # ---- D-Pad: cruz de retangulares padrão ----
        dx, dy, g = 74, 282, 6
        for ox, oy, hv in ((0, -(BTN_H + g), (0, -1)),
                           (0, BTN_H + g, (0, 1)),
                           (-(BTN_W + g), 0, (-1, 0)),
                           (BTN_W + g, 0, (1, 0)),
                           (0, 0, None)):
            hx, hy = s.get("hat", (0, 0))
            on = (hx, hy) == hv if hv else False
            cr.new_path()
            cr.set_line_width(BOLD if on else THIN)
            rrect(dx + ox, dy + oy, BTN_W, BTN_H, BTN_R)
            stroke(on)
        cr.new_path()  # miolo
        cr.set_source_rgb(FR, FG, FB)
        cr.rectangle(dx + BTN_W / 2 - 2, dy + BTN_H / 2 - 2, 4, 4)
        cr.fill()

        # ---- ABXY: losango de retangulares padrão ----
        rbutton(405, 124, label="Y", active=s["y"])
        rbutton(363, 166, label="X", active=s["x"])
        rbutton(447, 166, label="B", active=s["b"])
        rbutton(405, 208, label="A", active=s["a"])

        # ---- Share (pílula + seta; acende se o driver expuser) ----
        share_on = bool(s.get("share"))
        cr.new_path()
        cr.set_line_width(BOLD if share_on else THIN)
        cx, cy, hw, hh = 387, 297, 33, 12
        cr.move_to(cx - hw + hh, cy - hh)
        cr.line_to(cx + hw - hh, cy - hh)
        cr.arc(cx + hw - hh, cy, hh, -math.pi / 2, math.pi / 2)
        cr.line_to(cx - hw + hh, cy + hh)
        cr.arc(cx - hw + hh, cy, hh, math.pi / 2, math.pi * 1.5)
        cr.close_path()
        stroke(share_on)
        cr.new_path()
        cr.set_line_width(1.4)
        cr.move_to(cx, cy + 5)
        cr.line_to(cx, cy - 5)
        cr.move_to(cx - 4, cy - 1)
        cr.line_to(cx, cy - 6)
        cr.line_to(cx + 4, cy - 1)
        stroke(share_on)

        cr.restore()


class BatteryHistoryWindow(Adw.Window):
    """Gráfico simples do histórico de carga de um controle (UPower)."""

    def __init__(self, parent: Gtk.Window, native_path: str, device: str):
        super().__init__(transient_for=parent,
                         title=_("Histórico de bateria"))
        self.set_default_size(680, 500)
        self.native_path = native_path
        self.device = device
        self.rows = history.get_history(native_path, hours=24)
        header = window_header(_("Histórico de bateria"), device)
        copy_btn = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        copy_btn.add_css_class("btn-icon")
        copy_btn.set_tooltip_text(_("Copiar resumo"))
        copy_btn.connect("clicked", self._on_copy)
        header.pack_end(copy_btn)
        self.area = Gtk.DrawingArea()
        self.area.set_content_width(560)
        self.area.set_content_height(240)
        self.area.set_hexpand(True)
        self.area.set_vexpand(True)
        self.area.set_draw_func(self._draw, None)
        self.area.set_accessible_role(Gtk.AccessibleRole.IMG)
        self.area.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [_("Histórico de bateria de {d}").format(d=device)])
        s = history.summarize(self.rows)
        self.summary = Gtk.Label()
        self.summary.set_wrap(True)
        if s["count"]:
            self.summary.set_text(
                _("{n} amostras • mínimo {mn:.0f}% • máximo {mx:.0f}% • "
                  "último {last:.0f}%").format(
                      n=s["count"], mn=s["min"], mx=s["max"],
                      last=s["last"]))
        else:
            self.summary.set_text(_("sem histórico do UPower"))
        self.summary.add_css_class("dim")
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        panel.add_css_class("panel")
        panel.append(self.area)
        panel.append(self.summary)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.append(header)
        body.append(content_clamp(panel, 680))
        self.set_content(body)

    def _on_copy(self, _b):
        s = history.summarize(self.rows)
        text = _("{d}: {n} amostras, mínimo {mn}%, máximo {mx}%, último {last}%").format(
            d=self.device, n=s["count"], mn=s["min"], mx=s["max"],
            last=s["last"])
        try:
            provider = Gdk.ContentProvider.new_for_bytes(
                "text/plain;charset=utf-8", GLib.Bytes.new(text.encode()))
            self.get_clipboard().set_content(provider)
        except Exception:  # noqa: BLE001
            pass

    def _draw(self, _area, cr, w: int, h: int, _data):
        try:
            fg = _area.get_style_context().get_color()
            FR, FG, FB = fg.red, fg.green, fg.blue
        except Exception:  # noqa: BLE001
            FR, FG, FB = 0.6, 0.6, 0.6
        cr.set_source_rgba(FR, FG, FB, 0.35)
        cr.set_line_width(1.0)
        x, y = 24, 16
        bw, bh, br = max(10, w - 48), max(10, h - 48), 12
        cr.new_path()
        cr.move_to(x + br, y)
        cr.line_to(x + bw - br, y)
        cr.arc(x + bw - br, y + br, br, -math.pi / 2, 0)
        cr.line_to(x + bw, y + bh - br)
        cr.arc(x + bw - br, y + bh - br, br, 0, math.pi / 2)
        cr.line_to(x + br, y + bh)
        cr.arc(x + br, y + bh - br, br, math.pi / 2, math.pi)
        cr.line_to(x, y + br)
        cr.arc(x + br, y + br, br, math.pi, math.pi * 1.5)
        cr.close_path()
        cr.stroke()
        if not self.rows:
            return
        vals = [max(0.0, min(100.0, r["value"])) for r in self.rows]
        n = len(vals)
        cr.set_line_width(2.2)
        cr.set_source_rgb(0.19, 0.82, 0.35)
        for i, v in enumerate(vals):
            x = 24 + (w - 48) * (i / max(1, n - 1))
            y = h - 24 - (h - 48) * (v / 100.0)
            if i == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="Xbox Wireless GUI")
        self.set_default_size(760, 720)
        self._prefs = prefs.get_prefs()
        self._dongles: list[str] = []
        self._pair_since: float | None = None
        self._xow_countdown_id: int | None = None
        self._xow_left: int = 0
        self._fw_busy = False
        self._pair_busy = False
        self._driver_name_cached = ""
        self._perm_checked_at = 0.0
        self._last_conn: set[str] | None = None
        self._low_notified: set[str] = set()
        self._applied_profiles: set[str] = set()
        self._pair_auto_id: int | None = None
        self._audio_rows: list[Adw.ActionRow] = []
        self._bt_rows: list[Adw.ActionRow] = []
        self._fs_monitor = None
        self._up_monitor = None
        self._event_refresh_id: int | None = None
        self._fw_state = ""

        css = Gtk.CssProvider()
        css.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # ---- header ----
        header = window_header("Xbox Wireless", _("Central de controle"))
        menu = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu.add_css_class("btn-icon")
        a11y_label(menu, _("Menu"))
        pop = Gio.Menu()
        pop.append(_("Diagnóstico"), "app.diagnostics")
        pop.append(_("Sobre"), "app.about")
        menu.set_menu_model(pop)
        header.pack_end(menu)
        self.refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self.refresh_btn.add_css_class("btn-icon")
        self.refresh_btn.set_tooltip_text(_("Atualizar"))
        a11y_label(self.refresh_btn, _("Atualizar"))
        self.refresh_btn.add_css_class("btn-icon")
        self.refresh_btn.set_valign(Gtk.Align.CENTER)
        self.refresh_btn.connect("clicked", self.on_refresh)
        header.pack_start(self.refresh_btn)
        about_act = Gio.SimpleAction.new("about", None)
        about_act.connect("activate", self._on_about)
        app.add_action(about_act)
        diag_act = Gio.SimpleAction.new("diagnostics", None)
        diag_act.connect("activate", self._on_diagnostics)
        app.add_action(diag_act)
        self._install_shortcuts()

        # ---- barra de notificação detalhada ----
        self.banner = NotificationBar()
        self.banner.set_action(self._on_banner_button)
        self.banner.set_revealed(False)
        self._banner_mode = ""

        # ---- páginas / abas ----
        home_page = Adw.PreferencesPage()
        controls_page = Adw.PreferencesPage()
        audio_page = Adw.PreferencesPage()
        settings_page = Adw.PreferencesPage()

        # Grupo adaptador
        g_ad = Adw.PreferencesGroup(
            title=_("Conexão"),
            description=_("Adaptador, pairing e energia em um só lugar"))
        self.driver_row = Adw.ActionRow(title=_("Detectando…"))
        self.driver_row.add_prefix(Gtk.Image.new_from_icon_name("usb-symbolic"))
        g_ad.add(self.driver_row)

        # Seletor de dongle (só aparece com 2+ adaptadores)
        self.dongle_list = Gtk.StringList()
        self.dongle_drop = Gtk.DropDown(model=self.dongle_list)
        self.dongle_drop.set_tooltip_text(_("Qual dongle usar para pairing/LED"))
        self.dongle_drop.set_valign(Gtk.Align.CENTER)
        self.dongle_drop.connect("notify::selected", self._on_dongle_selected)
        self.dongle_row = Adw.ActionRow(title=_("Dongle"))
        self.dongle_row.add_suffix(self.dongle_drop)
        self.dongle_row.set_activatable(False)
        self.dongle_row.set_visible(False)
        g_ad.add(self.dongle_row)

        self.pair_switch = Adw.SwitchRow(title=_("Parear controle"),
                                         subtitle=_("deixe o adaptador visível para novos controles"))
        self.pair_switch.connect("notify::active", self._on_pair_switch)
        g_ad.add(self.pair_switch)

        self.pair_btn_box = Gtk.Box(spacing=8, homogeneous=True)
        self.pair_btn = Gtk.Button(label=_("Parear (xow)"))
        self.pair_btn.add_css_class("suggested-action")
        self.pair_btn.add_css_class("btn-std")
        self.pair_btn.set_valign(Gtk.Align.CENTER)
        self.pair_btn.connect("clicked", self.on_pair)
        self.pair_btn_box.append(self.pair_btn)
        pair_wrap = Adw.ActionRow(title=_("Parear (xow)"))
        pair_wrap.add_suffix(self.pair_btn_box)
        pair_wrap.set_activatable(False)
        self.pair_manual_row = pair_wrap
        g_ad.add(pair_wrap)

        self.clients_row = Adw.ActionRow(title=_("Conectados"),
                                         subtitle=_("—"))
        self.clients_row.set_activatable(False)
        g_ad.add(self.clients_row)

        off_all = Gtk.Button(label=_("Desligar todos"))
        off_all.add_css_class("destructive-action")
        off_all.add_css_class("btn-std")
        off_all.set_valign(Gtk.Align.CENTER)
        off_all.connect("clicked", self._on_poweroff_all)
        self.poweroff_all_row = Adw.ActionRow(
            title=_("Desligar todos"),
            subtitle=_("desliga todos os clientes wireless do dongle"))
        self.poweroff_all_row.add_suffix(off_all)
        self.poweroff_all_row.set_activatable(False)
        g_ad.add(self.poweroff_all_row)

        self.wakeup_switch = Adw.SwitchRow(
            title=_("Acordar o PC"),
            subtitle=_("habilita wakeup no adaptador USB (xone)"))
        self.wakeup_switch.connect("notify::active", self._on_wakeup_switch)
        g_ad.add(self.wakeup_switch)
        home_page.add(g_ad)

        # Grupo controles
        self.g_ctrl = Adw.PreferencesGroup(
            title=_("Seus controles"),
            description=_("Conectados ao adaptador • expanda para ajustes"))
        self.empty_status = Adw.StatusPage(
            icon_name="input-gaming-symbolic",
            title=_("Nenhum controle conectado"),
            description=_("Ative o pairing e segure o botão Xbox até piscar rápido."))
        steps = Gtk.Label(label=_("1. Ative o pareamento\n"
                                  "2. Segure o botão Xbox até o LED piscar rápido"))
        steps.add_css_class("dim")
        steps.set_justify(Gtk.Justification.CENTER)
        self.empty_btn = Gtk.Button(label=_("Conectar um controle"))
        self.empty_btn.add_css_class("suggested-action")
        self.empty_btn.add_css_class("btn-std")
        self.empty_btn.set_valign(Gtk.Align.CENTER)
        self.empty_btn.set_halign(Gtk.Align.CENTER)
        self.empty_btn.connect("clicked", self.on_pair)
        # StatusPage sem child direto: embrulha botão numa box
        empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        empty_box.set_halign(Gtk.Align.CENTER)
        empty_box.add_css_class("empty-card")
        empty_box.set_margin_top(8)
        empty_box.set_margin_bottom(8)
        empty_box.append(self.empty_status)
        empty_box.append(steps)
        empty_box.append(self.empty_btn)
        self.empty_wrap = empty_box
        self.g_ctrl.add(empty_box)
        self.cards: list[ControllerCard] = []
        controls_page.add(self.g_ctrl)

        # Grupo bateria
        self.g_bat = Adw.PreferencesGroup(title=_("Bateria"))
        self.bat_rows: list[Adw.ActionRow] = []
        controls_page.add(self.g_bat)

        # Grupo áudio/headset (xone expõe ALSA; xow geralmente não)
        self.g_audio = Adw.PreferencesGroup(
            title=_("Áudio"),
            description=_("Headset e roteamento via PipeWire/PulseAudio"))
        self.audio_status_row = Adw.ActionRow(
            title=_("Áudio do Xbox"), subtitle=_("verificando…"))
        audio_refresh = Gtk.Button(label=_("Atualizar"))
        audio_refresh.add_css_class("btn-std")
        audio_refresh.set_valign(Gtk.Align.CENTER)
        audio_refresh.connect("clicked", lambda _b: self._refresh_audio())
        self.audio_status_row.add_suffix(audio_refresh)
        self.audio_status_row.set_activatable(False)
        self.g_audio.add(self.audio_status_row)
        self._audio_rows.append(self.audio_status_row)
        audio_page.add(self.g_audio)

        # Grupo Bluetooth (xpadneo/BlueZ)
        self.g_bt = Adw.PreferencesGroup(
            title=_("Bluetooth"),
            description=_("Controles Xbox pareados via BlueZ (xpadneo)"))
        self.bt_row = Adw.ActionRow(
            title=_("Controles pareados"),
            subtitle=_("procure controles já pareados ou escaneie"))
        bt_btn = Gtk.Button(label=_("Buscar"))
        bt_btn.add_css_class("btn-std")
        bt_btn.set_valign(Gtk.Align.CENTER)
        bt_btn.connect("clicked", self._on_bt_scan)
        self.bt_row.add_suffix(bt_btn)
        self.bt_row.set_activatable(False)
        self.g_bt.add(self.bt_row)
        self._bt_rows.append(self.bt_row)
        audio_page.add(self.g_bt)

        # Grupo sistema
        g_sys = Adw.PreferencesGroup(title=_("Sistema"))
        self.fw_row = Adw.ActionRow(title=_("Firmware"))
        fw_box = Gtk.Box(spacing=8)
        fw_box.set_valign(Gtk.Align.CENTER)
        self.fw_spin = Gtk.Spinner()
        self.fw_spin.set_visible(False)
        self.fw_install_btn = Gtk.Button(label=_("Instalar"))
        self.fw_install_btn.add_css_class("btn-std")
        self.fw_install_btn.set_valign(Gtk.Align.CENTER)
        self.fw_install_btn.set_tooltip_text(_("Roda o script oficial com pkexec"))
        self.fw_install_btn.connect("clicked", self._on_fw_install)
        fw_copy = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        fw_copy.set_tooltip_text(_("Copiar comando de firmware (xone/xow)"))
        fw_copy.add_css_class("btn-icon")
        fw_copy.set_valign(Gtk.Align.CENTER)
        fw_copy.connect("clicked", self._on_copy_fw)
        fw_box.append(self.fw_spin)
        fw_box.append(self.fw_install_btn)
        fw_box.append(fw_copy)
        self.fw_row.add_suffix(fw_box)
        self.fw_row.set_activatable(False)
        g_sys.add(self.fw_row)

        # Opções de vibração (persistidas)
        self.rumble_dur = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 100, 2000, 50)
        self.rumble_dur.set_value(self._prefs.get_int("rumble-duration"))
        self.rumble_dur.set_draw_value(True)
        self.rumble_dur.set_size_request(180, -1)
        self.rumble_dur.set_valign(Gtk.Align.CENTER)
        self.rumble_dur.connect("value-changed", self._on_rumble_dur)
        dur_row = Adw.ActionRow(title=_("Duração"),
                                subtitle=_("milissegundos por teste"))
        dur_row.add_suffix(self.rumble_dur)
        dur_row.set_activatable(False)
        g_sys.add(dur_row)

        self.rumble_int = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.rumble_int.set_value(self._prefs.get_int("rumble-strong"))
        self.rumble_int.set_draw_value(True)
        self.rumble_int.set_size_request(180, -1)
        self.rumble_int.set_valign(Gtk.Align.CENTER)
        self.rumble_int.connect("value-changed", self._on_rumble_int)
        int_row = Adw.ActionRow(title=_("Intensidade"),
                                subtitle=_("vale para os dois motores"))
        int_row.add_suffix(self.rumble_int)
        int_row.set_activatable(False)
        g_sys.add(int_row)

        self.rumble_weak = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.rumble_weak.set_value(self._prefs.get_int("rumble-weak"))
        self.rumble_weak.set_draw_value(True)
        self.rumble_weak.set_size_request(180, -1)
        self.rumble_weak.set_valign(Gtk.Align.CENTER)
        self.rumble_weak.connect("value-changed", self._on_rumble_weak)
        weak_row = Adw.ActionRow(title=_("Motor fraco"),
                                 subtitle=_("intensidade independente do motor fraco"))
        weak_row.add_suffix(self.rumble_weak)
        weak_row.set_activatable(False)
        g_sys.add(weak_row)

        # Permissões (udev + grupo dedicado)
        self.perm_row = Adw.ActionRow(title=_("Permissões"))
        perm_box = Gtk.Box(spacing=8)
        perm_box.set_valign(Gtk.Align.CENTER)
        self.perm_spin = Gtk.Spinner()
        self.perm_spin.set_visible(False)
        self.perm_btn = Gtk.Button(label=_("Ajustar"))
        self.perm_btn.add_css_class("btn-std")
        self.perm_btn.set_valign(Gtk.Align.CENTER)
        self.perm_btn.set_tooltip_text(
            _("Instala a regra udev e ajusta o grupo xboxwireless"))
        self.perm_btn.connect("clicked", self._on_perm_fix)
        perm_box.append(self.perm_spin)
        perm_box.append(self.perm_btn)
        self.perm_row.add_suffix(perm_box)
        self.perm_row.set_activatable(False)
        g_sys.add(self.perm_row)

        vib_all = Gtk.Button(label=_("Testar todos"))
        vib_all.add_css_class("btn-std")
        vib_all.set_valign(Gtk.Align.CENTER)
        vib_all.connect("clicked", self._on_vibrate_all)
        vib_row = Adw.ActionRow(title=_("Vibração"),
                                subtitle=_("envia rumble a todos os gamepads Xbox"))
        vib_row.add_suffix(vib_all)
        vib_row.set_activatable(False)
        g_sys.add(vib_row)

        test_all = Gtk.Button(label=_("Abrir"))
        test_all.add_css_class("btn-std")
        test_all.set_valign(Gtk.Align.CENTER)
        test_all.connect("clicked", self._on_open_tester)
        test_row = Adw.ActionRow(title=_("Testar botões"),
                                 subtitle=_("desenho do controle com resposta ao vivo"))
        test_row.add_suffix(test_all)
        test_row.set_activatable(False)
        g_sys.add(test_row)

        # Atualizações
        self.upd_row = Adw.ActionRow(title=_("Atualizações"))
        self.upd_notes_btn = Gtk.Button(label=_("Notas"))
        self.upd_notes_btn.add_css_class("btn-std")
        self.upd_notes_btn.set_valign(Gtk.Align.CENTER)
        self.upd_notes_btn.set_visible(False)
        self.upd_notes_btn.connect("clicked", self._on_update_notes)
        self.upd_btn = Gtk.Button(label=_("Verificar"))
        self.upd_btn.add_css_class("btn-std")
        self.upd_btn.set_valign(Gtk.Align.CENTER)
        self.upd_btn.connect("clicked", self._on_check_updates)
        self.upd_row.add_suffix(self.upd_notes_btn)
        self.upd_row.add_suffix(self.upd_btn)
        self.upd_row.set_activatable(False)
        g_sys.add(self.upd_row)

        # Remapeamento via input-remapper (não reimplementamos uinput)
        self.remap_row = Adw.ActionRow(
            title=_("Remapear botões"),
            subtitle=remap.hint())
        remap_btn = Gtk.Button(label=_("Abrir"))
        remap_btn.add_css_class("btn-std")
        remap_btn.set_valign(Gtk.Align.CENTER)
        remap_btn.connect("clicked", self._on_remap)
        self.remap_row.add_suffix(remap_btn)
        self.remap_row.set_activatable(False)
        g_sys.add(self.remap_row)

        # Diagnóstico copiável (suporte)
        self.diag_row = Adw.ActionRow(
            title=_("Diagnóstico"),
            subtitle=_("kernel, driver, firmware, permissões, evdev e áudio"))
        diag_btn = Gtk.Button(label=_("Abrir"))
        diag_btn.add_css_class("btn-std")
        diag_btn.set_valign(Gtk.Align.CENTER)
        diag_btn.connect("clicked", self._on_diagnostics)
        self.diag_row.add_suffix(diag_btn)
        self.diag_row.set_activatable(False)
        g_sys.add(self.diag_row)

        # Serviço xow (legado)
        self.xow_row = Adw.ActionRow(title=_("Serviço xow"))
        xow_box = Gtk.Box(spacing=6)
        xow_box.set_valign(Gtk.Align.CENTER)
        self.xow_start_btn = Gtk.Button(label=_("Iniciar"))
        self.xow_stop_btn = Gtk.Button(label=_("Parar"))
        self.xow_logs_btn = Gtk.Button(label=_("Logs"))
        for b in (self.xow_start_btn, self.xow_stop_btn, self.xow_logs_btn):
            b.add_css_class("btn-std")
            b.set_valign(Gtk.Align.CENTER)
            xow_box.append(b)
        self.xow_start_btn.connect("clicked", lambda _b: self._xow_action("start"))
        self.xow_stop_btn.connect("clicked", lambda _b: self._xow_action("stop"))
        self.xow_logs_btn.connect("clicked", self._on_xow_logs)
        self.xow_row.add_suffix(xow_box)
        self.xow_row.set_activatable(False)
        g_sys.add(self.xow_row)

        # Preferências de comportamento
        self.notify_switch = Adw.SwitchRow(
            title=_("Notificações"), subtitle=_("conexão, desconexão e bateria baixa"))
        self.notify_switch.set_active(self._prefs.get_bool("notifications"))
        self.notify_switch.connect("notify::active", self._on_notifications)
        g_sys.add(self.notify_switch)

        self.updates_switch = Adw.SwitchRow(
            title=_("Atualizações automáticas"),
            subtitle=_("consulta releases no GitHub ao abrir"))
        self.updates_switch.set_active(self._prefs.get_bool("check-updates"))
        self.updates_switch.connect("notify::active", self._on_check_updates_pref)
        g_sys.add(self.updates_switch)

        self.pair_auto_list = Gtk.StringList.new(
            [_("Nunca"), _("30 segundos"), _("60 segundos"), _("120 segundos")])
        self.pair_auto = Gtk.DropDown(model=self.pair_auto_list)
        self.pair_auto.set_valign(Gtk.Align.CENTER)
        self.pair_auto.set_selected(self._pair_auto_index())
        self.pair_auto.connect("notify::selected", self._on_pair_auto)
        self.pair_auto_row = Adw.ActionRow(
            title=_("Desligar pareamento"),
            subtitle=_("evita deixar o dongle pareável para sempre"))
        self.pair_auto_row.add_suffix(self.pair_auto)
        self.pair_auto_row.set_activatable(False)
        g_sys.add(self.pair_auto_row)

        self.refresh_spin = Gtk.SpinButton.new_with_range(5, 120, 5)
        self.refresh_spin.set_value(self._prefs.get_int("refresh-interval"))
        self.refresh_spin.set_valign(Gtk.Align.CENTER)
        self.refresh_spin.connect("value-changed", self._on_refresh_interval)
        self.refresh_row = Adw.ActionRow(
            title=_("Atualizar a cada"),
            subtitle=_("segundos entre atualizações automáticas"))
        self.refresh_row.add_suffix(self.refresh_spin)
        self.refresh_row.set_activatable(False)
        g_sys.add(self.refresh_row)

        self.low_bat_spin = Gtk.SpinButton.new_with_range(5, 50, 5)
        self.low_bat_spin.set_value(self._prefs.get_int("low-battery"))
        self.low_bat_spin.set_valign(Gtk.Align.CENTER)
        self.low_bat_spin.connect("value-changed", self._on_low_battery)
        self.low_bat_row = Adw.ActionRow(
            title=_("Aviso de bateria"),
            subtitle=_("percentual para notificar (quando confiável)"))
        self.low_bat_row.add_suffix(self.low_bat_spin)
        self.low_bat_row.set_activatable(False)
        g_sys.add(self.low_bat_row)

        reset_btn = Gtk.Button(label=_("Restaurar padrões"))
        reset_btn.add_css_class("btn-std")
        reset_btn.set_valign(Gtk.Align.CENTER)
        reset_btn.connect("clicked", self._on_reset_prefs)
        self.reset_row = Adw.ActionRow(
            title=_("Padrões"), subtitle=_("voltar aos valores padrão"))
        self.reset_row.add_suffix(reset_btn)
        self.reset_row.set_activatable(False)
        g_sys.add(self.reset_row)
        settings_page.add(g_sys)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_top(WINDOW_MARGIN)
        content.set_margin_bottom(24)
        content.set_margin_start(WINDOW_MARGIN)
        content.set_margin_end(WINDOW_MARGIN)
        content.append(self._build_hero())

        stack = Adw.ViewStack()
        stack.set_vexpand(True)
        stack.add_titled_with_icon(home_page, "home", _("Início"),
                                   "go-home-symbolic")
        stack.add_titled_with_icon(controls_page, "controls", _("Controles"),
                                   "input-gaming-symbolic")
        stack.add_titled_with_icon(audio_page, "audio", _("Áudio"),
                                   "audio-volume-high-symbolic")
        stack.add_titled_with_icon(settings_page, "settings", _("Configurações"),
                                   "preferences-system-symbolic")
        self.tab_stack = stack
        switcher = Adw.ViewSwitcher()
        switcher.set_stack(stack)
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        switcher.set_halign(Gtk.Align.CENTER)
        content.append(switcher)
        content.append(stack)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(CONTENT_WIDTH)
        clamp.set_tightening_threshold(680)
        clamp.set_child(content)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(clamp)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.append(header)
        body.append(self.banner)
        body.append(scrolled)

        self.toasts = Adw.ToastOverlay()
        self.toasts.set_child(body)
        self.set_content(self.toasts)

        self._updating_switch = False
        self._fp_ctrl = None
        self._fp_bat = None
        self._update_check_id = None
        self._auto_refresh_id = None
        GLib.idle_add(self.on_refresh, None)
        self._schedule_auto_refresh()
        self._start_monitors()
        # verificação de atualização em 2º plano (não trava a UI)
        if self._prefs.get_bool("check-updates"):
            self._update_check_id = GLib.timeout_add_seconds(3, self._auto_update_check)
        self.connect("close-request", self._on_window_close)

    def _quick_button(self, label: str, icon: str):
        btn = Gtk.Button()
        btn.add_css_class("quick-action")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.append(Gtk.Image.new_from_icon_name(icon))
        text = Gtk.Label(label=label)
        box.append(text)
        btn.set_child(box)
        return btn, text

    def _stat_card(self, label: str):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.add_css_class("stat-card")
        value = Gtk.Label(label="—")
        value.add_css_class("stat-value")
        value.set_halign(Gtk.Align.START)
        cap = Gtk.Label(label=label)
        cap.add_css_class("stat-label")
        cap.set_halign(Gtk.Align.START)
        box.append(value)
        box.append(cap)
        return box, value

    def _build_hero(self):
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        hero.add_css_class("hero")

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        icon_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        icon_box.add_css_class("hero-icon")
        icon = Gtk.Image.new_from_icon_name("input-gaming-symbolic")
        icon.set_pixel_size(46)
        icon_box.append(icon)
        icon_box.set_valign(Gtk.Align.START)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        text.set_hexpand(True)
        title = Gtk.Label(label=_("Xbox Wireless"))
        title.add_css_class("hero-title")
        title.set_halign(Gtk.Align.START)
        self.hero_subtitle = Gtk.Label(
            label=_("Seu adaptador, seus controles, no seu ritmo."))
        self.hero_subtitle.add_css_class("hero-subtitle")
        self.hero_subtitle.set_halign(Gtk.Align.START)
        self.hero_subtitle.set_wrap(True)
        text.append(title)
        text.append(self.hero_subtitle)

        self.hero_status = Gtk.Label(label=_("Verificando…"))
        self.hero_status.add_css_class("status-pill")
        self.hero_status.add_css_class("neutral")
        self.hero_status.set_valign(Gtk.Align.START)
        top.append(icon_box)
        top.append(text)
        top.append(self.hero_status)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_margin_top(2)
        self.hero_pair_btn, self.hero_pair_label = self._quick_button(
            _("Parear controle"), "list-add-symbolic")
        self.hero_pair_btn.add_css_class("suggested-action")
        self.hero_pair_btn.connect("clicked", self.on_pair)
        self.hero_test_btn, self.hero_test_label = self._quick_button(
            _("Testar controle"), "input-gaming-symbolic")
        self.hero_test_btn.connect("clicked", self._on_open_tester)
        self.hero_diag_btn, self.hero_diag_label = self._quick_button(
            _("Diagnóstico"), "dialog-information-symbolic")
        self.hero_diag_btn.connect("clicked", self._on_diagnostics)
        actions.append(self.hero_pair_btn)
        actions.append(self.hero_test_btn)
        actions.append(self.hero_diag_btn)

        stats = Gtk.FlowBox()
        stats.set_selection_mode(Gtk.SelectionMode.NONE)
        stats.set_max_children_per_line(3)
        stats.set_min_children_per_line(1)
        stats.set_column_spacing(10)
        stats.set_row_spacing(10)
        stats.set_homogeneous(True)
        self.hero_ctrl_card, self.hero_ctrl_value = self._stat_card(
            _("Controles conectados"))
        self.hero_bat_card, self.hero_bat_value = self._stat_card(
            _("Bateria média"))
        self.hero_fw_card, self.hero_fw_value = self._stat_card(
            _("Firmware"))
        stats.insert(self.hero_ctrl_card, -1)
        stats.insert(self.hero_bat_card, -1)
        stats.insert(self.hero_fw_card, -1)

        hero.append(top)
        hero.append(actions)
        hero.append(stats)
        return hero

    def _set_status_pill(self, text: str, kind: str = ""):
        for cls in ("neutral", "ok", "warn", "err"):
            self.hero_status.remove_css_class(cls)
        if kind:
            self.hero_status.add_css_class(kind)
        self.hero_status.set_text(text)

    def _update_hero(self, info, pairing: bool, bats: list[dict]):
        try:
            count = len(self.cards)
        except Exception:  # noqa: BLE001
            count = 0
        self.hero_ctrl_value.set_text(str(count))
        pcts = []
        for b in bats:
            pct = battery_pct(b)
            if pct >= 0:
                pcts.append(pct)
        if pcts:
            self.hero_bat_value.set_text(f"{round(sum(pcts) / len(pcts))}%")
        else:
            self.hero_bat_value.set_text("—")
        state = getattr(info, "state", "") or ""
        if pairing:
            self._set_status_pill(_("Pareando…"), "warn")
            self.hero_subtitle.set_text(
                _("O adaptador está visível para novos controles."))
        elif info.name == "xone":
            self._set_status_pill(_("Conectado"), "ok")
            if count == 1:
                self.hero_subtitle.set_text(_("Tudo pronto. 1 controle conectado."))
            elif count > 1:
                self.hero_subtitle.set_text(
                    _("Tudo pronto. {n} controles conectados.").format(n=count))
            else:
                self.hero_subtitle.set_text(
                    _("Adaptador pronto. Conecte um controle para começar."))
        elif info.name == "xow" and state != "xow-stopped":
            self._set_status_pill(_("xow ativo"), "ok")
            self.hero_subtitle.set_text(_("Driver legado xow em execução."))
        elif state == "xow-stopped":
            self._set_status_pill(_("Serviço parado"), "warn")
            self.hero_subtitle.set_text(_("Inicie o serviço xow para conectar."))
        elif state == "dongle-no-driver":
            self._set_status_pill(_("Driver inativo"), "err")
            self.hero_subtitle.set_text(
                _("O adaptador foi detectado, mas o driver xone não está ativo."))
        else:
            self._set_status_pill(_("Adaptador ausente"), "err")
            self.hero_subtitle.set_text(
                _("Conecte o Xbox Wireless Adapter para começar."))
        self.hero_pair_label.set_text(
            _("Pareando…") if pairing else _("Parear controle"))
        can_pair = info.name == "xone" or (info.name == "xow"
                                           and state != "xow-stopped")
        self.hero_pair_btn.set_sensitive(bool(can_pair))
        self.hero_pair_btn.set_tooltip_text(
            None if can_pair else _("Conecte o adaptador para parear"))
        self.hero_test_btn.set_sensitive(bool(count))

    def _on_window_close(self, *_args):
        for obj in (getattr(self, "_fs_monitor", None),
                    getattr(self, "_up_monitor", None)):
            try:
                obj.stop()
            except Exception:  # noqa: BLE001
                pass
        for attr in ("_auto_refresh_id", "_update_check_id", "_xow_countdown_id",
                     "_pair_auto_id", "_event_refresh_id"):
            sid = getattr(self, attr, None)
            if sid is not None:
                try:
                    GLib.source_remove(sid)
                except Exception:  # noqa: BLE001
                    pass
                setattr(self, attr, None)
        app = self.get_application()
        if app is not None and getattr(app, "_main_window", None) is self:
            app._main_window = None
        return False

    # ---- helpers ----
    def toast(self, msg: str):
        LOG.info(msg)
        self.toasts.add_toast(Adw.Toast.new(msg))

    def _install_shortcuts(self):
        controller = Gtk.ShortcutController()
        controller.set_scope(Gtk.ShortcutScope.GLOBAL)

        def add(accel: str, callback):
            trigger = Gtk.ShortcutTrigger.parse_string(accel)
            action = Gtk.CallbackAction.new(
                lambda *_a: (callback(), True)[1])
            controller.add_shortcut(Gtk.Shortcut.new(trigger, action))

        add("<Control>r", lambda: self.on_refresh())
        add("<Control>d", lambda: self._on_diagnostics())
        add("<Control>q", lambda: self.close())
        add("F1", lambda: self._on_about())
        self.add_controller(controller)

    def copy_text(self, text: str):
        try:
            provider = Gdk.ContentProvider.new_for_bytes(
                "text/plain;charset=utf-8", GLib.Bytes.new(text.encode()))
            self.get_clipboard().set_content(provider)
            self.toast(_("copiado para a área de transferência"))
        except Exception as e:  # noqa: BLE001
            self.toast(_("não foi possível copiar: {e}").format(e=e))

    def _on_banner_button(self, *_args):
        if self._banner_mode == "xow-stopped":
            self._xow_action("start")
        elif self._banner_mode == "no-driver":
            self.copy_text(
                "sudo modprobe xone_dongle\n"
                "# se o módulo não existir, instale o driver xone "
                "(akmods/DKMS ou COPR) e reinicie a sessão.\n"
                "xbox-wireless-gui --diagnose")

    def _notify(self, title: str, body: str = "", kind: str = "info"):
        try:
            self.banner.show(title, body, kind=kind, timeout=8)
        except Exception:  # noqa: BLE001
            pass
        if not self._prefs.get_bool("notifications"):
            return
        try:
            n = Gio.Notification.new(title)
            if body:
                n.set_body(body)
            n.set_icon(Gio.ThemedIcon.new("input-gaming-symbolic"))
            app = self.get_application()
            if app is not None and app.get_is_registered():
                app.send_notification(None, n)
        except Exception:  # noqa: BLE001
            pass

    def _schedule_auto_refresh(self):
        if self._auto_refresh_id is not None:
            try:
                GLib.source_remove(self._auto_refresh_id)
            except Exception:  # noqa: BLE001
                pass
            self._auto_refresh_id = None
        try:
            secs = max(5, min(120, int(self._prefs.get_int("refresh-interval"))))
        except Exception:  # noqa: BLE001
            secs = 15
        self._auto_refresh_id = GLib.timeout_add_seconds(secs, self._auto_refresh)

    def _on_refresh_interval(self, spin):
        try:
            self._prefs.set_int("refresh-interval", int(spin.get_value()))
        except Exception:  # noqa: BLE001
            pass
        self._schedule_auto_refresh()

    def _start_monitors(self):
        try:
            self._fs_monitor = monitor.FsMonitor(self._queue_event_refresh)
            self._fs_monitor.start()
        except Exception:  # noqa: BLE001
            self._fs_monitor = None
        try:
            self._up_monitor = monitor.UPowerMonitor(self._queue_event_refresh)
            self._up_monitor.start()
        except Exception:  # noqa: BLE001
            self._up_monitor = None

    def _queue_event_refresh(self):
        if self._event_refresh_id is not None:
            return
        self._event_refresh_id = GLib.timeout_add(400, self._event_refresh)

    def _event_refresh(self):
        self._event_refresh_id = None
        try:
            if self.get_visible():
                self.on_refresh()
        except Exception as e:  # noqa: BLE001
            LOG.debug("refresh por evento falhou: %s", e)
        return False

    def _pair_auto_index(self) -> int:
        val = self._prefs.get_int("pairing-auto-off")
        return {0: 0, 30: 1, 60: 2, 120: 3}.get(val, 0)

    def _on_pair_auto(self, dd, _pspec):
        try:
            idx = int(dd.get_selected())
            value = (0, 30, 60, 120)[idx] if 0 <= idx < 4 else 0
            self._prefs.set_int("pairing-auto-off", value)
        except Exception:  # noqa: BLE001
            pass

    def _on_notifications(self, sw, _pspec):
        try:
            self._prefs.set_bool("notifications", bool(sw.get_active()))
        except Exception:  # noqa: BLE001
            pass

    def _on_check_updates_pref(self, sw, _pspec):
        enabled = bool(sw.get_active())
        self._prefs.set_bool("check-updates", enabled)
        if not enabled and self._update_check_id is not None:
            try:
                GLib.source_remove(self._update_check_id)
            except Exception:  # noqa: BLE001
                pass
            self._update_check_id = None
        elif enabled and self._update_check_id is None:
            self._update_check_id = GLib.timeout_add_seconds(
                3, self._auto_update_check)

    def _on_low_battery(self, spin):
        try:
            self._prefs.set_int("low-battery", int(spin.get_value()))
        except Exception:  # noqa: BLE001
            pass

    def _on_reset_prefs(self, _b):
        for key, value in prefs.DEFAULTS.items():
            if isinstance(value, bool):
                self._prefs.set_bool(key, value)
            elif isinstance(value, float):
                self._prefs.set_double(key, value)
            elif isinstance(value, int):
                self._prefs.set_int(key, value)
            else:
                self._prefs.set_string(key, value)
        self.notify_switch.set_active(self._prefs.get_bool("notifications"))
        self.updates_switch.set_active(self._prefs.get_bool("check-updates"))
        self.pair_auto.set_selected(self._pair_auto_index())
        self.refresh_spin.set_value(self._prefs.get_int("refresh-interval"))
        self.low_bat_spin.set_value(self._prefs.get_int("low-battery"))
        self.rumble_dur.set_value(self._prefs.get_int("rumble-duration"))
        self.rumble_int.set_value(self._prefs.get_int("rumble-strong"))
        self.rumble_weak.set_value(self._prefs.get_int("rumble-weak"))
        self._schedule_auto_refresh()
        self.toast(_("preferências restauradas"))

    # ---- energia / wakeup ----
    def _refresh_wakeup(self):
        try:
            val = xone.get_wakeup()
        except Exception:  # noqa: BLE001
            val = None
        if val is None:
            return
        self._updating_wakeup = True
        try:
            self.wakeup_switch.set_active(bool(val))
        finally:
            self._updating_wakeup = False

    def _on_wakeup_switch(self, sw, _pspec):
        if getattr(self, "_updating_wakeup", False):
            return
        enabled = bool(sw.get_active())

        def work():
            ok, msg = xone.set_wakeup(enabled)
            GLib.idle_add(self.toast, msg)
        threading.Thread(target=work, daemon=True).start()

    def _on_poweroff_all(self, _b):
        self._confirm_poweroff(-1, _("todos os controles"))

    def poweroff_controller(self, index: int, led_id: str | None,
                            label: str):
        self._confirm_poweroff(index, label)

    def _confirm_poweroff(self, index: int, label: str):
        dlg = Adw.AlertDialog(
            heading=_("Desligar {l}?").format(l=label),
            body=_("O controle só volta ao apertar o botão Xbox. "
                   "Nenhum dado é apagado."))
        dlg.add_response("cancel", _("Cancelar"))
        dlg.add_response("ok", _("Desligar"))
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.connect("response",
                    lambda d, r: self._do_poweroff(d, r, index))
        dlg.present(self)

    def _do_poweroff(self, _dlg, resp: str, index: int):
        if resp != "ok":
            return
        dongle = self._selected_dongle()

        def work():
            ok, msg = xone.poweroff(index, dongle)
            GLib.idle_add(self._poweroff_done, ok, msg)
        threading.Thread(target=work, daemon=True).start()

    def _poweroff_done(self, ok: bool, msg: str):
        self.toast(msg)
        self.banner.show(_("Energia") if ok else _("Falha ao desligar"),
                         msg, kind="ok" if ok else "err", timeout=8)
        if ok:
            self.on_refresh()
        return False

    def rename_controller(self, serial: str, current: str):
        dlg = Adw.AlertDialog(
            heading=_("Renomear controle"),
            body=_("O nome fica salvo pelo serial {s}.").format(s=serial))
        entry = Gtk.Entry()
        entry.set_text(current if current != _("Controle") else "")
        entry.set_placeholder_text(_("Ex.: Controle da sala"))
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", _("Cancelar"))
        dlg.add_response("ok", _("Salvar"))
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        def done(_d, resp):
            if resp == "ok":
                profiles.set_name(serial, entry.get_text())
                self.on_refresh()
        dlg.connect("response", done)
        dlg.present(self)

    # ---- diagnóstico / logs ----
    def _on_remap(self, _b):
        ok, msg = remap.open_tool()
        if ok:
            self.toast(msg)
            self.banner.show(_("Remapeamento"), msg, kind="ok", timeout=8)
            return
        self.copy_text(remap.hint())
        self.toast(_("input-remapper não encontrado — dica copiada"))
        self.banner.show(_("input-remapper não encontrado"),
                         remap.hint(), kind="warn", timeout=8)

    def _on_diagnostics(self, *_args):
        self.toast(_("coletando diagnóstico…"))

        def work():
            try:
                text = diagnostics.format_markdown()
            except Exception as e:  # noqa: BLE001
                text = _("falha ao coletar diagnóstico: {e}").format(e=e)
            GLib.idle_add(self._show_text_window,
                          _("Diagnóstico"), text)
        threading.Thread(target=work, daemon=True).start()

    def _show_text_window(self, title: str, text: str):
        win = Adw.Window(transient_for=self, title=title)
        win.set_default_size(780, 620)
        header = window_header(title, _("conteúdo copiável"))
        copy_btn = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        copy_btn.add_css_class("btn-icon")
        copy_btn.set_tooltip_text(_("Copiar"))
        a11y_label(copy_btn, _("Copiar"))
        copy_btn.connect("clicked", lambda _b: self.copy_text(text))
        header.pack_end(copy_btn)
        view = Gtk.TextView()
        view.set_editable(False)
        view.set_monospace(True)
        view.set_left_margin(10)
        view.set_right_margin(10)
        view.set_top_margin(8)
        view.set_bottom_margin(8)
        view.get_buffer().set_text(text)
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(view)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        panel.add_css_class("panel")
        panel.append(scrolled)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.append(header)
        body.append(content_clamp(panel, 820))
        win.set_content(body)
        win.present()
        return False

    def _on_xow_logs(self, _b):
        def work():
            text = xow.logs(120)
            GLib.idle_add(self._show_text_window, _("Logs do xow"), text)
        threading.Thread(target=work, daemon=True).start()

    def _xow_action(self, action: str):
        def show(msg: str):
            self.toast(msg)
            self.banner.show(_("Serviço xow"), msg, kind="info", timeout=8)

        def work():
            ok, msg = xow.service_control(action)
            GLib.idle_add(show, msg)
            GLib.idle_add(lambda: self.on_refresh() or False)
        threading.Thread(target=work, daemon=True).start()

    def _refresh_xow_row(self, info=None):
        try:
            active = xow.service_active()
        except Exception:  # noqa: BLE001
            active = False
        state = _("ativo") if active else _("parado")
        installed = getattr(info, "xow_installed", None)
        try:
            available = xow.available()
        except Exception:  # noqa: BLE001
            available = False
        self.xow_row.set_visible(bool(installed) or available)
        if installed is False:
            self.xow_row.set_subtitle(_("xow não instalado"))
        else:
            self.xow_row.set_subtitle(_("serviço {s}").format(s=state))
        self.xow_start_btn.set_sensitive(not active)
        self.xow_stop_btn.set_sensitive(active)

    # ---- bluetooth ----
    def _on_bt_scan(self, _b):
        self.bt_row.set_subtitle(_("procurando controles Bluetooth…"))

        def work():
            try:
                devices = bluetooth.xbox_devices()
            except Exception as e:  # noqa: BLE001
                devices = []
                GLib.idle_add(self.toast, str(e))
            GLib.idle_add(self._show_bt_devices, devices)
        threading.Thread(target=work, daemon=True).start()

    def _show_bt_devices(self, devices: list[dict]):
        self.bt_row.set_subtitle(
            _("{n} controle(s) Bluetooth pareado(s)").format(n=len(devices))
            if devices else _("nenhum controle Bluetooth pareado"))
        if not devices:
            self.toast(_("Nenhum controle Bluetooth pareado. "
                         "Pareie pelo bluetoothctl/Configurações."))
            return False
        win = Adw.Window(transient_for=self, title=_("Controles pareados"))
        win.set_default_size(600, 460)
        header = window_header(_("Controles pareados"),
                               _("BlueZ / xpadneo"))
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title=_("Pareados no BlueZ"),
            description=_("Selecione um controle para conectar"))
        for d in devices:
            row = Adw.ActionRow(title=d["name"], subtitle=d["mac"])
            conn = Gtk.Button(label=_("Conectar"))
            conn.add_css_class("btn-std")
            conn.set_valign(Gtk.Align.CENTER)
            conn.connect("clicked", lambda _b, mac=d["mac"]: self._bt_connect(mac))
            row.add_suffix(conn)
            group.add(row)
        page.add(group)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.append(header)
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(content_clamp(page, 640))
        body.append(scrolled)
        win.set_content(body)
        win.present()
        return False

    def _bt_connect(self, mac: str):
        def show(msg: str):
            self.toast(msg)
            self.banner.show(_("Bluetooth"), msg, kind="ok", timeout=8)

        def work():
            ok, msg = bluetooth.connect(mac)
            if ok:
                bluetooth.trust(mac)
            GLib.idle_add(show, msg)
            GLib.idle_add(lambda: self.on_refresh() or False)
        threading.Thread(target=work, daemon=True).start()

    # ---- áudio ----
    def _refresh_audio(self):
        try:
            st = audio.status()
        except Exception as e:  # noqa: BLE001
            st = {"available": False, "cards": [], "sinks": [], "sources": [],
                  "error": str(e)}
        for row in self._audio_rows[1:]:
            try:
                self.g_audio.remove(row)
            except Exception:  # noqa: BLE001
                pass
        self._audio_rows = self._audio_rows[:1]
        if not st.get("available"):
            self.audio_status_row.set_subtitle(
                _("pactl não encontrado (PipeWire/PulseAudio)"))
            return
        sinks = st.get("sinks") or []
        sources = st.get("sources") or []
        cards = st.get("cards") or []
        if not (sinks or sources or cards):
            self.audio_status_row.set_subtitle(
                _("nenhum áudio Xbox detectado (headset conectado?)"))
            return
        self.audio_status_row.set_subtitle(
            _("{c} card(s), {s} sink(s), {m} source(s)").format(
                c=len(cards), s=len(sinks), m=len(sources)))
        for kind, items in (("sink", sinks), ("source", sources)):
            for it in items:
                name = it["name"]
                row = Adw.ActionRow(
                    title=it["name"].split(".")[-1],
                    subtitle=f"{kind} • {name}")
                default_btn = Gtk.Button(label=_("Padrão"))
                default_btn.add_css_class("btn-std")
                default_btn.set_valign(Gtk.Align.CENTER)
                default_btn.connect(
                    "clicked",
                    lambda _b, k=kind, n=name: self._audio_default(k, n))
                vol = Gtk.Scale.new_with_range(
                    Gtk.Orientation.HORIZONTAL, 0, 150, 5)
                vol.set_size_request(140, -1)
                vol.set_valign(Gtk.Align.CENTER)
                vol.connect("value-changed",
                            lambda s, k=kind, n=name: self._audio_volume(
                                k, n, int(s.get_value())))
                mute = Gtk.Switch()
                mute.connect("notify::active",
                             lambda s, k=kind, n=name: self._audio_mute(
                                 k, n, bool(s.get_active())))
                row.add_suffix(default_btn)
                row.add_suffix(vol)
                row.add_suffix(mute)
                row.set_activatable(False)
                self.g_audio.add(row)
                self._audio_rows.append(row)
        return False

    def _audio_default(self, kind: str, name: str):
        def work():
            ok, msg = audio.set_default(kind, name)
            GLib.idle_add(self.toast, msg)
        threading.Thread(target=work, daemon=True).start()

    def _audio_volume(self, kind: str, name: str, percent: int):
        def work():
            ok, msg = audio.set_volume(kind, name, percent)
            if not ok:
                GLib.idle_add(self.toast, msg)
        threading.Thread(target=work, daemon=True).start()

    def _audio_mute(self, kind: str, name: str, muted: bool):
        def work():
            ok, msg = audio.set_mute(kind, name, muted)
            if not ok:
                GLib.idle_add(self.toast, msg)
        threading.Thread(target=work, daemon=True).start()

    def _selected_dongle(self) -> str | None:
        sel = self._prefs.get_string("selected-dongle")
        if sel and sel in self._dongles:
            return sel
        return self._dongles[0] if self._dongles else None

    def _on_dongle_selected(self, dd, _pspec):
        if getattr(self, "_loading_dongle", False):
            return
        i = dd.get_selected()
        if 0 <= i < len(self._dongles):
            self._prefs.set_string("selected-dongle", self._dongles[i])
            self.on_refresh()

    def _on_about(self, *_args):
        dlg = Adw.AboutDialog(
            application_name="Xbox Wireless GUI",
            version=APP_VERSION,
            comments=_("Gerencie o Xbox Wireless Adapter, controles, LED, "
                       "bateria, áudio e diagnóstico no Fedora (xone + xow)."),
            website="https://github.com/viniciussralves/xbox-wireless-gui",
            issue_url="https://github.com/viniciussralves/xbox-wireless-gui/issues",
            developers=["theone <viniciussralves92@gmail.com>"],
            copyright="© 2026 theone",
            license_type=Gtk.License.GPL_3_0)
        dlg.present(self)

    def _on_copy_fw(self, _b):
        cmd = ("sudo xow-get-firmware.sh" if self._driver_name() == "xow"
               else "sudo xone-get-firmware.sh")
        try:
            provider = Gdk.ContentProvider.new_for_bytes(
                "text/plain;charset=utf-8", GLib.Bytes.new(cmd.encode()))
            self.get_clipboard().set_content(provider)
            self.toast(_("Comando copiado: {cmd}").format(cmd=cmd))
        except Exception as e:  # noqa: BLE001
            self.toast(_("Copie manualmente: {cmd} ({e})").format(cmd=cmd, e=e))

    def _driver_name(self) -> str:
        return self._driver_name_cached or detector.detect().name

    def _refresh_firmware_row(self):
        st = firmware.status(self._driver_name())
        self._fw_state = st.get("state", "")
        if hasattr(self, "hero_fw_value"):
            self.hero_fw_value.set_text(
                _("Instalado") if self._fw_state == "installed"
                else _("Pendente"))
        if st["state"] == "installed":
            self.fw_row.set_subtitle(st["detail"])
        else:
            self.fw_row.set_subtitle(_("firmware ausente — {d}").format(d=st["detail"]))
        self.fw_install_btn.set_sensitive(not self._fw_busy and st["script"] is not None)

    def _on_fw_install(self, _b):
        if self._fw_busy or getattr(self, "_fw_dialog", None) is not None:
            return
        dlg = Adw.AlertDialog(
            heading=_("Instalar firmware do dongle?"),
            body=_("Roda o script oficial com pkexec. O firmware é sujeito aos "
                   "Termos de Uso da Microsoft, precisa de internet e pode levar minutos."))
        dlg.add_response("cancel", _("Cancelar"))
        dlg.add_response("ok", _("Instalar"))
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dlg.connect("response", self._on_fw_confirm)
        self._fw_dialog = dlg
        dlg.present(self)

    def _on_fw_confirm(self, _dlg, resp: str):
        self._fw_dialog = None
        if resp != "ok":
            return
        self._fw_busy = True
        self._refresh_firmware_row()
        self.fw_spin.set_visible(True)
        self.fw_spin.start()
        driver = self._driver_name()

        def work():
            ok, msg = firmware.install(driver)
            GLib.idle_add(self._fw_done, ok, msg)
        threading.Thread(target=work, daemon=True).start()

    def _fw_done(self, ok: bool, msg: str):
        self._fw_busy = False
        self.fw_spin.stop()
        self.fw_spin.set_visible(False)
        self.toast(msg)
        self.banner.show(_("Firmware") if ok else _("Falha no firmware"),
                         msg, kind="ok" if ok else "err", timeout=8)
        self._refresh_firmware_row()
        return False

    def _refresh_perm_row(self, force: bool = False):
        now = time.time()
        if not force and now - self._perm_checked_at < 60:
            return
        self._perm_checked_at = now
        st = permissions.status()
        self.perm_row.set_subtitle(st["detail"])
        self.perm_btn.set_sensitive(not getattr(self, "_perm_busy", False))

    def _on_perm_fix(self, _b):
        if getattr(self, "_perm_busy", False):
            return
        self._perm_busy = True
        self._refresh_perm_row(force=True)
        self.perm_spin.set_visible(True)
        self.perm_spin.start()

        def work():
            ok, msg = permissions.install_fix()
            GLib.idle_add(self._perm_done, ok, msg)
        threading.Thread(target=work, daemon=True).start()

    def _perm_done(self, ok: bool, msg: str):
        self._perm_busy = False
        self.perm_spin.stop()
        self.perm_spin.set_visible(False)
        self.toast(msg)
        self.banner.show(_("Permissões") if ok else _("Falha nas permissões"),
                         msg, kind="ok" if ok else "err", timeout=8)
        self._refresh_perm_row(force=True)
        self.on_refresh()
        return False

    def _on_rumble_dur(self, scale):
        try:
            self._prefs.set_int("rumble-duration", int(scale.get_value()))
        except Exception:  # noqa: BLE001
            pass

    def _on_rumble_int(self, scale):
        try:
            v = int(scale.get_value())
            self._prefs.set_int("rumble-strong", v)
            self._prefs.set_int("rumble-weak", v)
            if hasattr(self, "rumble_weak"):
                self.rumble_weak.set_value(v)
        except Exception:  # noqa: BLE001
            pass

    def _on_rumble_weak(self, scale):
        try:
            self._prefs.set_int("rumble-weak", int(scale.get_value()))
        except Exception:  # noqa: BLE001
            pass

    def _auto_update_check(self):
        def work():
            res = updates.check(APP_VERSION)
            if res.get("newer"):
                GLib.idle_add(self._show_update, res["tag"],
                              res.get("url", ""), res.get("body", ""))
        threading.Thread(target=work, daemon=True).start()
        return False  # roda uma vez

    def _show_update(self, tag: str, url: str, body: str = ""):
        self._upd_url = url
        self._upd_body = body
        self.upd_row.set_subtitle(_("nova versão disponível: {t}").format(t=tag))
        self.upd_btn.set_label(_("Abrir"))
        self.upd_notes_btn.set_visible(bool(body))
        self.toast(_("Nova versão {t} disponível").format(t=tag))
        self.banner.show(_("Atualização disponível"),
                         _("Versão {t} publicada no GitHub.").format(t=tag),
                         kind="info", timeout=10)
        return False

    def _on_update_notes(self, _b):
        body = getattr(self, "_upd_body", "") or _("sem notas do release")
        self._show_text_window(_("Notas da atualização"), body)

    def _on_check_updates(self, _b):
        if getattr(self, "_upd_url", ""):
            Gtk.show_uri(self, self._upd_url, Gdk.CURRENT_TIME)
            return
        self.upd_btn.set_sensitive(False)

        def work():
            res = updates.check(APP_VERSION)
            GLib.idle_add(self._check_done, res)
        threading.Thread(target=work, daemon=True).start()

    def _check_done(self, res: dict):
        self.upd_btn.set_sensitive(True)
        if res.get("newer"):
            self._show_update(res["tag"], res.get("url", ""),
                              res.get("body", ""))
        else:
            self._upd_url = ""
            self.upd_btn.set_label(_("Verificar"))
            if res.get("tag"):
                self.upd_row.set_subtitle(_("você já está na última versão"))
                self.toast(_("Você já está na última versão"))
            elif res.get("error"):
                self.upd_row.set_subtitle(_("não foi possível verificar atualizações"))
                self.toast(_("Não foi possível verificar atualizações"))
            else:
                self.upd_row.set_subtitle(_("nenhum release publicado ainda"))
                self.toast(_("Nenhum release publicado ainda"))
        return False

    def _cancel_xow_countdown(self):
        if self._xow_countdown_id is not None:
            try:
                GLib.source_remove(self._xow_countdown_id)
            except Exception:  # noqa: BLE001
                pass
            self._xow_countdown_id = None
        self._xow_left = 0

    def _start_xow_countdown(self):
        self._cancel_xow_countdown()
        self._xow_left = 20
        self.pair_btn.set_sensitive(False)

        def tick():
            self._xow_left -= 1
            if self._xow_left <= 0:
                self.pair_btn.set_label(_("Parear (xow)"))
                self.pair_btn.set_sensitive(True)
                self._xow_countdown_id = None
                self.on_refresh()
                return False
            self.pair_btn.set_label(_("Pareando… {n}s").format(n=self._xow_left))
            return True
        self.pair_btn.set_label(_("Pareando… {n}s").format(n=self._xow_left))
        self._xow_countdown_id = GLib.timeout_add_seconds(1, tick)

    # ---- refresh ----
    def _auto_refresh(self):
        try:
            self.on_refresh()
        except Exception as e:  # noqa: BLE001
            print(f"auto-refresh falhou: {e}")
        return True  # mantém o timer

    def on_refresh(self, *_args):
        self.refresh_btn.set_sensitive(False)
        try:
            info = detector.detect()
            self._driver_name_cached = info.name
            self._dongles = info.dongles or (
                [info.dongle_sysfs] if info.dongle_sysfs else [])
            chosen = self._selected_dongle()
            pairing = xone.get_pairing(chosen)

            # seletor de dongle
            multi = len(self._dongles) > 1
            self.dongle_row.set_visible(multi)
            if multi:
                self._loading_dongle = True
                try:
                    self.dongle_list.splice(
                        0, self.dongle_list.get_n_items(), self._dongles)
                    idx = self._dongles.index(chosen) if chosen in self._dongles else 0
                    self.dongle_drop.set_selected(idx)
                finally:
                    self._loading_dongle = False

            state = getattr(info, "state", "") or ""
            if info.name == "xone":
                self._cancel_xow_countdown()
                self.driver_row.set_title(_("Driver xone • dongle conectado"))
                version = getattr(info, "xone_version", "") or ""
                ver_txt = f" • xone {version}" if version else ""
                if pairing:
                    if self._pair_since is None:
                        self._pair_since = time.time()
                    since = time.strftime(
                        "%H:%M:%S", time.localtime(self._pair_since))
                    self.driver_row.set_subtitle(
                        _("{d} • pairing=ON (desde {h}){v}").format(
                            d=chosen, h=since, v=ver_txt))
                    self._start_pair_auto_off()
                else:
                    self._pair_since = None
                    self._cancel_pair_auto_off()
                    self.driver_row.set_subtitle(
                        _("{d} • pairing=OFF{v}").format(d=chosen, v=ver_txt))
                self.pair_switch.set_visible(True)
                self.pair_manual_row.set_visible(False)
                self._updating_switch = True
                self.pair_switch.set_active(bool(pairing))
                self._updating_switch = False
                self._banner_mode = ""
                self.banner.set_revealed(False)
            elif info.name == "xow":
                self._pair_since = None
                self._cancel_pair_auto_off()
                stopped = state == "xow-stopped"
                self.driver_row.set_title(
                    _("Driver xow (serviço parado)") if stopped
                    else _("Driver xow (legado)"))
                if self._xow_countdown_id is not None:
                    self.driver_row.set_subtitle(
                        _("xow em pairing ({n}s restantes)").format(n=self._xow_left))
                else:
                    self.driver_row.set_subtitle(
                        _("serviço ativo: {s}").format(s=xow.service_active()))
                    self.pair_btn.set_label(_("Parear (xow)"))
                    self.pair_btn.set_sensitive(not stopped)
                self.pair_switch.set_visible(False)
                self.pair_manual_row.set_visible(not stopped)
                self.banner.set_revealed(stopped)
                if stopped:
                    self._banner_mode = "xow-stopped"
                    self.banner.set_kind("warn")
                    self.banner.set_title(_("Serviço xow está parado"))
                    self.banner.set_detail(
                        _("Inicie o serviço para voltar a conectar controles."))
                    self.banner.set_button_label(_("Iniciar xow"))
            else:
                self._cancel_xow_countdown()
                self._cancel_pair_auto_off()
                self._pair_since = None
                no_driver = state == "dongle-no-driver"
                self.driver_row.set_title(
                    _("Dongle detectado — driver xone inativo") if no_driver
                    else _("Nenhum dongle detectado"))
                self.driver_row.set_subtitle(
                    info.detail if no_driver
                    else _("plugue o adaptador 045e:02e6/02d1"))
                self.pair_switch.set_visible(False)
                self.pair_manual_row.set_visible(False)
                self.pair_btn.set_label(_("Parear (xow)"))
                self.pair_btn.set_sensitive(True)
                self._banner_mode = "no-driver" if no_driver else ""
                self.banner.set_kind("err" if no_driver else "warn")
                self.banner.set_title(
                    _("Dongle USB sem driver xone") if no_driver
                    else _("Adaptador não encontrado"))
                self.banner.set_detail(
                    info.detail if no_driver
                    else _("Conecte o adaptador Xbox Wireless para começar."))
                self.banner.set_button_label(
                    _("Copiar comando") if no_driver else None)
                self.banner.set_revealed(True)

            try:
                clients = xone.active_clients(chosen)
                count = clients.get("count", 0) if isinstance(clients, dict) else 0
                slots = clients.get("slots", []) if isinstance(clients, dict) else []
                if not isinstance(slots, (list, tuple, set)):
                    slots = []
                self.clients_row.set_subtitle(
                    _("{n} cliente(s) • slots {s}").format(
                        n=count, s=sorted(slots)))
            except Exception:  # noqa: BLE001
                self.clients_row.set_subtitle("—")
            self._refresh_wakeup()
            self._refresh_xow_row(info)

            bats = battery.list_batteries()
            self._refresh_controllers(bats)
            self._refresh_batteries(bats)
            self._refresh_firmware_row()
            self._update_hero(info, bool(pairing), bats)
            self._refresh_perm_row()
            if not getattr(self, "_audio_loaded", False):
                self._audio_loaded = True
                self._refresh_audio()
            self._check_connection_notifications(bats)
            self._check_low_battery(bats)
        finally:
            self.refresh_btn.set_sensitive(True)

    def _start_pair_auto_off(self):
        if self._pair_auto_id is not None:
            return
        try:
            seconds = int(self._prefs.get_int("pairing-auto-off"))
        except Exception:  # noqa: BLE001
            seconds = 0
        if seconds <= 0:
            return
        self._pair_auto_id = GLib.timeout_add_seconds(seconds, self._pair_auto_off)

    def _cancel_pair_auto_off(self):
        if self._pair_auto_id is not None:
            try:
                GLib.source_remove(self._pair_auto_id)
            except Exception:  # noqa: BLE001
                pass
            self._pair_auto_id = None

    def _pair_auto_off(self):
        self._pair_auto_id = None
        dongle = self._selected_dongle()

        def work():
            ok, msg = xone.set_pairing(False, dongle)
            GLib.idle_add(self.toast, msg)
            GLib.idle_add(lambda: self.on_refresh() or False)
        threading.Thread(target=work, daemon=True).start()
        return False

    def _check_connection_notifications(self, bats: list[dict]):
        current = {c.serial or c.get_title() for c in self.cards}
        if self._last_conn is not None and current != self._last_conn:
            added = current - self._last_conn
            removed = self._last_conn - current
            if added:
                self._notify(_("Controle conectado"),
                             ", ".join(sorted(added)), kind="ok")
            if removed:
                self._notify(_("Controle desconectado"),
                             ", ".join(sorted(removed)), kind="warn")
        self._last_conn = current

    def _check_low_battery(self, bats: list[dict]):
        threshold = self._prefs.get_int("low-battery")
        for b in bats:
            key = b.get("serial") or b.get("device") or "?"
            low = False
            if battery_is_reliable(b):
                try:
                    low = int(b.get("percentage", 100)) <= threshold
                except (TypeError, ValueError):
                    low = False
            else:
                low = (b.get("level_en") or "").lower() in ("low", "critical")
            if low and key not in self._low_notified:
                self._low_notified.add(key)
                self._notify(_("Bateria baixa"),
                             _("{d}: {l}").format(
                                 d=b.get("device", "?"),
                                 l=battery_level_text(b) or "?"),
                             kind="warn")
            elif not low:
                self._low_notified.discard(key)

    def _refresh_controllers(self, bats: list[dict] | None = None):
        ctrls = xone.list_controllers()
        pads = rumble.find_gamepads()
        if bats is None:
            bats = battery.list_batteries()

        fp = repr([(c.get("id"), c.get("mode"), c.get("brightness")) for c in ctrls]
                  + [(p.get("path"), p.get("name"), p.get("phys"),
                      p.get("uniq")) for p in pads]
                  + [(b.get("device"), b.get("percentage"), b.get("state"),
                      b.get("level"), b.get("time_empty"), b.get("time_full"),
                      b.get("serial"), b.get("is_reliable"))
                     for b in bats])
        if fp == self._fp_ctrl and self.cards:
            return  # nada mudou: evita reconstruir e roubar o foco (auto-refresh)
        self._fp_ctrl = fp

        # tira o foco de dentro do grupo antes de remover as linhas
        # (evita Gtk-CRITICAL grab_focus em row destacada)
        try:
            focus = self.get_focus()
            w = focus
            inside = False
            while w is not None:
                if w is self.g_ctrl:
                    inside = True
                    break
                w = w.get_parent()
            if inside:
                self.set_focus(None)
        except Exception:  # noqa: BLE001
            pass
        expanded = {c.get_title(): c.get_expanded() for c in self.cards}

        for c in self.cards:
            self.g_ctrl.remove(c)
        self.cards.clear()

        used_bats: set[int] = set()

        def take_battery(led_id: str | None,
                         serial: str | None = None) -> dict | None:
            # 1) serial é a chave estável (evdev uniq == UPower serial)
            if serial:
                for i, b in enumerate(bats):
                    if i not in used_bats and (b.get("serial") or "") == serial:
                        used_bats.add(i)
                        return b
            # 2) casa pelo native_path (ex.: led 'gip0.0:white:status' <-> 'gip0.0')
            if led_id:
                short = led_id.split(":")[0]
                for i, b in enumerate(bats):
                    if i in used_bats:
                        continue
                    np = (b.get("native_path") or "").strip()
                    if np and (led_id.startswith(np) or short == np):
                        used_bats.add(i)
                        return b
            # 3) sobras, na ordem
            for i, b in enumerate(bats):
                try:
                    pct = float(b.get("percentage", -1))
                except (TypeError, ValueError):
                    continue
                if i not in used_bats and pct >= 0:
                    used_bats.add(i)
                    return b
            return None

        def short_led(led_id: str) -> str:
            # 'gip0.1:white:status' -> '1.2' (adapter.client, 1-based);
            # não usar só o adapter: dois controles no mesmo dongle
            # ficariam ambos como "Controle 1".
            base = (led_id or "").split(":")[0]
            if base.startswith("gip"):
                nums = base[3:].split(".")
                if len(nums) >= 2 and nums[0].isdigit() and nums[1].isdigit():
                    return f"{int(nums[0]) + 1}.{int(nums[1]) + 1}"
                if nums[0].isdigit():
                    return str(int(nums[0]) + 1)
                return base
            return base or led_id

        # Separa gamepads reais do dispositivo virtual de compatibilidade
        # "X-Box 360 pad" criado pelo xone para compatibilidade com jogos antigos.
        real_pads = [p for p in pads if not is_virtual_pad(p.get("name"))]
        virtual_pads = [p for p in pads if is_virtual_pad(p.get("name"))]
        if ctrls:
            # um cartão por controle físico (LED), anexando evdev + bateria
            items: list[dict] = []
            used_pad_paths: set[str] = set()

            def pad_for_led(led_id: str) -> dict | None:
                # xone expõe phys = 'gip0.0/input0'; casar com o LED evita
                # trocar controles quando a ordem do evdev muda.
                base = (led_id or "").split(":")[0]
                for p in real_pads:
                    if p.get("phys") and p["phys"].split("/")[0] == base:
                        return p
                return None

            for idx, c in enumerate(ctrls):
                pad = pad_for_led(c["id"])
                if pad is None and idx < len(real_pads):
                    cand = real_pads[idx]
                    if cand["path"] not in used_pad_paths:
                        pad = cand
                if pad is not None:
                    used_pad_paths.add(pad["path"])
                n = short_led(c["id"])
                items.append({"title": _("Controle {n}").format(n=n),
                              "sub": _("{cid} • mode={m} brilho={b}/{mx}").format(
                                  cid=c['id'], m=c.get('mode'),
                                  b=c.get('brightness'), mx=c.get('max_brightness')),
                              "led": c["id"],
                              "led_info": c,
                              "path": pad["path"] if pad else None,
                              "pad_name": pad["name"] if pad else None,
                              "serial": (pad.get("uniq") or "") if pad else ""})
            # evdev real sem LED correspondente (ex.: xow/Bluetooth): mostra à parte
            used_paths = set(used_pad_paths)
            for p in real_pads:
                if p["path"] not in used_paths:
                    items.append({"title": p["name"], "sub": p["path"],
                                  "led": None, "path": p["path"],
                                  "pad_name": p["name"],
                                  "serial": p.get("uniq") or ""})
        else:
            items = []
            for p in real_pads or virtual_pads:
                tag = _(" (virtual)") if is_virtual_pad(p.get("name")) else ""
                items.append({"title": f"{p['name']}{tag}", "sub": p["path"],
                              "led": None, "path": p["path"],
                              "pad_name": p["name"],
                              "serial": p.get("uniq") or ""})

        has_any = bool(items)
        self.empty_wrap.set_visible(not has_any)

        for it in items:
            serial = it.get("serial") or ""
            custom = profiles.name_of(serial) if serial else ""
            card = ControllerCard(
                it["title"], it["sub"], it["led"], self,
                pad_path=it["path"], led_info=it.get("led_info"),
                serial=serial, custom_name=custom,
                connection=connection_kind(it["path"], it["led"]))
            if it["title"] in expanded:
                card.set_expanded(expanded[it["title"]])
            b = take_battery(it["led"], serial)
            if b:
                card.set_battery_info(b)
            if serial and serial not in self._applied_profiles \
                    and profiles.led_of(serial):
                self._applied_profiles.add(serial)
                card.apply_saved_profile()
            self.g_ctrl.add(card)
            self.cards.append(card)

    def _refresh_batteries(self, blist: list[dict] | None = None):
        if blist is None:
            blist = battery.list_batteries()
        fp = repr([(b.get("device"), b.get("percentage"), b.get("state"),
                    b.get("level"), b.get("time_empty"), b.get("time_full"),
                    b.get("serial"), b.get("is_reliable"))
                   for b in blist])
        # os cartões já mostram a bateria; evita duplicar a seção inteira
        self.g_bat.set_visible(not bool(self.cards))
        if fp == self._fp_bat and self.bat_rows:
            return
        self._fp_bat = fp
        for r in self.bat_rows:
            self.g_bat.remove(r)
        self.bat_rows.clear()
        for b in blist:
            pct = battery_pct(b)
            reliable = battery_is_reliable(b)
            bar = Gtk.LevelBar(min_value=0, max_value=100)
            bar.set_hexpand(True)
            bar.set_valign(Gtk.Align.CENTER)
            pct_lbl = Gtk.Label()
            pct_lbl.add_css_class("bat-pct")
            if pct >= 0:
                style_bat_bar(bar, pct)
                if reliable:
                    pct_lbl.set_markup(f'<b>{pct}%</b>')
                else:
                    pct_lbl.set_markup(
                        f'<b>{battery_level_text(b) or f"≈{pct}%"}</b>')
            else:
                pct_lbl.set_markup('<b>—</b>')
            suffix = Gtk.Box(spacing=10)
            suffix.append(bar)
            suffix.append(pct_lbl)
            hist = Gtk.Button.new_from_icon_name("document-open-recent-symbolic")
            hist.add_css_class("btn-icon")
            hist.set_tooltip_text(_("Histórico de bateria"))
            a11y_label(hist, _("Histórico de bateria"))
            hist.add_css_class("btn-icon")
            hist.set_valign(Gtk.Align.CENTER)
            native = b.get("native_path") or b.get("serial") or ""
            hist.connect("clicked", lambda _btn, np=native,
                         dev=b.get("device", "?"):
                         self.show_battery_history(np, dev))
            suffix.append(hist)
            detail = bat_time_text(b)
            state = b.get("state", "")
            lvl = b.get("level", "?")
            parts = [state, _("nível {lvl}").format(lvl=lvl)] if lvl and lvl != "—" else [state]
            if detail and detail != state:
                parts.append(detail)
            if not reliable:
                parts.append(_("estimativa pelo nível"))
            sub = " • ".join(s for s in parts if s) if pct >= 0 else state
            row = Adw.ActionRow(title=b["device"], subtitle=sub)
            row.add_prefix(Gtk.Image.new_from_icon_name(
                b.get("icon") or ("battery-good-symbolic" if pct > 20 else "battery-empty-symbolic")))
            row.add_suffix(suffix)
            row.set_activatable(False)
            self.g_bat.add(row)
            self.bat_rows.append(row)
        if not self.bat_rows:
            row = Adw.ActionRow(title=_("Sem dados de bateria"),
                                subtitle=_("UPower não reportou nenhum controle"))
            row.set_activatable(False)
            self.g_bat.add(row)
            self.bat_rows.append(row)

    # ---- ações ----
    def _run_pair(self, action, on_ok=None, suffix: str = ""):
        if self._pair_busy:
            return
        self._pair_busy = True
        self.pair_switch.set_sensitive(False)
        self.pair_btn.set_sensitive(False)

        def work():
            try:
                ok, msg = action()
            except Exception as e:  # noqa: BLE001
                ok, msg = False, str(e)
            if ok and suffix:
                msg += suffix
            GLib.idle_add(self._pair_done, ok, msg, on_ok)
        threading.Thread(target=work, daemon=True).start()

    def _pair_done(self, ok: bool, msg: str, on_ok=None):
        self._pair_busy = False
        self.pair_switch.set_sensitive(True)
        self.pair_btn.set_sensitive(True)
        self.toast(msg)
        self.banner.show(
            _("Pareamento") if ok else _("Falha no pareamento"),
            msg, kind="ok" if ok else "err", timeout=8)
        if ok and on_ok is not None:
            on_ok()
        self.on_refresh()
        return False

    def _on_pair_switch(self, sw, _pspec):
        if self._updating_switch or self._pair_busy:
            return
        enabled = sw.get_active()
        dongle = self._selected_dongle()
        self._run_pair(lambda: xone.set_pairing(enabled, dongle))

    def on_pair(self, *_args):
        name = self._driver_name_cached or detector.detect().name
        if name == "xone":
            dongle = self._selected_dongle()
            self._run_pair(lambda: xone.set_pairing(True, dongle),
                           suffix=_(" • ligue o controle agora"))
        elif name == "xow" or xow.available():
            self._run_pair(xow.set_pairing, on_ok=self._start_xow_countdown)
        else:
            self.toast(_("Sem driver para parear"))
            self.on_refresh()

    def disconnect_bt(self, pad_path: str):
        def work():
            ok, msg = bluetooth.disconnect(pad_path)
            GLib.idle_add(self.toast, msg)
            GLib.idle_add(lambda: self.on_refresh() or False)
        threading.Thread(target=work, daemon=True).start()

    def vibrate_first(self, motor: str = "both"):
        pads = rumble.find_gamepads()
        if not pads:
            self.toast(_("Nenhum gamepad evdev encontrado"))
            return
        real = [p for p in pads if not is_virtual_pad(p.get("name"))]
        self.vibrate_path((real or pads)[0]["path"], motor=motor)

    def vibrate_path(self, path: str, motor: str = "both"):
        dur = self._prefs.get_int("rumble-duration")
        strong, weak = prefs.rumble_magnitudes(self._prefs)
        if motor == "strong":
            weak = 0
        elif motor == "weak":
            strong = 0

        def work():
            ok, msg = rumble.rumble(path, duration_ms=dur,
                                    strong=strong, weak=weak)
            GLib.idle_add(self.toast, msg)
        # rumble dorme ~dur+0.2s: fora da thread da UI para não congelar
        threading.Thread(target=work, daemon=True).start()

    def _on_vibrate_all(self, _b):
        pads = rumble.find_gamepads()
        if not pads:
            self.toast(_("Nenhum gamepad evdev encontrado"))
            return
        real = [p for p in pads if not is_virtual_pad(p.get("name"))]
        dur = self._prefs.get_int("rumble-duration")
        strong, weak = prefs.rumble_magnitudes(self._prefs)

        def work():
            for p in (real or pads):
                ok, msg = rumble.rumble(p["path"], duration_ms=dur,
                                        strong=strong, weak=weak)
                GLib.idle_add(self.toast, f"{p['name']}: {msg}")
        # fora da thread da UI (cada rumble dorme ~dur+0.2s)
        threading.Thread(target=work, daemon=True).start()

    def _on_open_tester(self, _b):
        self.open_tester(None)

    def open_tester(self, pad_path: str | None):
        if pad_path is None:
            pads = rumble.find_gamepads()
            real = [p for p in pads if not is_virtual_pad(p.get("name"))]
            pad_path = (real or pads)[0]["path"] if (real or pads) else None
        TesterWindow(self, initial_path=pad_path).present()

    def show_battery_history(self, native_path: str, device: str):
        BatteryHistoryWindow(self, native_path, device).present()


def _clients_json(dongle: str | None) -> dict:
    data = xone.active_clients(dongle)
    if not isinstance(data, dict):
        return {"count": 0, "slots": [], "all_slots": []}
    return {"count": data.get("count", 0),
            "slots": sorted(data.get("slots") or []),
            "all_slots": sorted(data.get("all_slots") or [])}


def _api_status() -> dict:
    """Status rápido para D-Bus (sem UPower/evdev bloqueantes)."""
    info = detector.detect()
    return {
        "app_version": APP_VERSION,
        "driver": info.name,
        "state": info.state,
        "detail": info.detail,
        "dongle": info.dongle_sysfs,
        "xone_version": info.xone_version,
        "pairing": xone.get_pairing(info.dongle_sysfs),
        "controllers": xone.list_controllers(),
        "active_clients": _clients_json(info.dongle_sysfs),
    }


def _status_dict() -> dict:
    info = detector.detect()
    return {
        "app_version": APP_VERSION,
        "driver": info.name,
        "state": info.state,
        "detail": info.detail,
        "dongle": info.dongle_sysfs,
        "xone_version": info.xone_version,
        "pairing": xone.get_pairing(info.dongle_sysfs),
        "controllers": xone.list_controllers(),
        "batteries": battery.list_batteries(),
        "active_clients": _clients_json(info.dongle_sysfs),
    }


def _cli(argv: list[str]) -> int | None:
    """CLI mínima para scripts/waybar; sem argumentos abre a GUI."""
    parser = argparse.ArgumentParser(
        prog="xbox-wireless-gui", add_help=False,
        description="Xbox Wireless GUI — CLI de status/controle")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--pair", choices=("on", "off"))
    parser.add_argument("--poweroff", nargs="?", const="-1")
    parser.add_argument("--led", nargs=3, metavar=("ID", "MODE", "BRILHO"))
    parser.add_argument("-h", "--help", action="store_true")
    try:
        ns, _unknown = parser.parse_known_args(argv)
    except SystemExit:
        return 2
    if ns.help:
        parser.print_help()
        return 0
    log.setup(verbose=bool(ns.verbose))
    if ns.version:
        print(f"xbox-wireless-gui {APP_VERSION}")
        return 0
    if ns.background:
        from backend import background
        return background.main()
    if ns.status:
        data = _status_dict()
        if ns.json:
            print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        else:
            print(f"driver: {data['driver']} ({data['state']})")
            print(f"dongle: {data['dongle'] or '—'}")
            print(f"pairing: {data['pairing']}")
            print(f"controles: {len(data['controllers'])}")
            for c in data["controllers"]:
                print(f"  - {c.get('id')} mode={c.get('mode')} "
                      f"brilho={c.get('brightness')}/{c.get('max_brightness')}")
            for b in data["batteries"]:
                if battery_is_reliable(b):
                    val = f"{b.get('percentage')}%"
                else:
                    val = f"nível {b.get('level') or '?'}"
                print(f"  bateria: {b.get('device')} {val}")
        return 0
    if ns.diagnose:
        print(diagnostics.format_markdown())
        return 0
    if ns.pair:
        info = detector.detect()
        if info.name == "xone":
            ok, msg = xone.set_pairing(ns.pair == "on", info.dongle_sysfs)
        elif info.name == "xow" or xow.available():
            if ns.pair == "off":
                ok, msg = False, _("xow não desliga o pairing manualmente "
                                   "(o serviço encerra sozinho)")
            else:
                ok, msg = xow.set_pairing()
        else:
            ok, msg = False, _("sem driver para parear")
        print(msg)
        return 0 if ok else 1
    if ns.poweroff is not None:
        ok, msg = xone.poweroff(int(ns.poweroff))
        print(msg)
        return 0 if ok else 1
    if ns.led:
        ok, msg = xone.set_led(*ns.led)
        print(msg)
        return 0 if ok else 1
    return None


class App(Adw.Application):
    def __init__(self):
        GLib.set_prgname(APP_ID)
        GLib.set_application_name("Xbox Wireless GUI")
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self._api = None

    def _register_api(self):
        if self._api is not None:
            return
        try:
            conn = self.get_dbus_connection()
            if conn is None:
                conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            if conn is None:
                return

            def dongle():
                win = getattr(self, "_main_window", None)
                if win is not None:
                    return win._selected_dongle()
                return detector.detect().dongle_sysfs

            self._api = api.register(conn, {
                "status": _api_status,
                "refresh": lambda: getattr(self, "_main_window", None)
                and self._main_window.on_refresh(),
                "present": self.do_activate,
                "pairing": lambda enabled: xone.set_pairing(enabled, dongle()),
                "led": lambda cid, mode, val: xone.set_led(cid, mode, val),
                "poweroff": lambda index: xone.poweroff(index, dongle()),
            })
            LOG.info("API D-Bus registrada em %s", api.OBJECT_PATH)
        except Exception as e:  # noqa: BLE001
            LOG.debug("API D-Bus indisponível: %s", e)

    def do_activate(self):
        win = getattr(self, "_main_window", None)
        if win is None:
            win = MainWindow(self)
            self._main_window = win
        win.present()
        self._register_api()


def main() -> int:
    code = _cli(sys.argv[1:])
    if code is not None:
        return code
    app = App()
    return app.run(sys.argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
