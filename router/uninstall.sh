#!/bin/sh
set -eu
PATH=/opt/sbin:/opt/bin:/usr/sbin:/usr/bin:/sbin:/bin
[ ! -x /opt/etc/init.d/S101awg3-web ] || /opt/etc/init.d/S101awg3-web disable
rm -f /opt/etc/init.d/S101awg3-web
# Preserve profiles, binaries, NDMS objects and policies. Destruction is explicit.
[ ! -x /opt/etc/init.d/S99awg3 ] || /opt/etc/init.d/S99awg3 disable
[ ! -x /opt/etc/init.d/S100awg3-watchdog ] || /opt/etc/init.d/S100awg3-watchdog disable
rm -f /opt/etc/init.d/S99awg3 /opt/etc/init.d/S100awg3-watchdog
echo 'Autostart scripts removed; profiles, binaries and NDMS policy objects preserved.'
echo 'Down TUN processes remain until reboot to preserve interface routes.'
