"""Backend: detecção automática xone vs xow + diagnóstico do estado do USB."""
from __future__ import annotations
import glob
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

# IDs USB conhecidos dos adaptadores Xbox Wireless (inclui variantes OEM).
XBOX_WIRELESS_IDS = {
    "02e6",  # Xbox Wireless Adapter for Windows (modelo 1713)
    "02d1",  # Xbox Wireless Adapter (modelo 1790)
    "02f9",  # Xbox Wireless Adapter (modelo 1790, revisão)
    "02fe",  # Xbox Wireless Adapter (modelo 1790, revisão)
    "091e",  # Surface Book 2 / adaptador embutido
}


@dataclass
class DriverInfo:
    name: str  # "xone", "xow", "nenhum"
    dongle_sysfs: str | None = None
    detail: str = ""
    dongles: list = field(default_factory=list)  # todos os dongles xone
    state: str = "none"  # ready | dongle-no-driver | xow-stopped | xow-ready | none
    xone_loaded: bool = False
    xow_installed: bool = False
    xow_active: bool = False
    usb_dongles: list = field(default_factory=list)
    xone_version: str = ""

    def __post_init__(self):
        if self.dongles is None:
            self.dongles = []
        if self.usb_dongles is None:
            self.usb_dongles = []


def _read(path: str, default: str = "") -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def detect_xone_dongle() -> str | None:
    candidates = glob.glob("/sys/bus/usb/drivers/xone-dongle/*:*")
    if candidates:
        return sorted(candidates)[0]
    return None


def xone_pairing_file(dongle_path: str | None = None) -> str | None:
    """Caminho do sysfs 'pairing' do xone (exige root p/ escrita)."""
    if dongle_path is None:
        dongle_path = detect_xone_dongle()
        if dongle_path is None:
            return None
    files = glob.glob(f"{dongle_path}/pairing")
    if files:
        return files[0]
    # fallback: qualquer dongle ligado
    generics = glob.glob("/sys/bus/usb/drivers/xone-dongle/*/pairing")
    return sorted(generics)[0] if generics else None


def module_loaded(name: str = "xone_dongle") -> bool:
    return os.path.isdir(f"/sys/module/{name}")


def module_version(name: str = "xone_dongle") -> str:
    return _read(f"/sys/module/{name}/version")


def _systemctl(args: list[str], timeout: int = 5) -> str:
    try:
        r = subprocess.run(["systemctl", *args], capture_output=True,
                           text=True, timeout=timeout)
        return (r.stdout or "").strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def xow_installed() -> bool:
    return shutil.which("xow") is not None


def xow_active() -> bool:
    return _systemctl(["is-active", "xow"]) == "active"


def xow_enabled() -> bool:
    return _systemctl(["is-enabled", "xow"]) == "enabled"


def detect_xow() -> bool:
    """Compatibilidade: xow disponível (instalado) ou serviço ativo."""
    return xow_installed() or xow_active()


def find_usb_dongles() -> list[dict]:
    """Varre o barramento USB por adaptadores Xbox Wireless.

    Serve para diferenciar “dongle nem plugado” de “dongle plugado sem
    driver xone” — o glob do driver xone não existe no segundo caso.
    """
    out: list[dict] = []
    for vendor_file in sorted(glob.glob("/sys/bus/usb/devices/*/idVendor")):
        base = os.path.dirname(vendor_file)
        vendor = _read(vendor_file)
        product = _read(os.path.join(base, "idProduct"))
        if vendor.lower() != "045e" or product.lower() not in XBOX_WIRELESS_IDS:
            continue
        driver = ""
        # o driver xone é vinculado à interface (3-1:1.0), não ao device
        for iface in sorted(glob.glob(base + ":*")):
            link = os.path.join(iface, "driver")
            if os.path.islink(link):
                driver = os.path.basename(os.path.realpath(link))
                break
        if not driver:
            link = os.path.join(base, "driver")
            try:
                driver = os.path.basename(os.path.realpath(link))
            except OSError:
                driver = ""
        out.append({
            "path": base,
            "id": f"{vendor.lower()}:{product.lower()}",
            "vendor": _read(os.path.join(base, "manufacturer")),
            "product": _read(os.path.join(base, "product")),
            "serial": _read(os.path.join(base, "serial")),
            "bcd_device": _read(os.path.join(base, "bcdDevice")),
            "driver": driver,
        })
    return out


