#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
SPLIT="$ROOT/router/opt/bin/awg3-split-config"
export AWG3_PARSED_DIR="$TMP/parsed"
mkdir -p "$TMP/bin"
cat > "$TMP/base" <<'EOF'
[Interface]
Address = 10.0.0.2/27
MTU = 1280
DNS = 1.1.1.1, 8.8.8.8
PrivateKey = test-private
I1 = <r 2><b 0x8580>
[Peer]
PublicKey = test-public
AllowedIPs = 0.0.0.0/0
Endpoint = 192.0.2.1:51820
EOF
sh "$SPLIT" "$TMP/base" >/dev/null
grep -Fq '255.255.255.224' "$TMP/parsed/opkgtun0.ndms.sh"
sh -n "$TMP/parsed/opkgtun0.ndms.sh"
cp "$TMP/parsed/opkgtun0.awg.conf" "$TMP/good"
# All IPv4 prefixes, CRLF and leading comments.
p=0
while [ "$p" -le 32 ]; do
    sed "s|10.0.0.2/27|10.0.0.2/$p|" "$TMP/base" | sed 's/$/\r/' > "$TMP/in"
    sh "$SPLIT" "$TMP/in" >/dev/null
    p=$((p+1))
done
sh "$SPLIT" "$TMP/base" >/dev/null
for bad in '10.0.0.999/24' '10.0.0.1/33' '10.0.0.1' '10.0.0.1/24;reboot' '::1/128'; do
    sed "s|10.0.0.2/27|$bad|" "$TMP/base" > "$TMP/in"
    if sh "$SPLIT" "$TMP/in" >/dev/null 2>&1; then echo 'Invalid address accepted'; exit 1; fi
    cmp "$TMP/good" "$TMP/parsed/opkgtun0.awg.conf"
done
for field in 'DNS = $(touch injected)' 'MTU = 1280;reboot' 'PostUp = reboot'; do
    sed '/^DNS =/d;/^MTU =/d' "$TMP/base" | sed "/^PrivateKey/i $field" > "$TMP/in"
    if sh "$SPLIT" "$TMP/in" >/dev/null 2>&1; then echo 'Unsafe field accepted'; exit 1; fi
done
if sh "$SPLIT" "$TMP/base" '../../escape' >/dev/null 2>&1; then exit 1; fi
if sh "$SPLIT" "$TMP/base" opkgtun0 'OpkgTun0;reboot' >/dev/null 2>&1; then exit 1; fi
# Execute the generated script against a recorder, checking exact DNS arguments.
cat > "$TMP/bin/ndmc" <<'EOF'
#!/bin/sh
printf '%s\n' "$2" >> "$CALLS"
[ "${REJECT:-0}" = 0 ] || echo 'Command::Base error[7405602]: argument parse error.'
EOF
chmod +x "$TMP/bin/ndmc"
export CALLS="$TMP/calls"
PATH="$TMP/bin:$PATH" sh "$TMP/parsed/opkgtun0.ndms.sh"
grep -Fxq 'ip name-server 1.1.1.1 "" on OpkgTun0' "$CALLS"
if REJECT=1 PATH="$TMP/bin:$PATH" sh "$TMP/parsed/opkgtun0.ndms.sh" >/dev/null 2>&1; then exit 1; fi
echo 'parser edge case tests passed'

# AllowedIPs never grants permission to change the system default route.
if grep -Fq 'ip route default' "$CALLS"; then
    echo 'Parser must not change default routing'; exit 1
fi
sed 's|AllowedIPs = 0.0.0.0/0|AllowedIPs = 10.20.0.0/16|' "$TMP/base" > "$TMP/split"
sh "$SPLIT" "$TMP/split" >/dev/null
if grep -Fq 'ip route default' "$TMP/parsed/opkgtun0.ndms.sh"; then
    echo 'Split-tunnel profile incorrectly gets a default route'; exit 1
fi
