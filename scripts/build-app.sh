#!/bin/zsh
# Builds Conductor.app from the SwiftPM product (no Xcode project needed).
set -euo pipefail
cd "$(dirname "$0")/.."
CONF=${1:-release}
swift build -c "$CONF" 2>&1 | grep -Ev "^\s*$" | tail -5
BIN=$(swift build -c "$CONF" --show-bin-path)
APP="build/Conductor.app"
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN/Conductor" "$APP/Contents/MacOS/Conductor"
cp Sources/Conductor/Info.plist "$APP/Contents/Info.plist"
echo "APPL????" > "$APP/Contents/PkgInfo"
# Sign with a real identity when one exists so TCC grants (mic/speech) survive rebuilds;
# ad-hoc signatures change with every build and macOS forgets the permissions each time.
# Set CONDUCTOR_SIGN=adhoc to force ad-hoc signing (macOS will then re-ask mic/speech after every rebuild).
IDENTITY=$(security find-identity -v -p codesigning 2>/dev/null | awk -F'"' 'NR==1{print $2}')
[ "${CONDUCTOR_SIGN:-}" = "adhoc" ] && IDENTITY=""
codesign --force --sign "${IDENTITY:--}" --identifier ai.conductor.app --options runtime --timestamp=none \
  --entitlements scripts/Conductor.entitlements "$APP"
echo "Signed as: ${IDENTITY:-ad-hoc}"
echo "Built $APP"
