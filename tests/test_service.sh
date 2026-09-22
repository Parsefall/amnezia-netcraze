#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
# Load functions with paths redirected into a disposable test directory.
sed '/^action=/,$d' "$ROOT/router/opt/etc/init.d/S99awg3" |
    sed "s|/opt|$TMP/opt|g;s|/var/run|$TMP/run|g" > "$TMP/lib.sh"
. "$TMP/lib.sh"
SPLIT="$ROOT/router/opt/bin/awg3-split-config"
export AWG3_PARSED_DIR="$PARSED"
mkdir -p "$TMP/bin" "$TMP/interfaces" "$TMP/ndms"
export MOCK="$TMP"
cat > "$TMP/bin/ip" <<'EOF'
#!/bin/sh
echo "ip $*" >> "$MOCK/calls"
case "$1 $2" in
    'link show') test -f "$MOCK/interfaces/$3";;
    'link set') test -f "$MOCK/interfaces/$3";;
    *) exit 1;;
esac
EOF
cat > "$TMP/bin/ndmc" <<'EOF'
#!/bin/sh
echo "ndmc $*" >> "$MOCK/calls"
set -- $2
case "$1 $2" in
    'show interface')
        if [ -f "$MOCK/ndms/$3" ]; then echo 'type: OpkgTun'; echo 'link: up'; else exit 1; fi;;
    'interface '*)
        [ ! -f "$MOCK/reject-ndms" ] || { echo 'error: rejected'; exit 0; }
        touch "$MOCK/ndms/$2";;
    'system configuration') :;;
    'ip name-server'|'ip route') :;;
    *) exit 1;;
esac
EOF
cat > "$TMP/bin/awg" <<'EOF'
#!/bin/sh
[ ! -f "$MOCK/reject-awg" ]
EOF
cat > "$TMP/bin/watchdog" <<'EOF'
#!/bin/sh
echo "watchdog $*" >> "$MOCK/calls"
EOF
chmod +x "$TMP/bin/"*
PATH="$TMP/bin:$PATH"
export PATH
AWG="$TMP/bin/awg"
WATCHDOG="$TMP/bin/watchdog"
requirements() { return 0; }
engine_alive() { test -f "$TMP/interfaces/$1"; }
ensure_engine() { touch "$TMP/interfaces/$1"; }
profile() {
    cat > "$1" <<'EOF'
[Interface]
Address = 10.0.0.2/27
PrivateKey = test
DNS = 1.1.1.1
[Peer]
PublicKey = test
AllowedIPs = 0.0.0.0/0
Endpoint = 192.0.2.1:51820
EOF
}
# An unrelated OpkgTun0 must remain untouched and never be allocated.
touch "$TMP/interfaces/opkgtun0" "$TMP/ndms/OpkgTun0"
profile "$CONF/a.conf"
start_service >/dev/null
grep -Fq "$(printf '%s\t1\tOpkgTun1' "$CONF/a.conf")" "$STATE"
test -f "$TMP/interfaces/opkgtun0"
! grep -Eq '(interface OpkgTun0 (description|down)|link set opkgtun0)' "$TMP/calls"
# Stable assignment and second profile allocation.
profile "$CONF/b.conf"
start_service >/dev/null
test "$(wc -l < "$STATE")" -eq 2
grep -Fq "$(printf '%s\t2\tOpkgTun2' "$CONF/b.conf")" "$STATE"
# Invalid profiles do not touch any network state.
printf 'PostUp = touch /tmp/not-allowed\n' >> "$CONF/a.conf"
cp "$TMP/calls" "$TMP/before"
if start_service >/dev/null 2>&1; then echo 'Malformed profile accepted'; exit 1; fi
cmp "$TMP/calls" "$TMP/before"
profile "$CONF/a.conf"
# AWG or firmware failure cannot be reported as successful.
touch "$TMP/reject-awg"
if configure "$CONF/a.conf" 1 >/dev/null; then exit 1; fi
rm "$TMP/reject-awg"
touch "$TMP/reject-ndms"
if configure "$CONF/a.conf" 1 >/dev/null; then exit 1; fi
rm "$TMP/reject-ndms"
# Removed source retains reserved ownership and never triggers broad cleanup.
rm "$CONF/a.conf"
start_service >/dev/null
test "$(wc -l < "$STATE")" -eq 2
test -f "$TMP/ndms/OpkgTun1"
stop_service >/dev/null
test ! -f "$RUN/running"
grep -Fq 'watchdog stop' "$TMP/calls"
if repair 2 >/dev/null; then echo 'Stopped service repaired'; exit 1; fi
# Corrupt / duplicate state fails closed.
printf '%s\t2\tOpkgTun2\n' "$CONF/c.conf" >> "$STATE"
if validate_state; then echo 'Duplicate index accepted'; exit 1; fi
echo 'service lifecycle tests passed'
