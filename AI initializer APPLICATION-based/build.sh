#!/usr/bin/env bash
# build.sh — macOS app build & run
# Made by Viperwraith47 — https://github.com/viperwraith47
set -euo pipefail

APP_NAME="${APP_NAME:-MyMacApp}"
SCHEME="${SCHEME:-$APP_NAME}"
CONFIGURATION="${CONFIGURATION:-Debug}"
DERIVED_DATA="${DERIVED_DATA:-./.build/DerivedData}"
OPEN_APP="${OPEN_APP:-1}"

echo "═══════════════════════════════════════════"
echo "  $APP_NAME — build by Viperwraith47"
echo "  https://github.com/viperwraith47"
echo "═══════════════════════════════════════════"

if compgen -G "*.xcworkspace" > /dev/null; then
  WORKSPACE=$(ls -1 *.xcworkspace | head -n1)
  echo "→ Building workspace: $WORKSPACE"
  xcodebuild \
    -workspace "$WORKSPACE" \
    -scheme "$SCHEME" \
    -configuration "$CONFIGURATION" \
    -derivedDataPath "$DERIVED_DATA" \
    -destination 'platform=macOS' \
    build
  APP_PATH=$(find "$DERIVED_DATA" -name "${APP_NAME}.app" -type d | head -n1)
elif compgen -G "*.xcodeproj" > /dev/null; then
  PROJECT=$(ls -1 *.xcodeproj | head -n1)
  echo "→ Building project: $PROJECT"
  xcodebuild \
    -project "$PROJECT" \
    -scheme "$SCHEME" \
    -configuration "$CONFIGURATION" \
    -derivedDataPath "$DERIVED_DATA" \
    -destination 'platform=macOS' \
    build
  APP_PATH=$(find "$DERIVED_DATA" -name "${APP_NAME}.app" -type d | head -n1)
else
  echo "→ Building with Swift Package Manager"
  swift build -c "$(echo "$CONFIGURATION" | tr '[:upper:]' '[:lower:]')"
  if [[ "$OPEN_APP" == "1" ]]; then
    swift run
    exit 0
  fi
  APP_PATH=""
fi

if [[ -n "${APP_PATH:-}" && -d "$APP_PATH" ]]; then
  echo "✓ Built: $APP_PATH"
  if [[ "$OPEN_APP" == "1" ]]; then
    echo "→ Launching…"
    open "$APP_PATH"
  fi
else
  echo "✓ Build finished."
fi

echo "Done. Made by Viperwraith47 → https://github.com/viperwraith47"
