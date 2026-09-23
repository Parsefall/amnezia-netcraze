#!/bin/sh
# Optional web panel. Does not start/stop VPN or change routing.
set -eu
umask 077
PATH=/opt/sbin:/opt/bin:/usr/sbin:/usr/bin:/sbin:/bin
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BASE=/opt/etc/awg3
[ ! -d /var/run/awg3/update.lock ] || { echo "ERROR: panel update in progress"; exit 1; }
[ "$(id -u)" = 0 ] || { echo 'ERROR: root required'; exit 1; }
[ -x /opt/etc/init.d/S99awg3 ] || { echo 'ERROR: install the VPN package first'; exit 1; }
/opt/bin/python3 -c 'import sys,ssl,http.server,hashlib,ipaddress,json,secrets,zlib,tarfile,urllib.request,shutil; assert sys.version_info >= (3,10)' || { echo 'ERROR: install python3-light python3-codecs python3-openssl python3-email python3-urllib python3-logging'; exit 1; }
[ -x /opt/bin/openssl ] || { echo 'ERROR: install openssl-util'; exit 1; }
(cd "$HERE/.." && sha256sum -c SHA256SUMS) || exit 1
# Install current import/service scripts first, preserving engine and profiles.
sh "$HERE/update-importer.sh"
mkdir -p "$BASE/web" /opt/lib/awg3/web
chmod 700 "$BASE/web" /opt/lib/awg3/web
BACKUP=$(mktemp -d "$BASE/web/update.XXXXXX")
if [ -x /opt/etc/init.d/S101awg3-web ]; then
    /opt/etc/init.d/S101awg3-web stop
    cp -p /opt/etc/init.d/S101awg3-web "$BACKUP/S101awg3-web"
fi
for file in server.py index.html app.js style.css updater.py VERSION UPDATE_FORMAT; do
    [ ! -f "/opt/lib/awg3/web/$file" ] || cp -p "/opt/lib/awg3/web/$file" "$BACKUP/$file"
    cp "$HERE/../web/$file" "/opt/lib/awg3/web/$file.new"
    chmod 600 "/opt/lib/awg3/web/$file.new"
    mv -f "/opt/lib/awg3/web/$file.new" "/opt/lib/awg3/web/$file"
done
cp "$HERE/opt/etc/init.d/S101awg3-web" /opt/etc/init.d/S101awg3-web.new
chmod 755 /opt/etc/init.d/S101awg3-web.new
mv -f /opt/etc/init.d/S101awg3-web.new /opt/etc/init.d/S101awg3-web
if [ -f "$BASE/web/settings.json" ]; then
    /opt/etc/init.d/S101awg3-web start
    echo 'Panel updated; existing password and LAN settings retained.'
else
    echo 'Panel installed, not started. Create password and LAN binding:'
    echo '/opt/bin/python3 /opt/lib/awg3/web/server.py --setup --bind 192.168.1.1 --network 192.168.1.0/24'
    echo 'Then: /opt/etc/init.d/S101awg3-web enable'
fi
