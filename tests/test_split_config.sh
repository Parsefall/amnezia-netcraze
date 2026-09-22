#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP=$(mktemp -d)
cleanup() {
    rm -f "$TMP/input.conf" "$TMP/error.log"
    rm -f "$TMP/parsed/opkgtun0.awg.conf" "$TMP/parsed/opkgtun0.ndms.sh"
    rmdir "$TMP/parsed" "$TMP"
}
trap cleanup EXIT

cat > "$TMP/input.conf" <<'EOF'
[Interface]
MTU = 1280
Address = 10.8.1.3/32
DNS = 1.1.1.1
PrivateKey = test-private-key
I1 = <r 2><b 0x8580>
I2 = <rc 8><t>
HeaderProtectionKey = test-header-key
RandomTrailers = on

[Peer]
PublicKey = test-public-key
AllowedIPs = 0.0.0.0/0
Endpoint = 192.0.2.1:51820
EOF

AWG3_PARSED_DIR="$TMP/parsed" sh "$ROOT/router/opt/bin/awg3-split-config" "$TMP/input.conf" >/dev/null
AWG_CONF="$TMP/parsed/opkgtun0.awg.conf"
NDMS_SH="$TMP/parsed/opkgtun0.ndms.sh"

grep -Fqx 'I1 = <r 2><b 0x8580>' "$AWG_CONF"
grep -Fqx 'I2 = <rc 8><t>' "$AWG_CONF"
grep -Fqx 'HeaderProtectionKey = test-header-key' "$AWG_CONF"
grep -Fq 'interface $NDMS_IFACE ip address 10.8.1.3 255.255.255.255' "$NDMS_SH"
if grep -Eq '^(Address|DNS|MTU) =' "$AWG_CONF"; then
    echo "Router-only settings leaked into AWG configuration" >&2
    exit 1
fi

printf 'Bad = 1\n' >> "$TMP/input.conf"
if AWG3_PARSED_DIR="$TMP/parsed" sh "$ROOT/router/opt/bin/awg3-split-config" "$TMP/input.conf" >"$TMP/error.log" 2>&1; then
    echo "Unsupported parameter was accepted" >&2
    exit 1
fi
grep -Fq 'ERROR: unsupported parameter:' "$TMP/error.log"

if [ "$#" -gt 0 ]; then
    AWG3_PARSED_DIR="$TMP/parsed" sh "$ROOT/router/opt/bin/awg3-split-config" "$1" >/dev/null
    SOURCE_I1=$(sed -n 's/^I1 = //p' "$1")
    PARSED_I1=$(sed -n 's/^I1 = //p' "$AWG_CONF")
    [ -n "$SOURCE_I1" ] && [ "$SOURCE_I1" = "$PARSED_I1" ]
    echo "Provided profile parsed with I1 preserved"
fi

echo "split-config tests passed"
