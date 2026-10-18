#!/usr/bin/env python3
"""Xbox Wireless GUI — GTK4 + Libadwaita, backend xone + xow (Fedora)."""
from __future__ import annotations
import math
import os
import sys
import threading
import time
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib, Gdk  # noqa: E402

from backend import bluetooth, detector, firmware, permissions, prefs, updates
from backend import xone, xow, battery, rumble, inputs
from backend import __version__ as APP_VERSION
from backend.i18n import _

APP_ID = "com.github.xbox-wireless-gui"


CSS = b"""
levelbar block { border-radius: 4px; min-height: 10px; }
levelbar block.filled { background: @success_bg_color; }
levelbar.warn block.filled { background: @warning_bg_color; }
levelbar.crit block.filled { background: @error_bg_color; }
.bat-pct { font-size: 14pt; font-weight: 800; }
.dim { font-size: 10pt; opacity: .75; }
.btn-std { min-width: 140px; min-height: 34px; border-radius: 9px; }
.btn-icon { min-width: 34px; min-height: 34px; border-radius: 9px; }
"""

# Escala única de fontes da interface: cada papel, um tamanho.
UI_FONT_BATTERY_PT = 14  # % da bateria (classe .bat-pct)
UI_FONT_DIM_PT = 10      # textos auxiliares (classe .dim)
UI_FONT_CANVAS = 12      # todos os rótulos do desenho do controle


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
        return f"{fmt_duration(b['time_empty'])} restantes"
    if "charg" in st_en and b.get("time_full"):
        return f"cheio em {fmt_duration(b['time_full'])}"
    if "full" in st_en:
        return "carregado"
    # sem tempo estimado: mostra só o estado já traduzido
    return st_pt or ""


def style_bat_bar(bar: Gtk.LevelBar, pct: int):
    bar.set_value(pct)
    bar.remove_css_class("warn")
    bar.remove_css_class("crit")
    if pct <= 20:
        bar.add_css_class("crit")
    elif pct <= 50:
        bar.add_css_class("warn")


