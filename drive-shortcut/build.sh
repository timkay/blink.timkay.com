#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
build=.build/drive-shortcut
sdk=.build/sdk
mkdir -p "$build/classes" "$build/dex"
javac -source 8 -target 8 -classpath "$sdk/android-35/android.jar" -d "$build/classes" drive-shortcut/MainActivity.java
"$sdk/android-15/d8" --lib "$sdk/android-35/android.jar" --output "$build/dex" "$build/classes/com/timkay/driverecent/MainActivity.class"
"$sdk/android-15/aapt" package -f -M drive-shortcut/AndroidManifest.xml -I "$sdk/android-35/android.jar" -F "$build/unsigned.apk"
(cd "$build/dex" && zip -q -u ../unsigned.apk classes.dex)
"$sdk/android-15/zipalign" -f 4 "$build/unsigned.apk" "$build/aligned.apk"
"$sdk/android-15/apksigner" sign --ks .build/overlay.keystore --ks-key-alias overlay --ks-pass pass:android --out "$build/drive-recent.apk" "$build/aligned.apk"
