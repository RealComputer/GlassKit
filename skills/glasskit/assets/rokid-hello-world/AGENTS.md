# Project Overview

This is a Rokid Glasses starter app with a screen and navigation scaffold.

# About Rokid Glasses

- Rokid Glasses are Android-based smart glasses with an outward-facing camera, a monochrome HUD, microphones, speakers, and a temple touchpad.
- In the app, app can use tap (select), double-tap (back), swipe forward (next), and swipe backward (previsous). Keep the double-tap available to exit the Rokid Glasses as it's the only way to quit the app.
- The app can be tested on an Android phone or emulator for convinience, but use actual Rokid Glasses to confirm real device behavior, especially for camera and microphone features, which are often unstable in the emulator.
- They have a green monochrome binocular display (portrait 3:4) on the lenses. Use black backgrounds and white foregrounds; on the device, black appears transparent and white appears green. Other colors can be used for media such as images, but the device still renders them as green, transparent, or intermediate brightness levels.

# Key Files

- `MainActivity.kt` is the entry point.
- `NavigationInputMapper.kt` maps Rokid Glasses touchpad and phone/emulator gestures to navigation actions.
- `ScreenController.kt` defines screen IDs, navigation actions, and screen commands.
- `activity_main.xml` defines the shared screen structure.
- `MenuScreenController.kt` owns menu focus and the root-screen quit confirmation.
- `HelloScreenController.kt`/`screen_hello.xml` are example content.

# Useful Commands

- `./gradlew :app:build`: check the app module and build the APKs.
- `adb install -r app/build/outputs/apk/debug/app-debug.apk`: install the debug APK on a connected device.
- `adb shell am start -n com.example.rokidhello/.MainActivity`: launch the app on a device.
- `adb logcat -c && adb logcat -v time`: view the full device log. Use `adb logcat -v time --pid "$(adb shell pidof -s com.example.rokidhello)"` to view only app logs once the app is running.
- `emulator` if available.
