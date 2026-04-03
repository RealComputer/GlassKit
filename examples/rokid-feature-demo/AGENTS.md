# Project Overview

Rokid Feature Demo is a Rokid Glasses app for testing device features and common implementation patterns:

- touchpad and voice command navigation
- camera
- microphone
- speaker
- touch gesture support on Android touchscreens, including phones and the Android emulator (mirrors the Rokid Glasses touchpad controls)

Rokid Glasses are Android-based smart glasses with a camera, a monochrome HUD, microphones, speakers, and a touchpad. Use black and white UI only.

## Screens

- Menu
- Camera: live camera preview
- Audio: test tones
- Microphone: live level meter and current voice-command status

# Key Files

- `app/src/main/java/com/example/rokidfeaturedemo/MainActivity.kt`: activity shell for the shared lifecycle, permissions, Rokid/emulator input mapping, and screen navigation.
- `app/src/main/java/com/example/rokidfeaturedemo/RokidHudViewportLayout.kt`: fixed 3:4 HUD viewport container that keeps phone rendering letterboxed to the Rokid/emulator shape.
- `app/src/main/java/com/example/rokidfeaturedemo/ScreenController.kt`: shared screen abstractions and navigation results for the HUD screens.
- `app/src/main/java/com/example/rokidfeaturedemo/MenuScreenController.kt`, `CameraScreenController.kt`, `AudioScreenController.kt`, `MicrophoneScreenController.kt`: per-screen state, rendering, and action handling.
- `app/src/main/java/com/example/rokidfeaturedemo/VoiceCommandRecognizer.kt`: Vosk model unpacking, endpoint tuning, `AudioRecord` loop, partial/final parsing, and command dispatch.
- `app/src/main/res/layout/activity_main.xml`: shared HUD chrome that includes the per-screen layouts.
- `app/src/main/res/layout/screen_menu.xml`, `screen_camera.xml`, `screen_audio.xml`, `screen_microphone.xml`: individual screen panel layouts.
- `README.md`: setup

# Commands

- `./gradlew build`: always run after Android changes
- `./gradlew :app:assembleDebug`: debug APK build
- `emulator -avd glass_480x640 -camera-back emulated`: launch the emulator
- `adb logcat -v time --pid "$(adb shell pidof -s com.example.rokidfeaturedemo)"`: general-purpose app log view once the demo is running

# Commit Guidelines

- Start message with "rokid-feature-demo: "
