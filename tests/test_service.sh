#!/bin/sh
set -eu
TEST_PYTHON=$(command -v python3 || command -v python)
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
# Import through the real converter, with firmware/engine calls mocked.
PYTHON=$TEST_PYTHON
CONVERTER=$ROOT/tools/convert_profile.py
cat > "$TMP/new.conf" <<'EOF'
[Interface]
Address = 10.8.0.4/32
PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
DNS = 9.9.9.9
[Peer]
PublicKey = AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=
AllowedIPs = 0.0.0.0/0
Endpoint = 192.0.2.20:51820
EOF
cp "$STATE" "$TMP/state-before"
: > "$TMP/calls"
import_profile "$TMP/new.conf" b >/dev/null
cmp "$STATE" "$TMP/state-before"
grep -q 'Endpoint = 192.0.2.20' "$CONF/b.conf"
grep -q 'MTU = 1280' "$CONF/b.conf"
! grep -q '^DNS =' "$CONF/b.conf"
! grep -Eq '(ip global|ip route|ip name-server|description|down)' "$TMP/calls"
cp "$CONF/b.conf" "$TMP/accepted"
cp "$TMP/calls" "$TMP/before"
printf 'vpn://not-valid' > "$TMP/bad.txt"
if import_profile "$TMP/bad.txt" b >/dev/null 2>&1; then exit 1; fi
cmp "$CONF/b.conf" "$TMP/accepted"
grep -v "show interface" "$TMP/calls" > "$TMP/mutations-after"
grep -v "show interface" "$TMP/before" > "$TMP/mutations-before"
cmp "$TMP/mutations-after" "$TMP/mutations-before"
if import_profile "$TMP/new.conf" ../escape >/dev/null 2>&1; then exit 1; fi
if import_profile "$TMP/new.conf" unknown >/dev/null 2>&1; then exit 1; fi
# Simulate engine rejecting a new configuration while accepting rollback.
cat > "$TMP/bin/awg" <<'EOF'
#!/bin/sh
if [ "$1" = setconf ] && grep -q '192.0.2.99:' "$3"; then exit 1; fi
exit 0
EOF
sed 's/192.0.2.20:/192.0.2.99:/' "$TMP/new.conf" > "$TMP/rejected.conf"
if import_profile "$TMP/rejected.conf" b > "$TMP/rejection"; then exit 1; fi
grep -q 'previous configuration restored' "$TMP/rejection"
cmp "$CONF/b.conf" "$TMP/accepted"
# Incomplete uploads are ignored; complete files are consumed exactly once.
mkdir -p "$BASE/inbox"
cp "$TMP/new.conf" "$BASE/inbox/b.vpn.part"
cp "$TMP/bad.txt" "$BASE/inbox/b.txt"
scan_inbox >/dev/null 2>&1
test -f "$BASE/inbox/b.vpn.part"
test ! -f "$BASE/inbox/b.txt"
grep -q rejected "$BASE"/inbox/item.*/result
cp "$TMP/new.conf" "$BASE/inbox/b.vpn"
scan_inbox >/dev/null
test ! -f "$BASE/inbox/b.vpn"
grep -q applied "$BASE"/inbox/item.*/result
# A real encoded key in .txt traverses the complete inbox pipeline.
"$PYTHON" -c 'import sys,json,zlib,base64; from pathlib import Path; native=Path(sys.argv[1]).read_text(); raw=json.dumps({"containers":[{"awg":{"last_config":json.dumps({"config":native})}}]}).encode(); Path(sys.argv[2]).write_text("vpn://"+base64.urlsafe_b64encode(len(raw).to_bytes(4,"big")+zlib.compress(raw)).decode().rstrip("="))' "$TMP/new.conf" "$BASE/inbox/b.txt"
scan_inbox >/dev/null
test ! -f "$BASE/inbox/b.txt"
cmp "$CONF/b.conf" "$TMP/accepted"
# Stop/import stores new credentials without bringing the service back up.
stop_service >/dev/null
: > "$TMP/calls"
import_profile "$TMP/new.conf" b >/dev/null
test ! -s "$TMP/calls"
test ! -f "$RUN/running"
# Existing interfaces retain firmware priority on later startup.
: > "$TMP/calls"
start_service >/dev/null
! grep -q 'ip global auto' "$TMP/calls"

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
