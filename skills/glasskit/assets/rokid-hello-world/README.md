# Rokid Glasses Hello World

This is the minimal starter app for Rokid Glasses.

See [AGENTS.md](./AGENTS.md) for technical details and guidance.

## Requirements

- `adb`
- Rokid Glasses with a dev cable (preferred), or an Android phone/emulator for quick checks

## Quick Start

```sh
./gradlew :app:assembleDebug                                                # Build
adb install -r app/build/outputs/apk/debug/app-debug.apk                    # Install
adb shell monkey -p ai.glasskit.hello -c android.intent.category.LAUNCHER 1 # Launch
```

## Device

Prefer the actual device for testing, but an Android phone can be used as well. Also, Android emulator works, but camera and microphone passthrough are often not stable or performant enough.

Emulator setup example:

```sh
AVD=Test
API=36
ABI=$([ "$(uname -m)" = "arm64" ] && echo "arm64-v8a" || echo "x86_64")
IMG="system-images;android-$API;google_apis;$ABI"
DEVICE=pixel_9a

sdkmanager "$IMG"
echo no | avdmanager create avd -n "$AVD" -k "$IMG" --device "$DEVICE"

emulator @"$AVD" \
  -allow-host-audio \
  -camera-front webcam0 \
  -camera-back webcam0
```
