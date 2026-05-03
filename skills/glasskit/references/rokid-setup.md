# Rokid Setup

Use this when connecting Rokid Glasses, preparing ADB access, installing builds, collecting logs, or setting up a phone/emulator fallback.

## Hardware

Use Rokid Glasses with the development cable when you need direct ADB installs, logs, or debugging. Non-cable APK upload workflows can be useful for simple installs, but the cable is the preferred development path.

For device and cable sourcing details, see the [Rokid Glasses setup guide](../../../docs/how-to-get-rokid-glasses.md).

## Device Wi-Fi

If the device is connected by cable but Wi-Fi is disabled, enable Wi-Fi and join a network through ADB:

```sh
adb shell cmd wifi status
adb shell cmd wifi set-wifi-enabled enabled
adb shell 'cmd wifi connect-network "NETWORK_NAME" wpa2 "NETWORK_PASSWORD"'
adb shell cmd wifi status
```

After the device is reachable on the same network as the development machine, you can switch to wireless ADB:

```sh
DEVICE_IP=$(adb shell ip route get 1.1.1.1 | awk '{for (i = 1; i <= NF; i++) if ($i == "src") print $(i + 1)}')
adb tcpip 5555
adb connect "$DEVICE_IP:5555"
adb devices
```

## Android Studio

Open the Android project directory, select the connected Rokid device, and run the app from Android Studio. If the device does not appear, verify it with `adb devices` first, then reconnect the development cable or restart ADB if needed.

## Common Commands

- `./gradlew :app:build`: build the app module and produce APKs.
- `adb install -r app/build/outputs/apk/debug/app-debug.apk`: install the debug APK on a connected device.
- `adb shell am start -n com.example.example/.MainActivity`: launch an installed app; replace the package and activity with the app's values.
- `adb logcat -c && adb logcat -v time`: clear and stream the full device log.
- `adb logcat -v time --pid "$(adb shell pidof -s com.example.example)"`: stream only the app logs once the app is running.
- `emulator @AVD_NAME`: launch an Android emulator when one is available.

## Phone And Emulator

You can test most app flows on an Android phone or emulator for convenience, but confirm final behavior on physical Rokid Glasses. This is especially important for camera, microphone, speaker, performance, and touchpad behavior, which can differ from phone and emulator behavior.

Use a fixed 3:4 HUD viewport wrapper so phone and emulator previews stay close to the Rokid display shape. The starter app includes an example at `../assets/rokid-hello-world/app/src/main/java/com/example/rokidhello/HudViewportLayout.kt`.

For apps that need touchpad navigation, map phone/emulator touch gestures to the same select, back, next, and previous actions used by the Rokid touchpad.

## Emulator Setup

This example creates an Android emulator with host audio and webcam input. It requires the Android SDK command-line tools on `PATH`.

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
