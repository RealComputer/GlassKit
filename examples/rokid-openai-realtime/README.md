# Rokid OpenAI Realtime (audio + vision)

Real-time voice assistant demo for Rokid Glasses. The Android app streams microphone audio and camera video over WebRTC to the OpenAI Realtime API, then plays back the assistant's speech. A small Node backend brokers the session and handles tool calls.

## Architecture
- Android app (`rokid/`): captures mic + camera, streams via WebRTC, toggles start/stop with the temple button (DPAD center / Enter).
- Backend (`backend/`): `POST /session` brokers SDP with OpenAI Realtime and routes sideband/tool traffic.

## Requirements
- Rokid Glasses + dev cable
- Android Studio + ADB
- Node.js 24
- OpenAI API key (`OPENAI_API_KEY`)

## Configuration
Create `rokid/local.properties` (gitignored):
```
SESSION_URL=http://<YOUR_BACKEND>:3000/session
```

Create the backend env file:
```
cd backend
cp .env.example .env
# set OPENAI_API_KEY in .env
```

## Run the backend
```
cd backend
npm install
npm run start
```

## Run the glasses app
1. Open `rokid/` in Android Studio and select the Rokid Glasses device.
2. Build the APK: `./gradlew :app:assembleDebug`
3. Run from Android Studio.

## Rokid device setup (one-time)
Connect the glasses over USB first, then enable Wi-Fi:
```
adb devices
adb shell cmd wifi status
adb shell cmd wifi set-wifi-enabled enabled
adb shell cmd wifi connect-network <NAME> wpa2 <PASSWORD>
adb shell cmd wifi status
```

Optional remote ADB over Wi-Fi:
```
adb shell ip -f inet addr show wlan0
adb tcpip 5555
adb connect <IP>
adb devices
```

## Project layout
- `rokid/`: Android app.
- `backend/`: Node session broker.
- `AGENTS.md`: dev workflow notes (build/test expectations).
