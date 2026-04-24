# Rokid Device Setup

Use this when setting up physical Rokid Glasses, running the starter asset, or reproducing a Rokid-sized emulator.

## Hardware And Connection

- Use Rokid Glasses with the official or equivalent development cable when you need direct ADB install, logs, or debugging.
- Non-cable APK upload flows can be useful for quick installs, but they do not replace direct ADB debugging.
- Keep the Android app portrait-only unless the product has a strong reason to do otherwise; the HUD target is 480x640 at 240 dpi.

## Mac-Like Development Setup

Install Android Studio and Android SDK Platform 36. Make sure `adb` is available through Android Studio's platform-tools.

Common checks:

```bash
adb devices
adb shell wm size
adb shell wm density
```

Known Rokid HUD values:

```text
Physical size: 480x640
Physical density: 240
```

## Wi-Fi Setup Through ADB

If the device is cabled but Wi-Fi is off:

```bash
adb shell cmd wifi status
adb shell cmd wifi set-wifi-enabled enabled
adb shell 'cmd wifi connect-network "NETWORK_NAME" wpa2 "NETWORK_PASSWORD"'
```

Optional wireless debugging after the device is reachable on the same network:

```bash
adb shell ip route
adb tcpip 5555
adb connect DEVICE_IP:5555
adb devices
```

Use the IP reported by the device network route or Wi-Fi status. Keep the cable available for recovery if wireless debugging drops.

## Running An App

For the bundled starter asset, from the skill directory:

```bash
cd assets/rokid-hello-world
./gradlew :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell monkey -p ai.glasskit.hello 1
```

After copying the starter into an app workspace, run the same Gradle and ADB commands from the copied starter directory.

## Emulator Profile

For layout checks without physical hardware, create an Android emulator or resizable profile close to:

- Resolution: 480x640
- Density: 240 dpi
- Orientation: portrait
- Camera: rear/outward camera emulation if the feature uses CameraX/WebRTC video
- Microphone: host passthrough when testing Vosk or direct Realtime audio

Emulator camera/mic timing can differ from Rokid hardware. Treat it as layout and control-flow validation, not final media validation.
