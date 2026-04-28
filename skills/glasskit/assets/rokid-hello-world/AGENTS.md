# Project Overview

GlassKit Rokid Hello World is a minimal Kotlin Android starter for Rokid Glasses. It renders a single black-and-white HUD screen inside a 480x640 portrait viewport and keeps fullscreen mode active while the app is running.

Rokid Glasses are Android-based smart glasses with a monochrome HUD, camera, microphones, speakers, and a temple touchpad. Use black backgrounds and white foreground UI unless the app has a specific reason to display media or grayscale imagery.

# Key Files

- `app/src/main/java/ai/glasskit/hello/MainActivity.kt`: activity shell, fullscreen handling, keep-screen-on behavior, and basic `KEYCODE_ENTER` handling.
- `app/src/main/java/ai/glasskit/hello/RokidHudViewportLayout.kt`: fixed 3:4 HUD viewport container that letterboxes phone or emulator rendering to the Rokid Glasses shape.
- `app/src/main/res/layout/activity_main.xml`: single starter HUD layout.
- `app/src/main/res/values/colors.xml`: HUD black, white, and letterbox colors.
- `app/src/main/res/values/strings.xml`: app name and starter text.
- `app/src/main/AndroidManifest.xml`: launcher activity, portrait orientation, theme, and future permission declarations.
- `app/build.gradle.kts`: Android namespace, application ID, SDK versions, ABI filters, and Java compatibility.
- `README.md`: setup and quick-start instructions.

# Development Guidance

- Target the Rokid HUD as 480x640 physical pixels at 240 dpi.
- Keep UI readable in a monochrome HUD: black background, white foreground, strong contrast, and sparse text.
- Preserve root-screen back/exit behavior. On Rokid Glasses, trapping back can leave users stuck in the app.
- Keep the app portrait-only unless the product has a strong reason to change it.
- Test layout on an emulator or phone when convenient, but use physical Rokid Glasses for final validation of touchpad, camera, microphone, and speaker behavior.
- If adding camera, microphone, speaker, voice controls, or multi-screen navigation, review `examples/rokid-feature-demo/` and the GlassKit skill references before implementing device-specific behavior.

# Commands

- `./gradlew build`: run after Android changes.
- `./gradlew :app:assembleDebug`: build the debug APK.
- `adb install -r app/build/outputs/apk/debug/app-debug.apk`: install the debug APK on a connected device.
- `adb shell monkey -p ai.glasskit.hello 1`: launch the starter app.
- `adb logcat -v time --pid "$(adb shell pidof -s ai.glasskit.hello)"`: view app logs once the app is running.

# Commit Guidelines

- Start commit messages with `rokid-hello-world: `.
