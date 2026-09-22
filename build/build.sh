#!/usr/bin/env bash
# Recommended userspace build. The old kernel scripts are unsupported research.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKDIR="${WORKDIR:-$ROOT/outputs/userspace-build}"
OUTPUT_DIR="${OUTPUT_DIR:-$ROOT/prebuilt/kn-1012}"
COMMIT=b5928efb6ca19f0153958460c3d141f04abc5c2e
mkdir -p "$WORKDIR" "$OUTPUT_DIR"
SRC="$WORKDIR/amneziawg-go"
if [ ! -d "$SRC/.git" ]; then
    git clone --depth 1 --branch v3.1.20260828 https://github.com/amnezia-vpn/amneziawg-go.git "$SRC"
fi
[ "$(git -C "$SRC" rev-parse HEAD)" = "$COMMIT" ] || { echo 'Source revision mismatch'; exit 1; }
PATCH="$ROOT/build/patches/002-go-tun-padding-refresh.patch"
if [ -z "$(git -C "$SRC" status --porcelain)" ]; then
    git -C "$SRC" apply "$PATCH"
fi
[ "$(git -C "$SRC" status --porcelain)" = " M device/send.go" ] || { echo 'Unexpected source modifications'; exit 1; }
git -C "$SRC" diff -- device/send.go | cmp - "$PATCH" || { echo 'Source patch mismatch'; exit 1; }
cd "$SRC"
export GOTOOLCHAIN=local CGO_ENABLED=0 GOOS=linux GOARCH=arm64
go build -trimpath -buildvcs=true -ldflags '-s -w' -o "$OUTPUT_DIR/amneziawg-go" .
go version -m "$OUTPUT_DIR/amneziawg-go"
echo 'Repackage with python build/package.py after changing binaries.'
