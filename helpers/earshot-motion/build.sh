#!/bin/sh
# Build the signed helper as EarshotMotion.app, for earshotd --helper (Phase 2, milestone 7).
#
#     helpers/earshot-motion/build.sh
#
# macOS judges a program by its app and that app's signature. Signed with a fixed identity, the
# mic and motion permissions survive a rebuild (D-016). Set EARSHOT_SIGNING_IDENTITY to your Apple
# Development certificate's name (`security find-identity -v -p codesigning` lists them).
# Without it, the app is signed ad hoc: it works, but macOS asks again after each rebuild.
# Everything stays in .build/, inside the repo (D-013).
set -eu

here="$(cd "$(dirname "$0")" && pwd)"
app="$here/.build/EarshotMotion.app"
identity="${EARSHOT_SIGNING_IDENTITY:--}"

(cd "$here" && swift build -c release)
rm -rf "$app"
mkdir -p "$app/Contents/MacOS"
cp "$here/.build/release/earshot-motion" "$app/Contents/MacOS/earshot-motion"
cp "$here/Sources/EarshotMotion/Info.plist" "$app/Contents/Info.plist"
codesign --force --sign "$identity" --identifier dev.earshot.motion "$app"
codesign --verify "$app"
if [ "$identity" = "-" ]; then
    echo "Built $app, signed ad hoc (set EARSHOT_SIGNING_IDENTITY to keep permissions across builds)."
else
    echo "Built $app, signed as $identity."
fi
