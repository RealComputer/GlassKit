# Project Overview

This is a minimal Rokid Glasses app with a small HUD screen/navigation scaffold.

Rokid Glasses are Android-based smart glasses with an outward-facing camera, a monochrome HUD, microphones, speakers, and a temple touchpad. The app UI and logic can be tested on an Android phone or emulator when convenient, but use physical Rokid Glasses to confirm real device behavior. This is especially important for camera and microphone features, which are often unstable in the emulator.

# Useful Commands

- `./gradlew :app:build`: check the app module and build the APKs.
- `adb install -r app/build/outputs/apk/debug/app-debug.apk`: install the debug APK on a connected device.
- `adb shell am start -n com.example.rokidhello/.MainActivity`: launch the app on a device.
- `adb logcat -v time`: view the full device log. Use `adb logcat -v time --pid "$(adb shell pidof -s com.example.rokidhello)"` to view only app logs once the app is running.
- `emulator` if available.

# Key Files

- `app/src/main/java/com/example/rokidhello/MainActivity.kt`: activity shell for shared HUD chrome, input mapping, and screen routing.
- `app/src/main/java/com/example/rokidhello/ScreenController.kt`: shared screen IDs, input actions, and navigation results.
- `app/src/main/java/com/example/rokidhello/MenuScreenController.kt`: root menu focus and quit confirmation behavior.
- `app/src/main/java/com/example/rokidhello/HelloScreenController.kt`: example content screen.
- `app/src/main/res/layout/activity_main.xml`: title/content/footer HUD structure.
- `app/src/main/res/layout/screen_menu.xml`, `screen_hello.xml`: per-screen layouts.
