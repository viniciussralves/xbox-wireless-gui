Name:           xbox-wireless-gui
Version:        0.1.0
Release:        1%{?dist}
Summary:        Interface GTK para Xbox Wireless Adapter (xone/xow)
License:        GPL-3.0-or-later
URL:            https://github.com/viniciussralves/xbox-wireless-gui
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
Requires:       python3-gobject gtk4 libadwaita upower polkit python3-evdev
Recommends:     evtest joystick
# driver via akmods/dkms, não obrigatório: xone ou xow

%description
GUI em Python + GTK4/Libadwaita para gerenciar o Xbox Wireless Adapter
e controles no Fedora, com backend xone + xow.

%install
mkdir -p %{buildroot}%{_bindir} %{buildroot}%{_datadir}/applications
mkdir -p %{buildroot}%{_datadir}/xbox-wireless-gui/backend
mkdir -p %{buildroot}%{_datadir}/polkit-1/actions
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

%files
%{_bindir}/xbox-wireless-gui
%{_datadir}/xbox-wireless-gui/main.py
%{_datadir}/xbox-wireless-gui/backend/*.py
%{_datadir}/applications/com.github.xbox-wireless-gui.desktop
%{_datadir}/polkit-1/actions/org.xboxwireless.gui.policy

%changelog
* Sun Oct 18 2026 Packager <you@example.com> - 0.1.0-1
- Initial package
