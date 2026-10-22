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
# se o grupo xboxwireless foi criado nesta sessão e ainda não está ativo:
sg xboxwireless -c './run.sh'
```

> O grupo só passa a valer em novas sessões; `sg xboxwireless -c ...` aplica
> imediatamente ao processo atual sem precisar reiniciar a sessão.

## Funcionalidades
- Detectar driver (xone sysfs `/sys/bus/usb/drivers/xone-dongle/*/pairing` / xow systemd), com suporte a múltiplos dongles.
- Ativar/desativar pairing (via `pkexec` — polkit), com tempo decorrido (xone) e contagem regressiva de 20s (xow).
- Listar controles (`/sys/class/leds/gip*` + evdev), incluindo Bluetooth (xpadneo) com botão Desconectar.
- Bateria via UPower.
- LED mode/brightness (xone sysfs), com todos os modos do driver (off/on/blink/fade), preservando o modo atual por padrão.
- Teste vibração via evdev ff-rumble, com duração e intensidade configuráveis (persistidos em GSettings).
- Firmware: detecta o binário esperado por driver (`xone_dongle_*.bin`/`xow_dongle.bin`) e instala via script oficial (com disclaimer da MS).
- Permissões: regra udev + grupo dedicado `xboxwireless` + `uaccess` para evdev; o app **não** adiciona mais o usuário ao grupo `input`.
- Testador de botões ao vivo, com zona morta configurável e tabela de mapeamento evdev.
- i18n pt-BR + en, verificação de atualizações no GitHub, testes (`python3 -m unittest discover -s tests`; cobertura de linha ~98% e branch ~95% em `src/` localmente; CI exige ≥95%).

## Instalar deps (Fedora)
```sh
sudo dnf install -y python3-gobject gtk4 libadwaita gobject-introspection python3-evdev evtest joystick upower polkit
sudo dnf install -y python3-coverage  # opcional, para rodar a cobertura
```

## Driver
O app gerencia o dongle, mas **não instala o driver**. Instale um dos dois:
- **xone** (recomendado): pacote/akmods do projeto `xone` (ou COPR/lpf compatível com seu kernel).
- **xow** (legado): pacote `xow` + serviço systemd ativo.

Depois de instalar o driver, plugue o adaptador e abra o app. O firmware é proprietário da Microsoft e só é baixado pelo script oficial após confirmação.

## Segurança e permissões
- O controle de LED/pairing usa o grupo `xboxwireless`; o app **não** usa o grupo `input`, que também dá leitura a teclados.
- O RPM instala um helper root-owned (`/usr/libexec/xbox-wireless-gui-helper`) e usa subcomandos fixos via `pkexec`; o checkout dev usa o caminho de fallback com valores validados.
- Gamepads recebem `TAG+="uaccess"` pela regra udev, liberando evdev para o usuário da sessão sem grupo global.
- Ainda assim, qualquer regra udev ou operação `pkexec` é privilégio elevado: revise o conteúdo de `data/71-xbox-wireless-gui.rules` antes de instalar em máquinas compartilhadas.

## Empacotar (Fedora/COPR)
```sh
sudo dnf copr enable viniciussralves/xbox-wireless-gui  # quando publicado
sudo dnf install xbox-wireless-gui
# ou build local do SRPM via .copr/Makefile
```
- `fedora/xbox-wireless-gui.spec` + AppData + ícone + man + GSettings + regra udev + sysusers + locales.

## Licença
GPL-3.0-or-later — veja [LICENSE](LICENSE).
