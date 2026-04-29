# Project Overview

This is a minimal Rokid Glasses app.

Rokid Glasses are Android-based smart glasses with an outward-facing camera, a monochrome HUD, microphones, speakers, and a temple touchpad. The app UI and logic can be tested on an Android phone or emulator when convenient, but use physical Rokid Glasses to confirm real device behavior. This is especially important for camera and microphone features, which are often unstable in the emulator.

# Useful Commands

- `./gradlew :app:build`: check the app module and build the APKs.
- `adb install -r app/build/outputs/apk/debug/app-debug.apk`: install the debug APK on a connected device.
- `adb shell monkey -p ai.glasskit.hello -c android.intent.category.LAUNCHER 1`: launch the app on a device.
- `adb logcat -v time`: view the full device log. Use `adb logcat -v time --pid "$(adb shell pidof -s ai.glasskit.hello)"` to view only app logs once the app is running.
- `emulator` if available.
