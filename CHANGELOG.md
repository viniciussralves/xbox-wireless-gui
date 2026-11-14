# Changelog

Todas as mudanças relevantes deste projeto seguem um formato simples,
inspirado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).

## [0.3.0] — 2026-11-07

### Adicionado
- Atualização orientada a eventos com `Gio.FileMonitor` e sinais do UPower,
  mantendo o polling como fallback.
- Helper D-Bus root com autorização polkit dedicada (`com.github.xbox-wireless-gui.helper`)
  e fallback para o helper/pkexec antigo.
- API D-Bus de sessão `com.github.xboxwirelessgui.Control1` com
  `GetStatus`, `Refresh`, `Present`, `SetPairing`, `SetLed` e `Poweroff`.
- Histórico de bateria via `UPower.GetHistory`, com janela e gráfico.
- Logging rotativo em `~/.local/state/xbox-wireless-gui/app.log`, opção
  `--verbose` e log recente no diagnóstico.
- Acessibilidade: rótulos em botões de ícone, descrição acessível do
  testador e atalhos Ctrl+R/Ctrl+D/Ctrl+Q/F1.
- Serviço de usuário em segundo plano (`--background`) para notificações
  e reaplicação de perfis de LED.
- Integração com input-remapper na interface.
- Empacotamento Debian e AUR; unidades systemd, política D-Bus e
  serviço de ativação por D-Bus.
- Design system consistente: headers, margens, painéis, botões, ícones e
  janelas secundárias padronizados; testador e histórico no mesmo estilo.
- Testes para os novos módulos e fluxos (248 testes).

### Corrigido
- Caminhos/interface D-Bus válidos (sem hífen em object path/interface).
- Convenção de nome de interface e registro de objeto D-Bus.

## [0.2.0] — 2026-11-07

### Adicionado
- Desligar controle individual ou todos via `poweroff` do xone.
- Bateria por nível quando o UPower não fornece percentual confiável.
- Mapeamento de bateria por serial (`evdev.uniq` ↔ UPower `serial`).
- Diagnóstico copiável com kernel, driver, Secure Boot, firmware, udev,
  evdev, UPower, áudio e clientes ativos.
- CLI `--status`, `--status --json`, `--diagnose`, `--pair`, `--poweroff`
  e `--led`.
- Notificações de conexão/desconexão e bateria baixa.
- Pairing com desligamento automático configurável.
- Áudio/headset do xone (sinks/sources, padrão, volume e mute via pactl).
- Perfis de LED por serial, reaplicados quando o controle reconecta.
- Bluetooth: listar controles pareados no BlueZ, conectar e confiar.
- Teste separado dos motores forte/fraco do rumble.
- Testador com log de eventos evdev, botões desconhecidos e cópia do estado.
- Wakeup do PC pelo controle (sysfs do adaptador USB).
- Preferências: notificações, intervalo de refresh, aviso de bateria baixa,
  pairing auto-off e restauração de padrões.
- Documentação: README, CHANGELOG, CONTRIBUTING, SECURITY, templates de
  issue/PR e screenshot no AppStream.
- Testes para áudio, Bluetooth, diagnóstico, perfis, poweroff, wakeup,
  CLI e novos fluxos de UI.

### Corrigido
- xow instalado mas parado não é mais exibido como driver ativo.
- Dongle presente sem driver agora é diagnosticado como tal.
- `active_clients` mostra apenas os slots realmente ativos.
- Estado do driver USB mostra o driver da interface (`xone-dongle`), não `usb`.
- Cobertura de testes mantida acima de 95%.

## [0.1.0] — 2026-10-18

- Primeira versão pública: GTK4/Libadwaita, xone/xow, pairing, LED,
  bateria via UPower, rumble, testador, firmware, permissões, i18n,
  AppData, man page e empacotamento Fedora/COPR.
