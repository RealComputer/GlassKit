# Rokid Setup

## Hardware

Use Rokid Glasses with the development cable when you need direct ADB installs, log access, or debugging. Non-cable APK upload workflows can be useful for simple installs, but the cable is the preferred development path.

For device and cable sourcing details, see the [Rokid Glasses setup guide](https://github.com/RealComputer/GlassKit/blob/main/docs/how-to-get-rokid-glasses.md).

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
adb shell ip route get 1.1.1.1 | grep -oE 'src [0-9.]+' | awk '{print $2}'
adb tcpip 5555
adb connect DEVICE_IP:5555
adb devices
```

## Common Commands

- `./gradlew :app:build`: build the app module and produce APKs.
- `adb install -r app/build/outputs/apk/debug/app-debug.apk`: install the debug APK.
- `adb shell am start -n com.example.example/.MainActivity`: launch an installed app.
- `adb logcat -c && adb logcat -v time`: clear and stream the full device log.
- `adb logcat -v time --pid "$(adb shell pidof -s com.example.example)"`: stream only the app logs once the app is running.
- `emulator ...`: launch an Android emulator when one is available.

## Runtime Permissions

Physical Rokid Glasses do not show an interactive Android permission dialog in the HUD; runtime permission requests on-device behave as accepted, but keep normal permission request code for phone and emulator testing.

## Phone And Emulator

You can test most app flows on an Android phone or emulator for convenience, but confirm final behavior on physical Rokid Glasses. This is especially important for the camera and microphone, which are often unstable in the emulator.

If you decide to use an Android phone or emulator, refer to the [Rokid Hello World starter](../assets/rokid-hello-world/) for a viewport wrapper and touchpad navigation mapping with touchscreen controls.

## Emulator Setup

```sh
AVD=Test
API=36
ABI=$([ "$(uname -m)" = "arm64" ] && echo "arm64-v8a" || echo "x86_64")
IMG="system-images;android-$API;google_apis;$ABI"
DEVICE=pixel_9a

sdkmanager "$IMG"
echo no | avdmanager create avd -n "$AVD" -k "$IMG" --device "$DEVICE"

emulator @"$AVD" -allow-host-audio -camera-back webcam0
```
