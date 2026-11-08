# Contribuindo

Obrigado por ajudar com o Xbox Wireless GUI.

## Ambiente

```sh
sudo dnf install -y python3-gobject gtk4 libadwaita gobject-introspection \
  python3-evdev evtest joystick upower polkit bluez pulseaudio-utils
python3 -m unittest discover -s tests -v
```

Para rodar a interface:

```sh
./run.sh
# ou, se o grupo xboxwireless acabou de ser criado:
sg xboxwireless -c './run.sh'
```

## Regras do projeto

- Mantenha o backend sem dependência de GTK; a UI fica em `src/main.py`.
- Toda operação que escreve em sysfs/roda como root deve passar por
  `helper`/`pkexec` com valores validados.
- Novos recursos precisam de testes com mock (sem hardware real no CI).
- Preserve a cobertura de linha ≥95% em `src/`.
- Use msgids em pt-BR com `_()`; traduções ficam em `po/`.
- Rode `python3 -m py_compile src/main.py src/backend/*.py tests/*.py`
  antes de abrir a PR.

## Commits e PR

- Commits pequenos, em português ou inglês, com mensagem clara.
- Descreva o comportamento testado e o hardware usado (se aplicável).
- Para mudanças de permissões/udev/polkit, explique o impacto de segurança.

## Licença

Ao contribuir você concorda que o código será distribuído sob GPL-3.0-or-later.
