#!/bin/sh
set -eu
ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
APP="$ROOT/dist/OpenArtifact.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$ROOT/tmp/swift-cache"
swiftc -swift-version 5 -target "$(uname -m)-apple-macosx12.0" "$ROOT"/desktop/*.swift -o "$APP/Contents/MacOS/OpenArtifact" \
    -module-cache-path "$ROOT/tmp/swift-cache" -framework AppKit -framework WebKit -framework Security
printf '%s\n' "$ROOT" > "$APP/Contents/Resources/checkout.txt"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>OpenArtifact</string>
<key>CFBundleIdentifier</key><string>dev.openartifact.desktop</string>
<key>CFBundleName</key><string>OpenArtifact</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>0.1.0</string>
<key>LSMinimumSystemVersion</key><string>12.0</string>
<key>NSHighResolutionCapable</key><true/>
<key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
PLIST
codesign --force --sign - "$APP"
printf 'Built %s\n' "$APP"
