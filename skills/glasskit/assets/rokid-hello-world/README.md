# Rokid Glasses Hello World

This is a minimal starter app for Rokid Glasses. It includes a small HUD
structure with a menu, a content screen, and footer navigation hints.

See [AGENTS.md](./AGENTS.md) for technical details and guidance.

## Requirements

- `adb`
- Rokid Glasses with a dev cable (preferred), or an Android phone or emulator for quick checks

## Quick Start

```sh
./gradlew :app:assembleDebug                               # Build
adb install -r app/build/outputs/apk/debug/app-debug.apk   # Install
adb shell am start -n com.example.rokidhello/.MainActivity # Launch
```

## Device

Use physical Rokid Glasses for final testing. An Android phone is useful for quick UI checks, and an emulator can work for basic smoke tests, but camera and microphone passthrough are often not stable or performant enough.

## App Structure

The UI uses a simple screen-controller pattern:

- `MainActivity.kt` owns shared HUD chrome, input routing, and current-screen navigation.
- `NavigationInputMapper.kt` maps Rokid touchpad and phone/emulator gestures to navigation actions.
- `ScreenController.kt` defines screen IDs, navigation actions, and screen commands.
- `MenuScreenController.kt` owns menu focus and the root-screen quit confirmation.
- `HelloScreenController.kt` is the example content screen.
- `activity_main.xml` defines the shared header, content frame, and footer.
- `screen_menu.xml` and `screen_hello.xml` define per-screen content.

To add another screen, add a `ScreenId`, create a `ScreenController`, include its
layout in `activity_main.xml`, register the controller in `MainActivity`, and add a
menu item in `MenuScreenController`.

## Controls

| Intent | Rokid Glasses touchpad | Android phone/emulator touchscreen |
| --- | --- | --- |
| Select / OK | Tap | Tap |
| Back / cancel | Double tap | Double tap |
| Next | Swipe forward | Swipe right |
| Previous | Swipe backward | Swipe left |

Keep Back available on the root screen so users can exit the app on Rokid
Glasses. Inner screens can use Back for in-app navigation, but the root screen
should still let Back close the app.

In this template, Back from the menu first updates the footer to ask for
confirmation. Press Back again to quit. Tapping or swiping clears the quit
confirmation. The app-visible footer describes this as double-tap for Rokid
Glass users.

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