def dongle_poweroff_file(dongle: str | None = None) -> str | None:
    """sysfs de poweroff do dongle (0-15 = cliente, -1 = todos)."""
    base = dongle or detect_xone_dongle()
    if not base:
        return None
    cand = os.path.join(base, "poweroff")
    return cand if os.path.isfile(cand) else None


def dongle_active_clients(dongle: str | None = None) -> dict:
    """Lê active_clients e devolve {'count': int, 'slots': set[int]}.

    O formato do xone é::

        Active clients: 1
        [00]*   [08]
        [01]    [09]
        ...
    """
    base = dongle or detect_xone_dongle()
    if not base:
        return {"count": 0, "slots": set(), "all_slots": set(), "raw": ""}
    raw = _read(os.path.join(base, "active_clients"))
    count = 0
    slots: set[int] = set()
    all_slots: set[int] = set()
    for line in raw.splitlines():
        low = line.lower()
        if low.startswith("active clients:"):
            try:
                count = int(line.split(":", 1)[1].strip())
            except ValueError:
                count = 0
            continue
        for m in re.finditer(r"\[(\d+)\](\*?)", line):
            idx = int(m.group(1))
            all_slots.add(idx)
            if m.group(2):
                slots.add(idx)
    return {"count": count, "slots": slots, "all_slots": all_slots,
            "raw": raw}


def detect() -> DriverInfo:
    dongle = detect_xone_dongle()
    usb = find_usb_dongles()
    xone_loaded = module_loaded("xone_dongle")
    xone_version = module_version("xone_dongle")
    xow_inst = detect_xow()
    xow_act = xow_active() if xow_inst else False
    xow_en = xow_enabled() if xow_inst else False

    if dongle:
        pf = xone_pairing_file(dongle)
        all_dongles = sorted(glob.glob("/sys/bus/usb/drivers/xone-dongle/*:*"))
        detail = f"dongle={dongle} pairing_file={pf}"
        if xone_version:
            detail += f" módulo=xone_dongle {xone_version}"
        if usb:
            detail += f" usb={usb[0]['id']}"
        return DriverInfo(name="xone", dongle_sysfs=dongle, detail=detail,
                          dongles=all_dongles, state="ready",
                          xone_loaded=xone_loaded, xow_installed=xow_inst,
                          xow_active=xow_act, usb_dongles=usb,
                          xone_version=xone_version)

    if xow_inst:
        detail = "serviço xow ativo" if xow_act else "xow instalado, serviço parado"
        if xow_en and not xow_act:
            detail += " (habilitado no boot)"
        return DriverInfo(name="xow", detail=detail,
                          state="xow-ready" if xow_act else "xow-stopped",
                          xone_loaded=xone_loaded, xow_installed=True,
                          xow_active=xow_act, usb_dongles=usb,
                          xone_version=xone_version)

    if usb:
        detail = (f"dongle USB {usb[0]['id']} detectado, mas o driver "
                  "xone-dongle não está vinculado")
        if not xone_loaded:
            detail += " (módulo xone_dongle não carregado)"
        return DriverInfo(name="nenhum", detail=detail, dongles=[],
                          state="dongle-no-driver", xone_loaded=xone_loaded,
                          xow_installed=False, xow_active=False,
                          usb_dongles=usb, xone_version=xone_version)

    return DriverInfo(name="nenhum", detail="sem dongle xone e sem xow",
                      state="none", xone_loaded=xone_loaded,
                      xow_installed=False, xow_active=False,
                      usb_dongles=[], xone_version=xone_version)
