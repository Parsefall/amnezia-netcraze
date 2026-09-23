#!/bin/sh
# Update scripts only; leave daemon binaries, flags and existing tunnels in place.
set -eu
umask 077
PATH=/opt/sbin:/opt/bin:/usr/sbin:/usr/bin:/sbin:/bin
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BASE=/opt/etc/awg3
RUN=/var/run/awg3
[ "$(id -u)" = 0 ] || { echo 'ERROR: root required'; exit 1; }
[ -x /opt/etc/init.d/S99awg3 ] || { echo 'ERROR: install the router package first'; exit 1; }
/opt/bin/python3 -c 'import sys, argparse, base64, getpass, ipaddress, json, pathlib, zlib; assert sys.version_info >= (3,10)' || { echo 'ERROR: install Entware python3-light and python3-codecs'; exit 1; }
(cd "$HERE/.." && sha256sum -c SHA256SUMS) || exit 1
mkdir -p "$RUN" "$BASE/inbox" /opt/lib/awg3
chmod 700 "$BASE/inbox" /opt/lib/awg3
mkdir "$RUN/service.lock" 2>/dev/null || { echo 'ERROR: service busy; retry later'; exit 1; }
echo "$$" > "$RUN/service.lock/pid"
trap 'rm -f "$RUN/service.lock/pid"; rmdir "$RUN/service.lock"' EXIT
trap 'exit 1' HUP INT TERM
BACKUP=$(mktemp -d "$BASE/update-importer.XXXXXX")
cp -p /opt/bin/awg3-split-config "$BACKUP/awg3-split-config"
cp "$HERE/opt/bin/awg3-split-config" /opt/bin/awg3-split-config.new
chmod 755 /opt/bin/awg3-split-config.new
for name in S99awg3 S100awg3-watchdog; do
    cp -p "/opt/etc/init.d/$name" "$BACKUP/$name"
    cp "$HERE/opt/etc/init.d/$name" "/opt/etc/init.d/$name.new"
    chmod 755 "/opt/etc/init.d/$name.new"
done
[ ! -f /opt/lib/awg3/convert_profile.py ] || cp -p /opt/lib/awg3/convert_profile.py "$BACKUP/convert_profile.py"
cp "$HERE/../tools/convert_profile.py" /opt/lib/awg3/convert_profile.py.new
chmod 600 /opt/lib/awg3/convert_profile.py.new
/opt/etc/init.d/S100awg3-watchdog stop
mv -f /opt/bin/awg3-split-config.new /opt/bin/awg3-split-config
mv -f /opt/lib/awg3/convert_profile.py.new /opt/lib/awg3/convert_profile.py
for name in S99awg3 S100awg3-watchdog; do mv -f "/opt/etc/init.d/$name.new" "/opt/etc/init.d/$name"; done
/opt/etc/init.d/S100awg3-watchdog start
echo "Importer scripts updated. Backup: $BACKUP"
echo 'VPN daemon and profiles unchanged. Enable watchdog for automatic inbox processing.'
