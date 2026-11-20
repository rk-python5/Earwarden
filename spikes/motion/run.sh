#!/bin/sh
# Build the head-motion spike as a small app and run it through Launch Services, with its output
# in this terminal.
#
#     spikes/motion/run.sh calibrate
#     spikes/motion/run.sh count --minutes 60
#     spikes/motion/run.sh --output out/session.jsonl log   # send the app's output to a file
#     spikes/motion/run.sh --build-only        # build and sign the app, don't run it (CI)
#
# Why an app: macOS judges a program by the app responsible for it. Run straight from Terminal,
# the spike is Terminal's responsibility, and Terminal declares no use of motion data, so macOS
# stops it with "abort" instead of asking. Opened as its own app, it gets asked about in its own
# name, "Earwarden motion spike". Everything stays in .build/, inside the repo (D-013).
set -eu

here="$(cd "$(dirname "$0")" && pwd)"
app="$here/.build/MotionSpike.app"

(cd "$here" && swift build -c release)
rm -rf "$app"
mkdir -p "$app/Contents/MacOS"
cp "$here/.build/release/motion-spike" "$app/Contents/MacOS/motion-spike"
cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleExecutable</key>
	<string>motion-spike</string>
	<key>CFBundleIdentifier</key>
	<string>dev.earwarden.motion-spike</string>
	<key>CFBundleName</key>
	<string>Earwarden motion spike</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleShortVersionString</key>
	<string>0.0</string>
	<key>LSUIElement</key>
	<true/>
	<key>NSMotionUsageDescription</key>
	<string>Earwarden reads head motion from your AirPods to recognise nods and shakes.</string>
</dict>
</plist>
PLIST
codesign --force --sign - "$app" >/dev/null

if [ "${1:-}" = "--build-only" ]; then
    echo "Built $app"
    exit 0
fi

terminal="$(tty)"
target="$terminal"
if [ "${1:-}" = "--output" ]; then
    # The app's output can't follow a shell redirect, so name the file instead.
    mkdir -p "$(dirname "$2")"
    target="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"
    shift 2
fi
# Ctrl-C here reaches the app as an interrupt, so it prints its summary before quitting.
trap 'pkill -INT -f "$app/Contents/MacOS/motion-spike" || true' INT TERM
open -W -n --stdout "$target" --stderr "$terminal" "$app" --args "$@"
