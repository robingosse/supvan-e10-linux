# Troubleshooting

## Label Studio says no printer queue was found

1. Confirm the service is running:

   ```bash
   systemctl --user status supvan-printer-app
   ```

2. Confirm CUPS can see printers:

   ```bash
   lpstat -p -d
   ```

3. In Label Studio, click **Refresh** beside the queue field.

## CUPS says `filter failed`

Older Label Studio experiments submitted a custom-size PDF. That path is no
longer used. The public candidate submits the exact E10 raster as `image/jpeg`.

If you still see `filter failed`, make sure you are running the Label Studio
from this repository and restart it after upgrading.

## Bluetooth reports `Host is down`

Physical E10 power loss can leave BlueZ temporarily claiming a connection that
no longer exists. The driver contains narrow self-healing for the observed
RFCOMM `EHOSTDOWN` signature and retries Classic Bluetooth once after clearing
that stale BlueZ link.

If the problem persists:

```bash
bluetoothctl info <PRINTER_MAC>
systemctl --user restart supvan-printer-app
```

Do not remove/re-pair the printer unless ordinary restart/recovery fails.

## See the driver log

```bash
journalctl --user -u supvan-printer-app --no-pager -n 150
```

For more detail:

```bash
RUST_LOG=supvan_printer_app=debug,supvan_proto=debug \
  ~/.cargo/bin/supvan-printer-app
```

Stop the user service first if running the binary manually.

## A job prints at the wrong length

Label Studio exact-raster jobs are 88 pixels wide. Their image height is the
requested feed length in dots. If you are printing from another application,
normal CUPS/JPEG media fitting rules apply instead.
