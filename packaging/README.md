# Empacotamento

## Fedora / COPR

```sh
make -C .copr srpm OUTDIR=/tmp/xwg-rpms
```

## Debian / Ubuntu

```sh
dpkg-buildpackage -b -us -uc
```

Os arquivos Debian instalam o helper shell, a regra udev, o helper D-Bus
root, a API de sessão, o serviço de usuário e o AppStream.

## Arch / AUR

```sh
cd packaging/aur
makepkg -si
```

Ao publicar uma tag, troque `sha256sums=('SKIP')` pelo hash real do tarball
em `PKGBUILD`.

## Serviços opcionais

```sh
# helper root com polkit dedicado (ativado por D-Bus)
sudo systemctl enable --now com.github.xbox-wireless-gui.helper.service

# notificações/perfis em segundo plano
systemctl --user enable --now xbox-wireless-gui-background.service
```
