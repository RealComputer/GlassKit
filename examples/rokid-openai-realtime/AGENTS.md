Project overview: Real-time, vision-enabled voice assistant example for Rokid Glasses (smart glasses). The Android client (running on the glasses) directly streams microphone audio and a camera feed over WebRTC to the OpenAI Realtime API, then speaks back to the user. Our backend establishes the connection and handles function calls.

# Android (glasses) app — `rokid/`

- Entry point `MainActivity`: auto-starts streaming after camera/mic permissions; temple tap (`KEYCODE_DPAD_CENTER`/`ENTER`) toggles start/stop.
- Media: `OpenAIRealtimeClient` uses Stream WebRTC.
- Before committing changes, run `cd rokid && ./gradlew :app:assembleDebug`

# Backend — `backend/`

- Node 24, ESM. Required env: `OPENAI_API_KEY`
- Entry point `server.ts`: handles session requests, sideband, and tools.
- `POST /session` accepts SDP offer, forwards to an OpenAI endpoint with our session config, returns the SDP answer.
- Before committing changes, run `cd backend && npm run typecheck && npm run format`.
