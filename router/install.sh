#!/bin/sh
# Stage files only. Never load a kernel module, import a key, or start a VPN.
set -eu
umask 077
PATH=/opt/sbin:/opt/bin:/usr/sbin:/usr/bin:/sbin:/bin
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PAYLOAD=$HERE/../prebuilt/kn-1012
BASE=/opt/etc/awg3
[ "$(id -u)" = 0 ] || { echo 'ERROR: root required'; exit 1; }
[ "$(uname -m)" = aarch64 ] || { echo 'ERROR: aarch64 required'; exit 1; }
[ -d /opt/bin ] && [ -d /opt/etc ] || { echo 'ERROR: install Entware first'; exit 1; }
[ -c /dev/net/tun ] || { echo 'ERROR: TUN device missing'; exit 1; }
[ ! -f /var/run/awg3/running ] || { echo 'ERROR: stop AWG3 before updating'; exit 1; }
for name in awg amneziawg-go; do [ -s "$PAYLOAD/$name" ] || { echo "ERROR: missing $PAYLOAD/$name"; exit 1; }; done
# A stopped service keeps TUN processes alive. Reboot with autostart disabled
# before an upgrade; replacing a live executable breaks process identity checks.
for pidfile in /var/run/awg3/opkgtun*.pid; do
    [ -f "$pidfile" ] || continue
    pid=$(cat "$pidfile")
    case "$pid" in ''|*[!0-9]*) echo 'ERROR: invalid engine PID record'; exit 1;; esac
    if kill -0 "$pid" 2>/dev/null; then echo 'ERROR: engine still running; disable service and reboot before updating'; exit 1; fi
done
# Verify every distributed file, not just the binaries.
(cd "$HERE/.." && sha256sum -c SHA256SUMS) || { echo 'ERROR: package checksum failed'; exit 1; }
# Check executables before replacing installed files.
chmod 755 "$PAYLOAD/awg" "$PAYLOAD/amneziawg-go"
"$PAYLOAD/awg" --version
"$PAYLOAD/amneziawg-go" --version
mkdir -p "$BASE/inbox" /opt/lib/awg3 "$BASE/conf/parsed" /opt/etc/init.d /opt/var/log /var/run/awg3
chmod 700 "$BASE/inbox" /opt/lib/awg3 "$BASE" "$BASE/conf" "$BASE/conf/parsed" /var/run/awg3
mkdir /var/run/awg3/service.lock 2>/dev/null || { echo 'ERROR: service busy'; exit 1; }
trap 'rmdir /var/run/awg3/service.lock' EXIT
BACKUP=$BASE/backups/$(date +%Y%m%d-%H%M%S)-$$
mkdir -p "$BACKUP"
# Refuse legacy daemons before replacing their executable paths.
if [ -x /opt/etc/init.d/S100awg3-watchdog ]; then /opt/etc/init.d/S100awg3-watchdog stop; fi
for path in bin/awg bin/amneziawg-go bin/awg3-split-config etc/init.d/S99awg3 etc/init.d/S100awg3-watchdog; do
    if [ -f "/opt/$path" ]; then mkdir -p "$BACKUP/$(dirname "$path")"; cp -p "/opt/$path" "$BACKUP/$path"; fi
done
# Stage all files on the destination filesystem, then rename them.
cp "$PAYLOAD/awg" /opt/bin/awg.new
cp "$PAYLOAD/amneziawg-go" /opt/bin/amneziawg-go.new
cp "$HERE/opt/bin/awg3-split-config" /opt/bin/awg3-split-config.new
cp "$HERE/opt/etc/init.d/S99awg3" /opt/etc/init.d/S99awg3.new
cp "$HERE/opt/etc/init.d/S100awg3-watchdog" /opt/etc/init.d/S100awg3-watchdog.new
for path in bin/awg bin/amneziawg-go bin/awg3-split-config etc/init.d/S99awg3 etc/init.d/S100awg3-watchdog; do
    chmod 755 "/opt/$path.new"
    mv -f "/opt/$path.new" "/opt/$path"
done
if [ -f /opt/lib/awg3/convert_profile.py ]; then cp -p /opt/lib/awg3/convert_profile.py "$BACKUP/convert_profile.py"; fi
cp "$HERE/../tools/convert_profile.py" /opt/lib/awg3/convert_profile.py.new
chmod 600 /opt/lib/awg3/convert_profile.py.new
mv -f /opt/lib/awg3/convert_profile.py.new /opt/lib/awg3/convert_profile.py
# Back up boot flags and leave the first run manual after every installation.
for flag in enabled watchdog-enabled; do
    [ ! -f "$BASE/$flag" ] || cp -p "$BASE/$flag" "$BACKUP/$flag"
    rm -f "$BASE/$flag"
done
cp "$HERE/opt/etc/awg3/conf/awg3_example.conf" "$BASE/example.conf.disabled"
echo "Files installed. Backup: $BACKUP"
echo "VPN NOT started. No module loaded. No profile imported."
echo "Import an IPv4 client profile into $BASE/conf, chmod 600, then run:"
echo "/opt/etc/init.d/S99awg3 up"
echo "/opt/etc/init.d/S99awg3 status"
