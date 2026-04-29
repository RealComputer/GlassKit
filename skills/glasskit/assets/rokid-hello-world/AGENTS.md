# Project Overview

This is a minimal Rokid Glasses app.

Rokid Glasses are Android-based smart glasses with an outward-facing camera, a monochrome HUD, microphones, speakers, and a temple touchpad. App UI and logics can be tested on an Android phone or an emulator when convenient, but use physical Rokid Glasses to confirm actual behaviour, especially since the emulator is unstable around camera and mic.

# Useful Commands

- `./gradlew :app:build`: check the app module and build APKs.
- `adb install -r app/build/outputs/apk/debug/app-debug.apk`: install the debug APK on a connected device.
- `adb shell monkey -p ai.glasskit.hello -c android.intent.category.LAUNCHER 1`: launch the app on a device.
- `adb logcat -v time`: view the full device log. Use `adb logcat -v time --pid "$(adb shell pidof -s ai.glasskit.hello)"` to view only app logs once the app is running.
- `emulator` if available.
