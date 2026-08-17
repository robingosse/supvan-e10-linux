# Installation

## Supported release target

The first public candidate targets Linux Mint / Ubuntu-style systems using
systemd, BlueZ and CUPS.

## Dependencies

```bash
sudo apt install \
  build-essential cargo pkg-config libdbus-1-dev \
  bluez cups avahi-daemon \
  python3 python3-gi gir1.2-gtk-3.0 python3-pil python3-qrcode \
  cups-client fonts-dejavu-core
```

The Rust workspace uses edition 2024. If your distribution's Rust toolchain is
too old, install a current Rust toolchain with rustup and re-run the installer.

## Pair the E10

The easiest route on Linux Mint is the graphical Bluetooth settings panel.
Pair and trust the printer whose name begins with `T0010`.

You can also use `bluetoothctl` manually if needed.

## Install both components

From the repository root:

```bash
./install.sh
```

The driver is installed as a user-scoped systemd service and Label Studio is
installed under the normal XDG user directories.

## Verify the driver

```bash
systemctl --user status supvan-printer-app
lpstat -p
```

The exact CUPS queue name can vary. Label Studio detects available queues on
startup and has a **Refresh** button next to the queue field.

## Remove the suite

```bash
./uninstall.sh
```
