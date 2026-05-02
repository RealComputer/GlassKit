# Rokid Glasses Starter

This is a starter app for Rokid Glasses with a simple screen and navigation scaffold.

See [AGENTS.md](./AGENTS.md) for technical details and guidance.

## Requirements

- `adb`
- Rokid Glasses with a development cable (preferred), or an Android phone or emulator for quick checks

## Quick Start

```sh
./gradlew :app:assembleDebug                               # Build
adb install -r app/build/outputs/apk/debug/app-debug.apk   # Install
adb shell am start -n com.example.rokidhello/.MainActivity # Launch
```

## Control Convention

| Intent | Rokid Glasses touchpad | Android phone/emulator touchscreen |
| --- | --- | --- |
| Select / OK | Tap | Tap |
| Back / cancel | Double tap | Double tap |
| Next | Swipe forward | Swipe right |
| Previous | Swipe backward | Swipe left |

## Emulator Setup Example

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
