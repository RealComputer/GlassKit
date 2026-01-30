The Rokid Glasses Android app streams microphone audio to the OpenAI Realtime session (via the backend) and sends low-rate camera video to the backend for RF-DETR detection. Tap the temple button (DPAD center/Enter) to start or stop the voice + vision link.

Configure the backend URLs in `rokid/local.properties` (gitignored):

```
SESSION_URL=http://YourBackend:3000/session
VISION_SESSION_URL=http://YourBackend:3000/vision/session
```

Before running the app, connect the Rokid Glasses to your computer using the dev cable, then turn on Wi-Fi on the glasses.

```sh
adb devices # check that you see your device
adb shell cmd wifi status # see whether it's connected; if not, follow the commands below
adb shell cmd wifi set-wifi-enabled enabled
adb shell cmd wifi connect-network <NAME> wpa2 <PASSWORD>
adb shell cmd wifi status # confirm the connection

# Optional:
adb shell ip -f inet addr show wlan0 # check the glasses' IP
ping -c 5 -W 3 <IP> # check connectivity: first ping may time out
adb tcpip 5555 # prepare for remote adb connection for convenience
adb connect <IP> # connect to the glasses via remote adb
adb devices # check the remote connection (you can unplug the cable afterward for convenience)
```

Open this directory in Android Studio, select Rokid Glasses as the device, and run the app.

Build:
```
./gradlew :app:assembleDebug
```
