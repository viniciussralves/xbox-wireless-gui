Name:           xbox-wireless-gui
Version:        0.1.0
Release:        1%{?dist}
Summary:        Interface GTK para Xbox Wireless Adapter (xone/xow)
License:        GPL-3.0-or-later
URL:            https://github.com/viniciussralves/xbox-wireless-gui
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  gettext
BuildRequires:  python3-evdev
Requires:       python3-gobject gtk4 libadwaita upower polkit python3-evdev
Recommends:     evtest joystick
Recommends:     bluez
# driver via akmods/dkms/lpf ou COPR, não obrigatório: xone ou xow

%description
GUI em Python + GTK4/Libadwaita para gerenciar o Xbox Wireless Adapter
e controles no Fedora, com backend xone + xow.

%prep
%autosetup -n %{name}-%{version}

%build
for po in po/*.po; do
  lang=$(basename $po .po)
  mkdir -p locale/$lang/LC_MESSAGES
  msgfmt --check $po -o locale/$lang/LC_MESSAGES/%{name}.mo
done

%install
mkdir -p %{buildroot}%{_bindir} %{buildroot}%{_datadir}/applications
mkdir -p %{buildroot}%{_datadir}/xbox-wireless-gui/backend
mkdir -p %{buildroot}%{_datadir}/polkit-1/actions
mkdir -p %{buildroot}%{_datadir}/glib-2.0/schemas
mkdir -p %{buildroot}%{_udevrulesdir}
mkdir -p %{buildroot}%{_datadir}/metainfo
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/scalable/apps
mkdir -p %{buildroot}%{_mandir}/man1
mkdir -p %{buildroot}%{_datadir}/locale
# wrapper que encontra o backend em /usr/share + checkout dev
cat > %{buildroot}%{_bindir}/xbox-wireless-gui <<'EOF'
#!/bin/sh
for d in %{_datadir}/xbox-wireless-gui "$(dirname "$0")/../src"; do
  if [ -f "$d/main.py" ]; then exec python3 "$d/main.py" "$@"; fi
done
exec python3 %{_datadir}/xbox-wireless-gui/main.py "$@"
EOF
chmod 755 %{buildroot}%{_bindir}/xbox-wireless-gui
install -m644 src/main.py %{buildroot}%{_datadir}/xbox-wireless-gui/main.py
install -m644 src/backend/*.py %{buildroot}%{_datadir}/xbox-wireless-gui/backend/
install -m644 data/com.github.xbox-wireless-gui.desktop %{buildroot}%{_datadir}/applications/
install -m644 data/org.xboxwireless.gui.policy %{buildroot}%{_datadir}/polkit-1/actions/
install -m644 data/com.github.xbox-wireless-gui.gschema.xml %{buildroot}%{_datadir}/glib-2.0/schemas/
install -m644 data/71-xbox-wireless-gui.rules %{buildroot}%{_udevrulesdir}/
install -m644 data/com.github.xbox-wireless-gui.metainfo.xml %{buildroot}%{_datadir}/metainfo/
install -m644 data/icons/hicolor/scalable/apps/com.github.xbox-wireless-gui.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/
install -m644 data/xbox-wireless-gui.1 %{buildroot}%{_mandir}/man1/
cp -a locale/* %{buildroot}%{_datadir}/locale/

%check
python3 -m py_compile src/main.py src/backend/*.py tests/*.py
python3 -m unittest discover -s tests
desktop-file-validate %{buildroot}%{_datadir}/applications/com.github.xbox-wireless-gui.desktop || :

%post
glib-compile-schemas %{_datadir}/glib-2.0/schemas &>/dev/null || :
udevadm control --reload-rules &>/dev/null || :
udevadm trigger --subsystem-match=leds &>/dev/null || :

%postun
glib-compile-schemas %{_datadir}/glib-2.0/schemas &>/dev/null || :
udevadm control --reload-rules &>/dev/null || :

%files
%{_bindir}/xbox-wireless-gui
%{_datadir}/xbox-wireless-gui/main.py
%{_datadir}/xbox-wireless-gui/backend/*.py
%{_datadir}/applications/com.github.xbox-wireless-gui.desktop
%{_datadir}/metainfo/com.github.xbox-wireless-gui.metainfo.xml
%{_datadir}/polkit-1/actions/org.xboxwireless.gui.policy
%{_datadir}/glib-2.0/schemas/com.github.xbox-wireless-gui.gschema.xml
%{_udevrulesdir}/71-xbox-wireless-gui.rules
%{_datadir}/icons/hicolor/scalable/apps/com.github.xbox-wireless-gui.svg
%{_mandir}/man1/xbox-wireless-gui.1*
%{_datadir}/locale/*/LC_MESSAGES/xbox-wireless-gui.mo

%changelog
* Sun Oct 18 2026 theone <viniciussralves92@gmail.com> - 0.1.0-1
- Firmware com status/instalação, permissões udev, multi-dongle, countdown xow,
  rumble configurável, GSettings, i18n (pt/en), testes, AppData/ícone/man, COPR
* Sun Oct 18 2026 theone <viniciussralves92@gmail.com> - 0.1.0-0
- Initial package
