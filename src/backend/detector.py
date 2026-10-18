"""Backend: detecção automática xone vs xow."""
from __future__ import annotations
import glob
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class DriverInfo:
    name: str  # "xone", "xow", "nenhum"
    dongle_sysfs: str | None = None
    detail: str = ""


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


def detect_xow() -> bool:
    if shutil.which("xow"):
        return True
    try:
        r = subprocess.run(["systemctl", "is-active", "xow"],
                           capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return r.stdout.strip() == "active"


def detect() -> DriverInfo:
    dongle = detect_xone_dongle()
    if dongle:
        pf = xone_pairing_file(dongle)
        return DriverInfo(name="xone", dongle_sysfs=dongle,
                          detail=f"dongle={dongle} pairing_file={pf}")
    if detect_xow():
        return DriverInfo(name="xow", detail="serviço xow detectado")
    return DriverInfo(name="nenhum", detail="sem dongle xone e sem xow")
