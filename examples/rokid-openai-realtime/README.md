# Example: Rokid Glasses x OpenAI Realtime API

Real-time, vision-enabled voice assistant demo for Rokid Glasses. The glasses stream microphone audio and camera video over WebRTC to the OpenAI Realtime API, then play back the assistant's speech. A Node backend brokers the session and handles tool calls.

An IKEA wooden box assembly instruction is set up for reference. Feel free to modify and experiment with it!

[demo.webm](https://github.com/user-attachments/assets/370fe9d7-09ea-45a7-bd09-5ab090e550bc)

## Features
- End-to-end example: Rokid Glasses connect to the OpenAI Realtime API via WebRTC.
- Real-time audio and vision streaming with assistant speech playback.
- Sideband WebSocket with tool calls enabled.

## Architecture
- Android (Rokid Glasses) app (`rokid/`): captures mic and camera, streams via WebRTC, toggles start/stop with the temple button (DPAD center / Enter).
- Backend (`backend/`): `POST /session` brokers SDP with OpenAI Realtime and routes sideband/tool traffic.

See [AGENTS.md](./AGENTS.md) for dev workflow.

## Requirements
- Rokid Glasses and dev cable
- Android Studio with `adb`
- Node.js 24
- OpenAI API key (`OPENAI_API_KEY`)

## Configuration
Fill out `rokid/local.properties`:
```
SESSION_URL=http://<YOUR_BACKEND>/session
```

Create the backend env file:
```
cd backend
cp .env.example .env
# set OPENAI_API_KEY in .env
```

## Customize instruction items
Reference files:
- Instruction data: `backend/items/` (each `.txt` filename becomes an item name).
- System prompt: `backend/server.ts` (`SESSION_INSTRUCTIONS`).

## Run the backend
```
cd backend
npm install
npm run start
```

## Run the glasses app
Before running the app, connect the Rokid Glasses to your computer using the dev cable, then turn on Wi-Fi on the glasses.

```sh
adb devices # check that you see your device
adb shell cmd wifi status # see whether it's connected; if not, follow the commands below
adb shell cmd wifi set-wifi-enabled enabled
adb shell 'cmd wifi connect-network "NAME" wpa2 "PASSWORD"'
adb shell cmd wifi status # confirm the connection

# Optional:
adb shell ip -f inet addr show wlan0 # check the glasses' IP
ping -c 5 -W 3 <IP> # check connectivity: first ping may time out
adb tcpip 5555 # prepare for remote adb connection for convenience
adb connect <IP> # connect to the glasses via remote adb
adb devices # check the remote connection (you can unplug the cable afterward for convenience)
```

Then, open the `rokid/` directory in Android Studio, select Rokid Glasses as the device, and run the app.

## Roadmap
- Enable Wi-Fi from the glasses app so no manual `adb` is necessary.
- Implement a handoff pattern for when a smarter, specialized response is needed.

## Related Examples
- [Rokid Glasses x OpenAI Realtime API x RF-DETR object detection](../rokid-openai-realtime-rfdetr/README.md): An updated version of this project with backend RF-DETR vision and annotated-frame injection; explore it if you need more accurate spatial understanding.
- [Rokid Glasses x Object Detection](../rokid-rfdetr/README.md): Vision-only speedrun HUD with RF-DETR detection and split timing.
