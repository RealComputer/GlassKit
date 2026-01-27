# Realtime AI Expo mobile app

This document explains how the Expo mobile app (`client/`) and Node server (`backend/`) work together to support OpenAI’s Realtime WebRTC stack, the tooling loop, and multimodal UX.

`tech-arch.md` is an initial design snapshot and may diverge from the current implementation; treat it as historical context rather than a living spec.

## 1. Architecture Overview
- **Mobile client** (Expo Router) captures microphone audio, gathers the full SDP offer, posts it to the backend, then establishes a direct WebRTC session with OpenAI once the SDP answer comes back. After that point, audio and the `oai-events` data channel travel straight between the device and OpenAI.
- **Backend server** exists for signaling and tooling: it forwards the initial `FormData { sdp, session }` to `https://api.openai.com/v1/realtime/calls`, passes the answer SDP back to the client, and keeps the Sideband WebSocket open to execute function tools on the app’s behalf.
- **Realtime model**: `gpt-realtime` with audio+text modalities, Whisper transcription, server VAD, and a fixed voice/instructions pair.

## 2. Backend (`backend/server.ts`)
1. **Environment**
   - `OPENAI_API_KEY` (required)
   - Optional overrides: `PORT`.
2. **Session config**
   - `modalities: ["audio", "text"]` enables text deltas alongside audio playback.
   - `input_audio_transcription` defaults to Whisper for user transcripts displayed in the UI.
   - `audio.input.vad.type = "server_vad"` delegates turn-taking to the platform.
3. **/session route**
   - Accepts the SDP offer (raw body with `Content-Type: application/sdp`).
   - Creates `FormData { sdp, session }` and POSTs to OpenAI.
   - Returns the upstream SDP answer directly to the client.
4. **Sideband tools**
   - After receiving the `Location` header, opens `wss://api.openai.com/v1/realtime?call_id=...`.
   - Registers example tools (`delayed_add`, `echo_upper`) and stores pending invocation args.
   - Buffers `response.function_call_arguments.delta`, executes helper async functions, and replies with `conversation.item.create` (type `function_call_output`) followed by `response.create`.
5. **Error handling**
   - Logs Sideband `error` events, catches tool execution failures, and responds with JSON error payloads to keep the model loop alive.

**Commands:**
```bash
cd backend
npm run typecheck # Always run this after changes
npm run format # Always run this after changes
# npm run start # Note: Human does this part
```

## 3. Mobile Client (`client/`)
### 3.1 Project layout
```
client/
  app/
    _layout.tsx
    index.tsx
  src/
    realtime/OpenAIRealtimeClient.ts
    screens/VoiceChatScreen.tsx
    components/CameraModal.tsx
```

### 3.2 Realtime client
`OpenAIRealtimeClient` wraps `react-native-webrtc`:
- captures microphone audio via `mediaDevices.getUserMedia`.
- adds tracks to an `RTCPeerConnection` and creates `oai-events` data channel.
- posts the SDP offer to `${SERVER_BASE_URL}/session`; applies the answer.
- exposes helpers to send text (`input_text`) and images (Base64 JPEG) plus arbitrary events.
- emits callbacks for assistant deltas, completed responses, user transcription, and errors.

### 3.3 VoiceChatScreen UX
- **Start/Stop** buttons control the session lifecycle and append system messages.
- **Assistant stream** displays running deltas and completed responses in a chat-style FlatList.
- **Text input** sends typed prompts.
- **CameraModal** requests permissions, captures Base64 JPEGs, and posts them along with a default instruction (`"Please describe this photo in detail."`).
- Resolves the backend URL once at module load from `Constants.expoConfig?.extra?.SERVER_BASE_URL`, falling back to `http://localhost:3000` for local dev. Set this via `app.config.js` or app.json extras when targeting devices.

### 3.4 Commands
```bash
cd client
npm run typecheck # Always run this after changes
npm run lint # Always run this after changes
# npm run ios # Note: Human does this part
```
Ensure your device can reach the backend host (use LAN IP or tunneling if needed).

### 3.5 React Compiler
- `client/app.json` enables the React Compiler. The compiler handles most memoization automatically, so prefer plain functions unless referential stability is required.

## 4. Tooling & Extensibility
- **Adding tools**: register additional `function` definitions in `session.update`, then extend `runTool` with real implementations. The pending map is keyed by `call_id` to handle concurrent requests safely.
- **Streaming UI**: `assistantBufferRef` accumulates `response.text.delta` chunks; on `response.text.done`/`response.done` the buffer is flushed to the transcript list.
- **Custom session behavior**: adjust `sessionConfig` or send additional `session.update` payloads from either the backend or data channel (e.g., change instructions mid-call).
- **Vision prompts**: the default camera instruction is purposefully generic; tweak it or expose UI controls for user-provided captions.
- **Multi-call handling**: the current app maintains a single `OpenAIRealtimeClient` instance. For multi-room scenarios, create separate instances and manage component state accordingly.
