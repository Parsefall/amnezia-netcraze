#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TEST_PYTHON=$(command -v python3)
TMP=$(mktemp -d)
cleanup_test() {
    if [ -f "$TMP/run/awg3/web.pid" ]; then
        testpid=$(cat "$TMP/run/awg3/web.pid")
        kill -TERM "$testpid" 2>/dev/null || true
    fi
    rm -rf "$TMP"
}
trap cleanup_test EXIT
# Load only definitions; all filesystem paths point at the test sandbox.
sed '/^mkdir "\$RUN\/web-service.lock"/,$d' "$ROOT/router/opt/etc/init.d/S101awg3-web" |
    sed "s|/opt|$TMP/opt|g;s|/var/run|$TMP/run|g" > "$TMP/lib.sh"
. "$TMP/lib.sh"
PYTHON=$TEST_PYTHON
mkdir -p "$(dirname "$APP")" "$BASE/web"
: > "$BASE/web-enabled"
printf '{}\n' > "$BASE/web/settings.json"
cat > "$APP" <<'PY'
import pathlib, signal, time
pathlib.Path(__file__).with_suffix('.hup').write_text(str(signal.getsignal(signal.SIGHUP) == signal.SIG_IGN))
while True:
    time.sleep(1)
PY
# An executable sentinel catches any accidental dependency on nohup.
mkdir -p "$TMP/bin"
printf '#!/bin/sh\nexit 99\n' > "$TMP/bin/nohup"
chmod +x "$TMP/bin/nohup"
PATH="$TMP/bin:$PATH"
start
alive
first=$(cat "$PIDFILE")
test "$(cat "${APP%.py}.hup")" = True
kill -HUP "$first"
sleep 1
alive
start
test "$(cat "$PIDFILE")" = "$first"
stop
! alive
test ! -f "$PIDFILE"
rm "$BASE/web-enabled"
start
test ! -f "$PIDFILE"
echo 'web service lifecycle and SIGHUP tests passed'
