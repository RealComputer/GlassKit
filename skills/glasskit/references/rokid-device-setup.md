# Rokid Setup

## Hardware

Use Rokid Glasses with the dev cable when you need direct ADB install, logs, or debugging. Non-cable APK upload flows is also possible for APK upload. Detail: https://github.com/RealComputer/GlassKit/blob/main/docs/how-to-get-rokid-glasses.md

## Wi-Fi Setup

If the device is cabled but Wi-Fi is off:

```sh
adb shell cmd wifi status
adb shell cmd wifi set-wifi-enabled enabled
adb shell 'cmd wifi connect-network "NETWORK_NAME" wpa2 "NETWORK_PASSWORD"'
adb shell cmd wifi status
```

Optional wireless connection after the device is reachable on the same network:

```sh
adb shell ip route get 1.1.1.1 | grep -oE 'src [0-9.]+' | awk '{print $2}'
adb tcpip 5555
adb connect DEVICE_IP:5555
adb devices
```

## Common Commands

- `./gradlew :app:build`: check the app module and build APKs.
- `adb install -r app/build/outputs/apk/debug/app-debug.apk`: install the debug APK on a connected device.
- `adb shell am start -n com.example.example/.MainActivity`: launch the app on a device.
- `adb logcat -c && adb logcat -v time`: view the full device log. Use `adb logcat -v time --pid "$(adb shell pidof -s com.example.example)"` to view only app logs once the app is running.
- `emulator` if available.

## Phone/Emulator

You can test apps on an Android phone or emulator for convenience, but confirm real device behavior on physical Rokid Glasses. This is especially important for camera and microphone features, which are often unstable in the emulator.

To have a consistent view with Rokid Glasses and Android devices, you can implement letterbox layout, like: `../assets/rokid-hello-world/app/src/main/java/com/example/rokidhello/HudViewportLayout.kt`

Emulator Setup example:
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

