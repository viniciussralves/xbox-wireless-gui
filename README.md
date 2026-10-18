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
- Detectar driver (xone sysfs `/sys/bus/usb/drivers/xone-dongle/*/pairing` / xow systemd), com suporte a múltiplos dongles.
- Ativar/desativar pairing (via `pkexec` — polkit), com tempo decorrido (xone) e contagem regressiva de 20s (xow).
- Listar controles (`/sys/class/leds/gip*` + evdev), incluindo Bluetooth (xpadneo) com botão Desconectar.
- Bateria via UPower.
- LED mode/brightness (xone sysfs), preservando o modo atual por padrão.
- Teste vibração via evdev ff-rumble, com duração e intensidade configuráveis (persistidos em GSettings).
- Firmware: detecta `xone_dongle_*.bin`/`xow_dongle.bin` e instala via script oficial (com disclaimer da MS).
- Permissões: regra udev + grupo `input` com assistente de correção (evita `pkexec` a cada clique).
- Testador de botões ao vivo, com zona morta configurável e tabela de mapeamento evdev.
- i18n pt-BR + en, verificação de atualizações no GitHub, testes (`python3 -m unittest discover -s tests`, cobertura 100% em `src/` via `coverage run -m unittest discover -s tests`).

## Instalar deps (Fedora)
```sh
sudo dnf install -y python3-gobject gtk4 libadwaita gobject-introspection python3-evdev evtest joystick upower polkit
```

## Empacotar (Fedora/COPR)
```sh
sudo dnf copr enable viniciussralves/xbox-wireless-gui  # quando publicado
sudo dnf install xbox-wireless-gui
# ou build local do SRPM via .copr/Makefile
```
- `fedora/xbox-wireless-gui.spec` + AppData + ícone + man + GSettings + regra udev + locales.

## Licença
GPL-3.0-or-later — veja [LICENSE](LICENSE).
