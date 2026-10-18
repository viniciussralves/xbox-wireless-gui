# Xbox Wireless GUI

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Fedora](https://img.shields.io/badge/Fedora-RPM-blue.svg)](fedora/xbox-wireless-gui.spec)

Interface GTK4 + Libadwaita para gerenciar o **Xbox Wireless Adapter** no Linux,
com gestão de controles. Backend com detecção automática **xone (atual) + xow (legado)**.
Empacotamento alvo: **Fedora (RPM/COPR)**.

## Estado atual (testado em Fedora 44 KDE)
- `xone_dongle` + dongle `045e:02e6` detectados, `pairing=0`, sem controle conectado.
- GTK4 + Libadwaita + UPowerGlib OK. `python3-evdev`, `evtest` instalados via dnf.

## Uso (dev)
```sh
./run.sh
# ou
python3 src/main.py
```

## Funcionalidades
- Detectar driver (xone sysfs `/sys/bus/usb/drivers/xone-dongle/*/pairing` / xow systemd).
- Ativar/desativar pairing (via `pkexec` — polkit).
- Listar controles (`/sys/class/leds/gip*` + evdev).
- Bateria via UPower.
- LED mode/brightness (xone sysfs).
- Teste vibração via evdev ff-rumble.
- Dica firmware: `sudo xone-get-firmware.sh`.

## Instalar deps (Fedora)
```sh
sudo dnf install -y python3-gobject gtk4 libadwaita gobject-introspection python3-evdev evtest joystick upower polkit
```

## Empacotar (próximo passo)
- `fedora/xbox-wireless-gui.spec` + regra polkit + `.desktop` para COPR.

## Licença
GPL-3.0-or-later — veja [LICENSE](LICENSE).
