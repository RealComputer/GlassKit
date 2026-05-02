# Project Overview

This is a starter app for Rokid Glasses with a simple screen and navigation scaffold.

# About Rokid Glasses

- Rokid Glasses are Android-based smart glasses with an outward-facing camera, a monochrome HUD, microphones, speakers, and a temple touchpad.
- The temple touchpad supports four common controls: tap for select, double-tap for back, swipe forward for next, and swipe backward for previous. Keep double-tap available on the root screen so users can exit the app.
- You can test the app on an Android phone or emulator for convenience, but confirm real device behavior on physical Rokid Glasses. This is especially important for camera and microphone features, which are often unstable in the emulator.
- Rokid Glasses use a green monochrome binocular display with a portrait 3:4 viewport. Use black backgrounds and white foregrounds; on the device, black appears transparent and white appears green. Other colors can be used for media such as images, but the device renders them as green, transparent, or intermediate brightness levels.

# Key Files

- `MainActivity.kt` is the entry point.
- `NavigationInputMapper.kt` maps Rokid Glasses touchpad and phone/emulator gestures to navigation actions.
- `ScreenController.kt` defines screen IDs, navigation actions, and screen commands.
- `activity_main.xml` defines the shared screen structure.
- `MenuScreenController.kt` owns menu focus and the root-screen quit confirmation.
- `HelloScreenController.kt`/`screen_hello.xml` are example content.

# Useful Commands

- `./gradlew :app:build`: check the app module and build APKs.
- `adb install -r app/build/outputs/apk/debug/app-debug.apk`: install the debug APK on a connected device.
- `adb shell am start -n com.example.rokidhello/.MainActivity`: launch the app on a device.
- `adb logcat -c && adb logcat -v time`: view the full device log. Use `adb logcat -v time --pid "$(adb shell pidof -s com.example.rokidhello)"` to view only app logs once the app is running.
- `emulator` if available.