class ControllerCard(Adw.ExpanderRow):
    """Cartão expansível por controle: bateria + LED + vibração."""

    def __init__(self, title: str, subtitle: str, led_id: str | None,
                 window: "MainWindow", pad_path: str | None = None):
        super().__init__(title=title, subtitle=subtitle)
        self._win = window
        self.led_id = led_id
        self.pad_path = pad_path
        self.add_prefix(Gtk.Image.new_from_icon_name("input-gaming-symbolic"))
        self.set_expanded(False)

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
        self.bat_row = Adw.ActionRow(title=_("Bateria"), subtitle=_("via UPower"))
        self.bat_row.add_suffix(bat_box)
        self.bat_row.set_activatable(False)
        self.add_row(self.bat_row)

        # --- LED (só xone com gip*) ---
        if led_id:
            info = next((c for c in xone.list_controllers() if c["id"] == led_id), {})
            try:
                cur = int(info.get("brightness") or 0)
                mx = int(info.get("max_brightness") or 5)
            except ValueError:
                cur, mx = 0, 5
            cur_mode = str(info.get("mode") or "2")
            if cur_mode not in ("0", "1", "2"):
                cur_mode = "2"
            self.led_mode_list = Gtk.StringList.new(["0", "1", "2"])
            self.led_mode = Gtk.DropDown(model=self.led_mode_list)
            self.led_mode.set_selected(("0", "1", "2").index(cur_mode))
            self.led_mode.set_tooltip_text("Modo do LED (preserva o atual por padrão)")
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

        # --- vibração ---
        vib_btn = Gtk.Button(label=_("Vibrar"), icon_name="audio-volume-high-symbolic")
        vib_btn.add_css_class("btn-std")
        vib_btn.set_valign(Gtk.Align.CENTER)
        vib_btn.connect("clicked", self._on_vibrate)
        vib_row = Adw.ActionRow(title=_("Teste de vibração"),
                                subtitle=_("testa a vibração via evdev (ff-rumble)"))
        vib_row.add_suffix(vib_btn)
        vib_row.set_activatable(False)
        self.add_row(vib_row)
        self._vib_btn = vib_btn

        # --- testador de botões (desenho do controle) ---
        test_btn = Gtk.Button(label=_("Testar botões"))
        test_btn.add_css_class("pill")
        test_btn.add_css_class("btn-std")
        test_btn.set_valign(Gtk.Align.CENTER)
        test_btn.connect("clicked", self._on_test_buttons)
        test_row = Adw.ActionRow(title=_("Testador de botões"),
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
        try:
            pct = int(b.get("percentage", -1))
        except (ValueError, TypeError):
            pct = -1
        if pct < 0:
            self.bat_label.set_markup('<b>—</b>')
            self.bat_row.set_subtitle(_("sem dados"))
            return
        style_bat_bar(self.bat_bar, pct)
        self.bat_label.set_markup(f'<b>{pct}%</b>')
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
        sub = " • ".join(s for s in parts if s)
        self.bat_row.set_subtitle(sub or "via UPower")

    def set_battery(self, pct: int, state: str):
        self.set_battery_info({"percentage": pct, "state": state,
                               "state_en": state})

    def _on_led_apply(self, _b):
        if not self.led_id:
            return
        val = str(int(self.led_scale.get_value()))
        try:
            mode = str(self.led_mode.get_selected())
        except Exception:  # noqa: BLE001
            mode = None
        if mode not in ("0", "1", "2"):
            # fallback: preserva o mode atual do sysfs em vez de forçar "2"
            try:
                cur = next((c for c in xone.list_controllers()
                            if c["id"] == self.led_id), {}).get("mode")
                mode = cur if cur in ("0", "1", "2") else "2"
            except Exception:  # noqa: BLE001
                mode = "2"
        ok, msg = xone.set_led(self.led_id, mode, val)
        self._win.toast(msg)

    def _on_vibrate(self, _b):
        if self.pad_path:
            self._win.vibrate_path(self.pad_path)
        else:
            self._win.vibrate_first()

    def _on_test_buttons(self, _b):
        self._win.open_tester(self.pad_path)

    def _on_disconnect(self, _b):
        if self.pad_path:
            self._win.disconnect_bt(self.pad_path)


class TesterWindow(Adw.Window):
    """Testador de botões: desenho do controle Xbox com destaque ao vivo via evdev."""

    def __init__(self, parent: Gtk.Window, initial_path: str | None = None):
        super().__init__(transient_for=parent, title=_("Testador de botões"))
        self.set_default_size(580, 520)
        self._dev = None
        self._limits: dict[int, tuple[int, int]] = {}
        self._state = inputs.new_state()
        self._watch_id: int | None = None
        self._devices: list[dict] = []
        self._prefs = prefs.get_prefs()

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=_("Testador de botões"),
                                                subtitle=_("aperte os botões do controle")))

        self.dev_list = Gtk.StringList()
        self.dropdown = Gtk.DropDown(model=self.dev_list)
        self.dropdown.set_tooltip_text("Gamepad evdev")
        self._loading_devices = False
        self.dropdown.connect("notify::selected", self._on_device_selected)
        dev_row = Adw.ActionRow(title=_("Gamepad"))
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

        self.status_label = Gtk.Label(label=_("Nenhum botão pressionado"))
        self.status_label.add_css_class("dim")
        self.status_label.set_wrap(True)
        self.axis_label = Gtk.Label(label="LX 0.00  LY 0.00  •  RX 0.00  RY 0.00  •  LT 0%  RT 0%")
        self.axis_label.add_css_class("dim")
        self.axis_label.set_wrap(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.append(dev_row)
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
        content.append(dz_row)
        content.append(self.area)
        content.append(self.status_label)
        content.append(self.axis_label)
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
            content.append(map_exp)
        except ImportError:
            pass
        hint = Gtk.Label(label=_("Dica: o dispositivo virtual “X-Box 360 pad” espelha o real — teste no “Microsoft Xbox Controller”."))
        hint.add_css_class("dim")
        hint.set_wrap(True)
        content.append(hint)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.append(header)
        body.append(content)
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
                    if "360" not in d.get("name", ""):
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
                from evdev import ecodes
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
            self.status_label.set_text(_("Sem permissão em {path} (grupo input ou udev rule)").format(path=path))
        except OSError as e:
            self.status_label.set_text(_("Falha ao abrir {path}: {e}").format(path=path, e=e))

    def _on_io(self, _fd, _cond):
        if self._dev is None:
            return False
        try:
            from evdev import ecodes
            changed = False
            while True:
                try:
                    ev = self._dev.read_one()
                except BlockingIOError:
                    break
                except OSError:
                    self.status_label.set_text(_("Dispositivo desconectado"))
                    self._state["connected"] = False
                    return False
                if ev is None:
                    break
                if ev.type == ecodes.EV_SYN:
                    # SYN_DROPPED = buffer transbordou, eventos perdidos:
                    # ressincroniza tudo em vez de deixar botão "grudado"
                    if ev.code == ecodes.SYN_DROPPED:
                        if inputs.resync(self._state, self._dev, self._limits):
                            changed = True
                    continue
                if ev.type == ecodes.EV_KEY:
                    if inputs.apply_key(self._state, ev.code, ev.value):
                        changed = True
                elif ev.type == ecodes.EV_ABS:
                    if inputs.apply_abs(self._state, ev.code, ev.value,
                                        self._limits, self._deadzone()):
                        changed = True
            if changed:
                self._update_labels()
                self.area.queue_draw()
        except Exception as e:  # noqa: BLE001
            self.status_label.set_text(_("Erro de leitura: {e}").format(e=e))
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
                self.status_label.set_text(f"D-Pad: x={hx:+d} y={hy:+d}")
            else:
                self.status_label.set_text(_("Nenhum botão pressionado"))
        s = self._state
        self.axis_label.set_text(
            f"LX {s['lx']:+.2f}  LY {s['ly']:+.2f}  •  "
            f"RX {s['rx']:+.2f}  RY {s['ry']:+.2f}  •  "
            f"LT {s['lt']:.0%}  RT {s['rt']:.0%}")

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

        # ---- Share (pílula + seta; decorativo: xone não expõe o botão) ----
        cr.new_path()
        cr.set_line_width(THIN)
        cx, cy, hw, hh = 387, 297, 33, 12
        cr.move_to(cx - hw + hh, cy - hh)
        cr.line_to(cx + hw - hh, cy - hh)
        cr.arc(cx + hw - hh, cy, hh, -math.pi / 2, math.pi / 2)
        cr.line_to(cx - hw + hh, cy + hh)
        cr.arc(cx - hw + hh, cy, hh, math.pi / 2, math.pi * 1.5)
        cr.close_path()
        stroke()
        cr.new_path()
        cr.set_line_width(1.4)
        cr.move_to(cx, cy + 5)
        cr.line_to(cx, cy - 5)
        cr.move_to(cx - 4, cy - 1)
        cr.line_to(cx, cy - 6)
        cr.line_to(cx + 4, cy - 1)
        stroke()

        cr.restore()


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="Xbox Wireless GUI")
        self.set_default_size(680, 600)
        self._prefs = prefs.get_prefs()
        self._dongles: list[str] = []
        self._pair_since: float | None = None
        self._xow_countdown_id: int | None = None
        self._xow_left: int = 0
        self._fw_busy = False

        css = Gtk.CssProvider()
        css.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # ---- header ----
        header = Adw.HeaderBar()
        menu = Gtk.MenuButton(icon_name="open-menu-symbolic")
        pop = Gio.Menu()
        pop.append(_("Sobre"), "app.about")
        menu.set_menu_model(pop)
        header.pack_end(menu)
        self.refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self.refresh_btn.set_tooltip_text(_("Atualizar"))
        self.refresh_btn.add_css_class("btn-icon")
        self.refresh_btn.set_valign(Gtk.Align.CENTER)
        self.refresh_btn.connect("clicked", self.on_refresh)
        header.pack_start(self.refresh_btn)
        about_act = Gio.SimpleAction.new("about", None)
        about_act.connect("activate", self._on_about)
        app.add_action(about_act)

        # ---- banner status ----
        self.banner = Adw.Banner()
        self.banner.set_revealed(False)

        # ---- página ----
        page = Adw.PreferencesPage()

        # Grupo adaptador
        g_ad = Adw.PreferencesGroup(
            title=_("Adaptador Wireless"),
            description=_("Dongle Microsoft 045e:02e6 / 02d1 via driver xone (ou xow legado)"))
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

        self.pair_switch = Adw.SwitchRow(title=_("Modo pairing"),
                                         subtitle=_("dongle visível para novos controles"))
        self.pair_switch.connect("notify::active", self._on_pair_switch)
        g_ad.add(self.pair_switch)

        self.pair_btn_box = Gtk.Box(spacing=8, homogeneous=True)
        self.pair_btn = Gtk.Button(label=_("Ativar pairing (xow)"))
        self.pair_btn.add_css_class("suggested-action")
        self.pair_btn.add_css_class("btn-std")
        self.pair_btn.set_valign(Gtk.Align.CENTER)
        self.pair_btn.connect("clicked", self.on_pair)
        self.pair_btn_box.append(self.pair_btn)
        pair_wrap = Adw.ActionRow(title=_("Pareamento manual"))
        pair_wrap.add_suffix(self.pair_btn_box)
        pair_wrap.set_activatable(False)
        self.pair_manual_row = pair_wrap
        g_ad.add(pair_wrap)
        page.add(g_ad)

        # Grupo controles
        self.g_ctrl = Adw.PreferencesGroup(
            title=_("Controles"),
            description=_("Conectados ao dongle • expanda para LED e vibração"))
        self.empty_status = Adw.StatusPage(
            icon_name="input-gaming-symbolic",
            title=_("Nenhum controle conectado"),
            description=_("Ative o pairing e segure o botão Xbox até piscar rápido."))
        self.empty_btn = Gtk.Button(label=_("Ativar pairing agora"))
        self.empty_btn.add_css_class("suggested-action")
        self.empty_btn.add_css_class("btn-std")
        self.empty_btn.set_valign(Gtk.Align.CENTER)
        self.empty_btn.set_halign(Gtk.Align.CENTER)
        self.empty_btn.connect("clicked", self.on_pair)
        # StatusPage sem child direto: embrulha botão numa box
        empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        empty_box.set_halign(Gtk.Align.CENTER)
        empty_box.append(self.empty_status)
        empty_box.append(self.empty_btn)
        self.empty_wrap = empty_box
        self.g_ctrl.add(empty_box)
        self.cards: list[ControllerCard] = []
        page.add(self.g_ctrl)

        # Grupo bateria
        self.g_bat = Adw.PreferencesGroup(title=_("Bateria"))
        self.bat_rows: list[Adw.ActionRow] = []
        page.add(self.g_bat)

        # Grupo sistema
        g_sys = Adw.PreferencesGroup(title=_("Sistema e firmware"))
        self.fw_row = Adw.ActionRow(title=_("Firmware do dongle"))
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
        dur_row = Adw.ActionRow(title=_("Duração da vibração"),
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
        int_row = Adw.ActionRow(title=_("Intensidade da vibração"),
                                subtitle=_("vale para os dois motores"))
        int_row.add_suffix(self.rumble_int)
        int_row.set_activatable(False)
        g_sys.add(int_row)

        # Permissões (udev + grupo input)
        self.perm_row = Adw.ActionRow(title=_("Permissões"))
        perm_box = Gtk.Box(spacing=8)
        perm_box.set_valign(Gtk.Align.CENTER)
        self.perm_spin = Gtk.Spinner()
        self.perm_spin.set_visible(False)
        self.perm_btn = Gtk.Button(label=_("Corrigir"))
        self.perm_btn.add_css_class("btn-std")
        self.perm_btn.set_valign(Gtk.Align.CENTER)
        self.perm_btn.set_tooltip_text(_("Instala a regra udev e ajusta o grupo input"))
        self.perm_btn.connect("clicked", self._on_perm_fix)
        perm_box.append(self.perm_spin)
        perm_box.append(self.perm_btn)
        self.perm_row.add_suffix(perm_box)
        self.perm_row.set_activatable(False)
        g_sys.add(self.perm_row)

        vib_all = Gtk.Button(label=_("Vibrar todos"))
        vib_all.add_css_class("btn-std")
        vib_all.set_valign(Gtk.Align.CENTER)
        vib_all.connect("clicked", self._on_vibrate_all)
        vib_row = Adw.ActionRow(title=_("Teste de vibração"),
                                subtitle=_("envia rumble a todos os gamepads Xbox"))
        vib_row.add_suffix(vib_all)
        vib_row.set_activatable(False)
        g_sys.add(vib_row)

        test_all = Gtk.Button(label=_("Abrir testador"))
        test_all.add_css_class("btn-std")
        test_all.set_valign(Gtk.Align.CENTER)
        test_all.connect("clicked", self._on_open_tester)
        test_row = Adw.ActionRow(title=_("Testador de botões"),
                                 subtitle=_("desenho do controle com resposta ao vivo"))
        test_row.add_suffix(test_all)
        test_row.set_activatable(False)
        g_sys.add(test_row)

        # Atualizações
        self.upd_row = Adw.ActionRow(title=_("Atualizações"))
        self.upd_btn = Gtk.Button(label=_("Verificar"))
        self.upd_btn.add_css_class("btn-std")
        self.upd_btn.set_valign(Gtk.Align.CENTER)
        self.upd_btn.connect("clicked", self._on_check_updates)
        self.upd_row.add_suffix(self.upd_btn)
        self.upd_row.set_activatable(False)
        g_sys.add(self.upd_row)
        page.add(g_sys)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(page)

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
        GLib.idle_add(self.on_refresh, None)
        # auto-refresh a cada 15s para bateria/pairing sem clique manual
        GLib.timeout_add_seconds(15, self._auto_refresh)
        # verificação de atualização em 2º plano (não trava a UI)
        if self._prefs.get_bool("check-updates"):
            GLib.timeout_add_seconds(3, self._auto_update_check)

    # ---- helpers ----
    def toast(self, msg: str):
        print(msg)
        self.toasts.add_toast(Adw.Toast.new(msg))

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
        dlg = Adw.AboutWindow(
            transient_for=self, application_name="Xbox Wireless GUI",
            version=APP_VERSION,
            comments=_("Gerencie o Xbox Wireless Adapter e controles no Fedora (xone + xow)."),
            license_type=Gtk.License.GPL_3_0)
        dlg.present()

    def _on_copy_fw(self, _b):
        info = detector.detect()
        cmd = ("sudo xow-get-firmware.sh" if info.name == "xow"
               else "sudo xone-get-firmware.sh")
        try:
            provider = Gdk.ContentProvider.new_for_bytes(
                "text/plain;charset=utf-8", GLib.Bytes.new(cmd.encode()))
            self.get_clipboard().set_content(provider)
            self.toast(_("Comando copiado: {cmd}").format(cmd=cmd))
        except Exception as e:  # noqa: BLE001
            self.toast(_("Copie manualmente: {cmd} ({e})").format(cmd=cmd, e=e))

    def _driver_name(self) -> str:
        return detector.detect().name

    def _refresh_firmware_row(self):
        st = firmware.status(self._driver_name())
        if st["state"] == "installed":
            self.fw_row.set_subtitle(st["detail"])
        else:
            self.fw_row.set_subtitle(_("firmware ausente — {d}").format(d=st["detail"]))
        self.fw_install_btn.set_sensitive(not self._fw_busy and st["script"] is not None)

    def _on_fw_install(self, _b):
        if self._fw_busy:
            return
        dlg = Adw.MessageDialog(
            transient_for=self,
            heading=_("Instalar firmware do dongle?"),
            body=_("Roda o script oficial com pkexec. O firmware é sujeito aos "
                   "Termos de Uso da Microsoft, precisa de internet e pode levar minutos."))
        dlg.add_response("cancel", _("Cancelar"))
        dlg.add_response("ok", _("Instalar"))
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dlg.connect("response", self._on_fw_confirm)
        dlg.present()

    def _on_fw_confirm(self, _dlg, resp: str):
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
        self._refresh_firmware_row()
        return False

    def _refresh_perm_row(self):
        st = permissions.status()
        self.perm_row.set_subtitle(st["detail"])
        self.perm_btn.set_sensitive(not getattr(self, "_perm_busy", False))

    def _on_perm_fix(self, _b):
        if getattr(self, "_perm_busy", False):
            return
        self._perm_busy = True
        self._refresh_perm_row()
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
        self._refresh_perm_row()
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
        except Exception:  # noqa: BLE001
            pass

    def _auto_update_check(self):
        def work():
            res = updates.check(APP_VERSION)
            if res.get("newer"):
                GLib.idle_add(self._show_update, res["tag"], res.get("url", ""))
        threading.Thread(target=work, daemon=True).start()
        return False  # roda uma vez

    def _show_update(self, tag: str, url: str):
        self._upd_url = url
        self.upd_row.set_subtitle(_("nova versão disponível: {t}").format(t=tag))
        self.upd_btn.set_label(_("Abrir"))
        self.toast(_("Nova versão {t} disponível").format(t=tag))
        return False

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
            self._show_update(res["tag"], res.get("url", ""))
        elif res.get("tag"):
            self.upd_row.set_subtitle(_("você já está na última versão"))
            self.toast(_("Você já está na última versão"))
        elif res.get("error"):
            # sem releases publicados ainda ou sem rede: silencioso no auto,
            # informativo no manual
            self.toast(_("Nenhum release publicado ainda"))
        return False

    def _start_xow_countdown(self):
        if self._xow_countdown_id is not None:
            try:
                GLib.source_remove(self._xow_countdown_id)
            except Exception:  # noqa: BLE001
                pass
        self._xow_left = 20
        self.pair_btn.set_sensitive(False)

        def tick():
            self._xow_left -= 1
            if self._xow_left <= 0:
                self.pair_btn.set_label(_("Ativar pairing (xow)"))
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

            if info.name == "xone":
                self.driver_row.set_title(_("Driver xone • dongle conectado"))
                if pairing:
                    if self._pair_since is None:
                        self._pair_since = time.time()
                    since = time.strftime(
                        "%H:%M:%S", time.localtime(self._pair_since))
                    self.driver_row.set_subtitle(
                        _("{d} • pairing=ON (desde {h})").format(d=chosen, h=since))
                else:
                    self._pair_since = None
                    self.driver_row.set_subtitle(
                        _("{d} • pairing=OFF").format(d=chosen))
                self.pair_switch.set_visible(True)
                self.pair_manual_row.set_visible(False)
                self._updating_switch = True
                self.pair_switch.set_active(bool(pairing))
                self._updating_switch = False
                self.banner.set_revealed(False)
            elif info.name == "xow":
                self._pair_since = None
                self.driver_row.set_title(_("Driver xow (legado)"))
                if self._xow_countdown_id is not None:
                    self.driver_row.set_subtitle(
                        _("xow em pairing ({n}s restantes)").format(n=self._xow_left))
                else:
                    self.driver_row.set_subtitle(
                        _("serviço ativo: {s}").format(s=xow.service_active()))
                self.pair_switch.set_visible(False)
                self.pair_manual_row.set_visible(True)
            else:
                self._pair_since = None
                self.driver_row.set_title(_("Nenhum dongle detectado"))
                self.driver_row.set_subtitle(_("plugue o adaptador 045e:02e6/02d1"))
                self.banner.set_title(_("Adaptador não encontrado"))
                self.banner.set_button_label(None)
                self.banner.set_revealed(True)

            self._refresh_controllers()
            self._refresh_batteries()
            self._refresh_firmware_row()
            self._refresh_perm_row()
        finally:
            self.refresh_btn.set_sensitive(True)

    def _refresh_controllers(self):
        ctrls = xone.list_controllers()
        pads = rumble.find_gamepads()
        bats = battery.list_batteries()

        fp = repr([(c.get("id"), c.get("mode"), c.get("brightness")) for c in ctrls]
                  + [(p.get("path"), p.get("name")) for p in pads]
                  + [(b.get("device"), b.get("percentage"), b.get("state"),
                      b.get("level")) for b in bats])
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

        def take_battery(led_id: str | None) -> dict | None:
            # 1) casa pelo native_path (ex.: led 'gip0.0:white:status' <-> 'gip0.0')
            if led_id:
                short = led_id.split(":")[0]
                for i, b in enumerate(bats):
                    if i in used_bats:
                        continue
                    np = (b.get("native_path") or "").strip()
                    if np and (led_id.startswith(np) or short == np):
                        used_bats.add(i)
                        return b
            # 2) sobras, na ordem
            for i, b in enumerate(bats):
                if i not in used_bats and b.get("percentage", -1) >= 0:
                    used_bats.add(i)
                    return b
            return None

        def short_led(led_id: str) -> str:
            # 'gip0.0:white:status' -> 'gip0.0' -> '1' (nº após 'gip')
            base = (led_id or "").split(":")[0]
            if base.startswith("gip"):
                num = base[3:].split(".")[0]
                if num.isdigit():
                    return str(int(num) + 1)
                return base
            return base or led_id

        # Separa gamepads reais do dispositivo virtual de compatibilidade
        # "X-Box 360 pad" criado pelo xone para compatibilidade com jogos antigos.
        real_pads = [p for p in pads if "360" not in p.get("name", "")]
        virtual_pads = [p for p in pads if "360" in p.get("name", "")]
        if ctrls:
            # um cartão por controle físico (LED), anexando evdev + bateria
            items: list[dict] = []
            for idx, c in enumerate(ctrls):
                pad = real_pads[idx] if idx < len(real_pads) else None
                if pad is None and real_pads:
                    pad = real_pads[0]
                n = short_led(c["id"])
                items.append({"title": _("Controle {n}").format(n=n),
                              "sub": _("{cid} • mode={m} brilho={b}/{mx}").format(
                                  cid=c['id'], m=c.get('mode'),
                                  b=c.get('brightness'), mx=c.get('max_brightness')),
                              "led": c["id"],
                              "path": pad["path"] if pad else None,
                              "pad_name": pad["name"] if pad else None})
            # evdev real sem LED correspondente (ex.: xow/Bluetooth): mostra à parte
            used_paths = {i["path"] for i in items if i["path"]}
            for p in real_pads:
                if p["path"] not in used_paths:
                    items.append({"title": p["name"], "sub": p["path"],
                                  "led": None, "path": p["path"],
                                  "pad_name": p["name"]})
        else:
            items = []
            for p in real_pads or virtual_pads:
                tag = _(" (virtual)") if "360" in p.get("name", "") else ""
                items.append({"title": f"{p['name']}{tag}", "sub": p["path"],
                              "led": None, "path": p["path"],
                              "pad_name": p["name"]})

        has_any = bool(items)
        self.empty_wrap.set_visible(not has_any)

        for it in items:
            card = ControllerCard(it["title"], it["sub"], it["led"], self,
                                  pad_path=it["path"])
            if it["title"] in expanded:
                card.set_expanded(expanded[it["title"]])
            b = take_battery(it["led"])
            if b:
                card.set_battery_info(b)
            self.g_ctrl.add(card)
            self.cards.append(card)

    def _refresh_batteries(self):
        blist = battery.list_batteries()
        fp = repr([(b.get("device"), b.get("percentage"), b.get("state"),
                    b.get("level")) for b in blist])
        if fp == self._fp_bat and self.bat_rows:
            return
        self._fp_bat = fp
        for r in self.bat_rows:
            self.g_bat.remove(r)
        self.bat_rows.clear()
        for b in blist:
            try:
                pct = int(b["percentage"])
            except (ValueError, TypeError):
                pct = -1
            bar = Gtk.LevelBar(min_value=0, max_value=100)
            bar.set_hexpand(True)
            bar.set_valign(Gtk.Align.CENTER)
            pct_lbl = Gtk.Label()
            pct_lbl.add_css_class("bat-pct")
            if pct >= 0:
                style_bat_bar(bar, pct)
                pct_lbl.set_markup(f'<b>{pct}%</b>')
            else:
                pct_lbl.set_markup('<b>—</b>')
            suffix = Gtk.Box(spacing=10)
            suffix.append(bar)
            suffix.append(pct_lbl)
            detail = bat_time_text(b)
            state = b.get("state", "")
            lvl = b.get("level", "?")
            parts = [state, _("nível {lvl}").format(lvl=lvl)] if lvl and lvl != "—" else [state]
            if detail and detail != state:
                parts.append(detail)
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
    def _on_pair_switch(self, sw, _pspec):
        if self._updating_switch:
            return
        ok, msg = xone.set_pairing(sw.get_active(), self._selected_dongle())
        self.toast(msg)
        self.on_refresh()

    def on_pair(self, *_args):
        info = detector.detect()
        if info.name == "xone":
            ok, msg = xone.set_pairing(True, self._selected_dongle())
            self.toast(msg + _(" • ligue o controle agora"))
        elif info.name == "xow" or xow.available():
            ok, msg = xow.set_pairing()
            self.toast(msg)
            if ok:
                self._start_xow_countdown()
        else:
            self.toast(_("Sem driver para parear"))
        self.on_refresh()

    def disconnect_bt(self, pad_path: str):
        def work():
            ok, msg = bluetooth.disconnect(pad_path)
            GLib.idle_add(self.toast, msg)
            GLib.idle_add(lambda: self.on_refresh() or False)
        threading.Thread(target=work, daemon=True).start()

    def vibrate_first(self):
        pads = rumble.find_gamepads()
        if not pads:
            self.toast(_("Nenhum gamepad evdev encontrado"))
            return
        real = [p for p in pads if "360" not in p.get("name", "")]
        self.vibrate_path((real or pads)[0]["path"])

    def vibrate_path(self, path: str):
        dur = self._prefs.get_int("rumble-duration")
        strong, weak = prefs.rumble_magnitudes(self._prefs)
        ok, msg = rumble.rumble(path, duration_ms=dur,
                                strong=strong, weak=weak)
        self.toast(msg)

    def _on_vibrate_all(self, _b):
        pads = rumble.find_gamepads()
        if not pads:
            self.toast(_("Nenhum gamepad evdev encontrado"))
            return
        real = [p for p in pads if "360" not in p.get("name", "")]
        dur = self._prefs.get_int("rumble-duration")
        strong, weak = prefs.rumble_magnitudes(self._prefs)
        for p in (real or pads):
            ok, msg = rumble.rumble(p["path"], duration_ms=dur,
                                    strong=strong, weak=weak)
            self.toast(f"{p['name']}: {msg}")

    def _on_open_tester(self, _b):
        self.open_tester(None)

    def open_tester(self, pad_path: str | None):
        if pad_path is None:
            pads = rumble.find_gamepads()
            real = [p for p in pads if "360" not in p.get("name", "")]
            pad_path = (real or pads)[0]["path"] if (real or pads) else None
        TesterWindow(self, initial_path=pad_path).present()


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        win = self.props.active_window or MainWindow(self)
        win.present()


def main() -> int:
    app = App()
    return app.run(sys.argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
