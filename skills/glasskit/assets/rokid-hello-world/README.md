# GlassKit Rokid Hello World

GlassKit Rokid Hello World is the minimal starter app for Rokid Glasses. It builds a portrait Android app with a 480x640 Rokid HUD viewport, black-and-white UI, fullscreen system chrome, and basic temple touchpad handling.

See [AGENTS.md](./AGENTS.md) for project details and coding guidance.

## Requirements

- Android Studio with Android SDK Platform 36
- JDK 17 or newer
- Rokid Glasses with a development cable, or an Android phone/emulator for layout checks

## Quick Start

Build the debug APK:

```bash
./gradlew :app:assembleDebug
```

Install and launch on a connected device:

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell monkey -p ai.glasskit.hello 1
```

Run a full Gradle check before sharing changes:

```bash
./gradlew build
```

## Customize The App

After copying this starter into a new app workspace, update:

- `settings.gradle.kts`: project name
- `app/build.gradle.kts`: `namespace` and `applicationId`
- `app/src/main/AndroidManifest.xml`: app label, activity metadata, and permissions if your app needs camera, microphone, or network access
- `app/src/main/res/values/strings.xml`: visible app strings
- `app/src/main/res/layout/activity_main.xml`: HUD layout
- `app/src/main/java/ai/glasskit/hello/`: package path and Kotlin source

Keep the root screen's back behavior available. On Rokid Glasses, the temple back action is the expected way to leave the app.

## Device And Emulator Notes

Rokid Glasses are Android-based smart glasses with a portrait monochrome HUD, camera, microphones, speakers, and a temple touchpad. The known HUD target is 480x640 physical pixels at 240 dpi.

For a close emulator layout profile, use:

- Resolution: 480x640
- Density: 240 dpi
- Orientation: portrait

Emulators are useful for layout and control-flow checks. Use physical Rokid Glasses for final validation, especially once the app uses the camera, microphone, speaker, or temple touchpad gestures.

## Control Mapping

| Intent | Rokid Glasses touchpad (`KeyEvent`) | Current starter behavior |
| ------ | ----------------------------------- | ------------------------ |
| Select / OK | Tap (`KEYCODE_ENTER`) | Consumed by `MainActivity` |
| Back / exit | Back gesture | Uses Android's default activity back behavior |

For richer controls such as swipe navigation, voice commands, camera, microphone, and speaker patterns, see `examples/rokid-feature-demo/` in the GlassKit repository.
