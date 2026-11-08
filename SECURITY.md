# Segurança

## Modelo de privilégios

O app roda como usuário comum. Operações que exigem root passam por um
helper root-owned instalado pelo RPM (`/usr/libexec/xbox-wireless-gui-helper`),
chamado com subcomandos fixos via `pkexec`:

- `pairing on|off <pairing>`
- `led <id> <mode> <brightness>`
- `poweroff <poweroff> <0-15|-1>`
- `wakeup <wakeup> on|off`
- `permissions <usuário>`
- `xow start|stop|restart|enable|disable`

O helper valida caminhos, IDs, modos e índices antes de escrever em sysfs.
O fallback de desenvolvimento usa um script constante com valores cotados;
nunca executa arquivos do checkout do usuário.

## Regra udev

A regra `71-xbox-wireless-gui.rules` dá ao grupo `xboxwireless` acesso de
escrita apenas a:

- `/sys/class/leds/gip*/brightness` e `mode`
- `/sys/bus/usb/drivers/xone-dongle/*/pairing` e `poweroff`

Ela também adiciona `TAG+="uaccess"` a gamepads, liberando evdev para o
usuário da sessão sem usar o grupo `input` (que lê teclados).

## Relatando vulnerabilidades

Não abra uma issue pública para falhas de segurança. Envie um e-mail para
`viniciussralves92@gmail.com` com:

- versão do app, distro e kernel;
- passos para reproduzir;
- impacto e, se possível, uma sugestão de correção.

Você receberá uma confirmação em até 7 dias.
