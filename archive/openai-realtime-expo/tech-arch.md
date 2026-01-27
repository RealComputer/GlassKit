# Realtime WebRTC Client for React Native + Expo

**Scope:** complete Expo app code + setup. Realtime audio chat with AI, live transcript, text input, on‑device photo capture → image caption spoken by AI. Uses server‑created `/v1/realtime/calls` and server‑only Sideband WS for tools.

## 1) Requirements and assumptions

* **Expo Dev Client** build is required. Expo Go cannot load native WebRTC. ([GitHub][2])
* **react-native-webrtc** with Expo config plugin. ([GitHub][3])
* **expo-camera** to capture a photo and export Base64. ([Expo Documentation][4])
* Server exposes `POST /session` that forwards the SDP offer to `https://api.openai.com/v1/realtime/calls` with `FormData { sdp, session }` and returns the **answer SDP**. The same server opens **Sideband** WS using `wss://api.openai.com/v1/realtime?call_id=...` for tools. ([OpenAI Platform][1])
* Enable input transcription in session: `input_audio_transcription: { model: "whisper-1" }`. ([Microsoft Learn][6])
* Vision inputs use content parts `[{"type":"input_text"}, {"type":"input_image","image_url":"data:image/jpeg;base64,..."}]`. ([GitHub][7])

## 2) High‑level flow

1. RN client creates RTCPeerConnection, adds **mic** track and **data channel** `"oai-events"`.
2. Client POSTs **SDP offer** to your server `/session`.
3. Server POSTs to **`/v1/realtime/calls`** with `{sdp, session}`. Returns **answer SDP** and `Location` header with `call_id`. Server also opens **Sideband WS** for tools using that `call_id`. ([OpenAI Platform][1])
4. Client sets remote answer. Remote audio track plays via RN WebRTC. ([GitHub][2])
5. Events:

   * User speech → server VAD commits → AI speaks back; stream **text** via `response.text.delta`. User transcript via `conversation.item.input_audio_transcription.completed`. ([Microsoft Learn][5])
   * Text send: send `conversation.item.create` with `input_text`, then `response.create`. ([Microsoft Learn][5])
   * Photo: capture Base64 JPEG → send `input_image` + short instruction text → `response.create`. ([Expo Documentation][4])
   * Tools: Sideband receives function call (`response.output_item.added` + `response.function_call_arguments.*`), runs async function, sends `function_call_output`, then `response.create`. ([Microsoft Learn][8])

## 3) Install and configure

Already setup

## 4) Project structure

```
/App.tsx
/src/realtime/OpenAIRealtimeClient.ts
/src/screens/VoiceChatScreen.tsx
/src/components/CameraModal.tsx
```

## 5) Full source code

### `/App.tsx`

```tsx
import React from "react";
import { SafeAreaView, StatusBar } from "react-native";
import VoiceChatScreen from "./src/screens/VoiceChatScreen";

export default function App() {
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: "#111" }}>
      <StatusBar barStyle="light-content" />
      <VoiceChatScreen />
    </SafeAreaView>
  );
}
```

### `/src/realtime/OpenAIRealtimeClient.ts`

```ts
// A thin Realtime WebRTC client for OpenAI.
// - WebRTC PC + mic track, data channel `oai-events`
// - POST SDP offer to your server /session -> get answer SDP
// - Handle Realtime events: response.text.delta/.done, user transcription, etc.
// Event names and shapes follow docs. See:
//   - WebRTC call creation via /v1/realtime/calls
//   - Server events like response.text.delta, response.function_call_arguments.*
//   - Sideband WS is handled on your server (tools), not here.

import {
  RTCPeerConnection,
  mediaDevices,
  MediaStream,
  RTCIceCandidateType,
  RTCSessionDescriptionType,
} from "react-native-webrtc";
import { Platform } from "react-native";

type Listener = (evt: any) => void;

export type TranscriptEntry = {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
};

export type OpenAIRealtimeClientOptions = {
  serverBaseUrl: string; // e.g., http://localhost:3000
  instructions?: string;
};

export default class OpenAIRealtimeClient {
  pc: RTCPeerConnection | null = null;
  dc: RTCDataChannel | null = null;
  localStream: MediaStream | null = null;
  started = false;

  // Simple event listeners
  onServerEvent: Listener | null = null;
  onTranscriptDelta: ((role: "assistant", delta: string) => void) | null = null;
  onTranscriptDone: ((role: "assistant", text: string) => void) | null = null;
  onUserTranscript: ((text: string) => void) | null = null;
  onError: ((err: Error) => void) | null = null;

  constructor(private opts: OpenAIRealtimeClientOptions) {}

  // Start: mic capture, peerconnection, data channel, create offer -> POST /session
  async start() {
    if (this.started) return;
    this.started = true;

    // 1) Prepare mic
    const stream = await mediaDevices.getUserMedia({
      audio: true,
      video: false,
    });
    this.localStream = stream;

    // 2) Prepare RTCPeerConnection
    this.pc = new RTCPeerConnection({
      // Unified Plan is default in RN WebRTC
      // ICE servers are optional; OpenAI’s Realtime uses public STUN internally.
      iceServers: [{ urls: ["stun:stun.l.google.com:19302"] }],
    });

    // Add mic track
    stream.getTracks().forEach((t) => this.pc!.addTrack(t, stream));

    // 3) Data channel for events
    this.dc = this.pc.createDataChannel("oai-events");
    this.dc.onopen = () => {
      // Optionally push initial instruction override per response
      // Keep session-level instructions in server `session` if preferred.
    };
    this.dc.onmessage = (ev) => this.handleServerMessage(ev.data);

    // 4) Auto-play remote audio track (RN WebRTC plays remote audio by default)
    this.pc.ontrack = (_ev) => {
      // No UI element needed for audio. Track plays through device speaker.
    };

    // 5) Create offer
    const offer = await this.pc.createOffer({
      offerToReceiveAudio: true,
      offerToReceiveVideo: false,
    });
    await this.pc.setLocalDescription(offer);

    // 6) POST SDP offer to your server -> /session
    const resp = await fetch(`${this.opts.serverBaseUrl}/session`, {
      method: "POST",
      headers: { "Content-Type": "application/sdp" },
      body: offer.sdp ?? "",
    });
    if (!resp.ok) {
      throw new Error(`/session failed: ${resp.status} ${await resp.text()}`);
    }
    const answerSdp = await resp.text();
    const answer: RTCSessionDescriptionType = {
      type: "answer",
      sdp: answerSdp,
    };
    await this.pc.setRemoteDescription(answer);
  }

  async stop() {
    if (!this.started) return;
    this.started = false;
    try {
      this.dc?.close();
      this.pc?.getTransceivers().forEach((t) => t.stop && t.stop());
      this.pc?.close();
    } finally {
      this.dc = null;
      this.pc = null;
      this.localStream?.getTracks().forEach((t) => t.stop());
      this.localStream = null;
    }
  }

  // Send a text as user
  sendUserText(text: string) {
    if (!this.dc || this.dc.readyState !== "open") return;
    const ev1 = {
      type: "conversation.item.create",
      item: {
        type: "message",
        role: "user",
        content: [{ type: "input_text", text }],
      },
    };
    const ev2 = { type: "response.create" };
    this.dc.send(JSON.stringify(ev1));
    this.dc.send(JSON.stringify(ev2));
  }

  // Send a photo as input_image (base64 JPEG without data: prefix; we add it here)
  sendUserImageBase64JPEG(b64: string, instruction?: string) {
    if (!this.dc || this.dc.readyState !== "open") return;
    const parts: any[] = [];
    if (instruction && instruction.trim().length) {
      parts.push({ type: "input_text", text: instruction });
    }
    parts.push({
      type: "input_image",
      image_url: `data:image/jpeg;base64,${b64}`,
    });
    const ev1 = {
      type: "conversation.item.create",
      item: {
        type: "message",
        role: "user",
        content: parts,
      },
    };
    const ev2 = { type: "response.create" };
    this.dc.send(JSON.stringify(ev1));
    this.dc.send(JSON.stringify(ev2));
  }

  // Parse server events
  private handleServerMessage(raw: string) {
    let msg: any;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }
    this.onServerEvent?.(msg);

    switch (msg.type) {
      case "response.text.delta":
        this.onTranscriptDelta?.("assistant", msg.delta ?? "");
        return;
      case "response.text.done":
        // msg?.text may be present in some impls; otherwise accumulate externally
        return;
      case "response.done":
        // end of response; caller can finalize accumulated text
        return;
      case "conversation.item.input_audio_transcription.completed":
        // user speech transcript (requires input_audio_transcription in session)
        if (msg.transcript) this.onUserTranscript?.(msg.transcript);
        return;
      case "error":
        this.onError?.(new Error(msg?.error?.message ?? "realtime error"));
        return;
      default:
        return;
    }
  }
}
```

### `/src/components/CameraModal.tsx`

```tsx
import React, { useRef, useState } from "react";
import { Modal, View, TouchableOpacity, Text } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";

export default function CameraModal({
  visible,
  onClose,
  onShot,
}: {
  visible: boolean;
  onClose: () => void;
  onShot: (base64: string) => void;
}) {
  const cameraRef = useRef<CameraView>(null);
  const [perm, requestPerm] = useCameraPermissions();
  const [ready, setReady] = useState(false);

  if (!perm?.granted) {
    return (
      <Modal visible={visible} transparent>
        <View style={{ flex: 1, backgroundColor: "#000a", alignItems: "center", justifyContent: "center" }}>
          <TouchableOpacity onPress={requestPerm} style={{ padding: 16, backgroundColor: "#fff" }}>
            <Text>Grant camera permission</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={onClose} style={{ padding: 16, marginTop: 12, backgroundColor: "#ddd" }}>
            <Text>Cancel</Text>
          </TouchableOpacity>
        </View>
      </Modal>
    );
  }

  return (
    <Modal visible={visible} animationType="slide">
      <View style={{ flex: 1, backgroundColor: "black" }}>
        <CameraView
          ref={cameraRef}
          style={{ flex: 1 }}
          facing="back"
          onCameraReady={() => setReady(true)}
        />
        <View style={{ position: "absolute", bottom: 40, width: "100%", alignItems: "center" }}>
          <TouchableOpacity
            onPress={async () => {
              if (!cameraRef.current || !ready) return;
              // @ts-ignore: takePictureAsync available on CameraView via ref
              const shot = await cameraRef.current.takePictureAsync({
                base64: true,
                quality: 0.8,
                skipProcessing: true,
              });
              if (shot?.base64) onShot(shot.base64);
              onClose();
            }}
            style={{ width: 84, height: 84, borderRadius: 42, backgroundColor: "#fff" }}
          />
          <TouchableOpacity onPress={onClose} style={{ marginTop: 16 }}>
            <Text style={{ color: "white" }}>Close</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}
```

*Base64 option is supported and returns JPEG data. Prepend data URL when sending.* ([Expo Documentation][4])

### `/src/screens/VoiceChatScreen.tsx`

```tsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import { View, Text, TouchableOpacity, TextInput, FlatList, Platform } from "react-native";
import Constants from "expo-constants";
import OpenAIRealtimeClient, { TranscriptEntry } from "../realtime/OpenAIRealtimeClient";
import CameraModal from "../components/CameraModal";

export default function VoiceChatScreen() {
  const serverBaseUrl = Constants.expoConfig?.extra?.SERVER_BASE_URL || "http://localhost:3000";
  const client = useMemo(
    () => new OpenAIRealtimeClient({ serverBaseUrl }),
    [serverBaseUrl]
  );

  const [running, setRunning] = useState(false);
  const [cameraVisible, setCameraVisible] = useState(false);
  const [entries, setEntries] = useState<TranscriptEntry[]>([]);
  const [assistantBuffer, setAssistantBuffer] = useState<string>("");
  const [text, setText] = useState("");

  // Wire events
  useEffect(() => {
    client.onTranscriptDelta = (_role, delta) => {
      setAssistantBuffer((prev) => prev + delta);
    };
    client.onTranscriptDone = (_role, txt) => {
      // not used; finalize on response.done
    };
    client.onUserTranscript = (t) => {
      append({ role: "user", text: t });
    };
    client.onServerEvent = (msg) => {
      if (msg.type === "response.done") {
        if (assistantBuffer.trim().length) {
          append({ role: "assistant", text: assistantBuffer });
          setAssistantBuffer("");
        }
      }
    };
    client.onError = (e) => {
      append({ role: "system", text: `Error: ${e.message}` });
    };
    return () => { /* no-op */ };
  }, [client, assistantBuffer]);

  const append = (e: Omit<TranscriptEntry, "id">) => {
    setEntries((prev) => [{ id: Math.random().toString(36).slice(2), ...e }, ...prev]);
  };

  return (
    <View style={{ flex: 1, backgroundColor: "#111", paddingTop: 8 }}>
      {/* Controls */}
      <View style={{ paddingHorizontal: 12, gap: 8 }}>
        {!running ? (
          <TouchableOpacity
            onPress={async () => {
              try {
                await client.start();
                setRunning(true);
              } catch (e: any) {
                append({ role: "system", text: `Start failed: ${e?.message ?? e}` });
              }
            }}
            style={{ backgroundColor: "#2e7d32", padding: 12, borderRadius: 8 }}
          >
            <Text style={{ color: "white", textAlign: "center" }}>Start</Text>
          </TouchableOpacity>
        ) : (
          <>
            <TouchableOpacity
              onPress={async () => {
                await client.stop();
                setRunning(false);
              }}
              style={{ backgroundColor: "#c62828", padding: 12, borderRadius: 8 }}
            >
              <Text style={{ color: "white", textAlign: "center" }}>Stop</Text>
            </TouchableOpacity>

            {/* Take photo and describe */}
            <TouchableOpacity
              onPress={() => setCameraVisible(true)}
              style={{ backgroundColor: "#1565c0", padding: 12, borderRadius: 8 }}
            >
              <Text style={{ color: "white", textAlign: "center" }}>
                Take photo and ask AI to describe
              </Text>
            </TouchableOpacity>

            {/* Text input */}
            <View style={{ flexDirection: "row", gap: 8 }}>
              <TextInput
                placeholder="Type text to send"
                placeholderTextColor="#999"
                value={text}
                onChangeText={setText}
                style={{
                  flex: 1,
                  backgroundColor: "#222",
                  color: "white",
                  paddingHorizontal: 12,
                  paddingVertical: 10,
                  borderRadius: 8,
                }}
              />
              <TouchableOpacity
                onPress={() => {
                  if (!text.trim()) return;
                  append({ role: "user", text });
                  client.sendUserText(text);
                  setText("");
                }}
                style={{ backgroundColor: "#424242", paddingHorizontal: 16, justifyContent: "center", borderRadius: 8 }}
              >
                <Text style={{ color: "white" }}>Send</Text>
              </TouchableOpacity>
            </View>
          </>
        )}
      </View>

      {/* Transcript list */}
      <FlatList
        data={[
          ...(assistantBuffer
            ? [{ id: "__buffer", role: "assistant", text: assistantBuffer } as TranscriptEntry]
            : []),
          ...entries,
        ]}
        keyExtractor={(i) => i.id}
        contentContainerStyle={{ padding: 12, gap: 8 }}
        renderItem={({ item }) => (
          <View
            style={{
              backgroundColor: item.role === "assistant" ? "#1b5e20" : item.role === "user" ? "#283593" : "#424242",
              padding: 10,
              borderRadius: 8,
            }}
          >
            <Text style={{ color: "white", fontWeight: "600" }}>{item.role}</Text>
            <Text style={{ color: "white" }}>{item.text}</Text>
          </View>
        )}
        inverted
      />

      <CameraModal
        visible={cameraVisible}
        onClose={() => setCameraVisible(false)}
        onShot={(b64) => {
          append({ role: "user", text: "[photo]" });
          // Minimal instruction so model speaks a caption
          client.sendUserImageBase64JPEG(
            b64,
            "Please describe this photo in one concise sentence and then speak it."
          );
        }}
      />
    </View>
  );
}
```

## 6) Server

* On WS open: send `session.update` to register **tools** and enable **transcription**.
* Handle function calls:
  * Capture `response.output_item.added` with `item.type === "function_call"` to learn `name` and `call_id`.
  * Accumulate args from `response.function_call_arguments.delta`, finalize on `.done`.
  * Execute async function.
  * Send `conversation.item.create` with `{ type:"function_call_output", call_id, output }` then `response.create`. ([Microsoft Learn][8])

### code

```ts
import http from "node:http";
import { text } from "node:stream/consumers";
import WebSocket from "ws";

const PORT = Number(process.env.PORT ?? 3000);
const OPENAI_API_KEY = process.env.OPENAI_API_KEY;
if (!OPENAI_API_KEY) throw new Error("Set OPENAI_API_KEY in env");

// Default session; can be overridden by client via session.update later
const sessionConfig = {
  type: "realtime",
  model: "gpt-realtime",
  modalities: ["audio", "text"],
  input_audio_transcription: { model: "whisper-1" }, // enable user transcript
  audio: {
    input: { // server VAD for turn-taking
      vad: { type: "server_vad" }
    },
    output: { voice: "marin" }
  },
  // Optional starter instructions
  instructions:
    "You are a helpful voice assistant.",
};

type PendingTool = { name: string; args: string };
const pendingByCallId = new Map<string, PendingTool>();

// Example async tools
async function delayed_add({ a, b }: { a: number; b: number }) {
  await new Promise((r) => setTimeout(r, 800));
  return { sum: Number(a) + Number(b) };
}
async function echo_upper({ text }: { text: string }) {
  await new Promise((r) => setTimeout(r, 400));
  return { result: String(text).toUpperCase() };
}

const server = http.createServer(async (req, res) => {
  try {
    const pathname = req.url ?? "/";

    if (req.method === "POST" && pathname === "/session") {
      const sdp = await text(req);

      const fd = new FormData();
      fd.set("sdp", sdp);
      fd.set("session", JSON.stringify(sessionConfig));

      const upstream = await fetch("https://api.openai.com/v1/realtime/calls", {
        method: "POST",
        headers: { Authorization: `Bearer ${OPENAI_API_KEY}` },
        body: fd,
        signal: AbortSignal.timeout(10_000),
      });

      const location = upstream.headers.get("location");
      const callId = location?.split("/").pop();

      if (callId) {
        const url = `wss://api.openai.com/v1/realtime?call_id=${callId}`;
        const ws = new WebSocket(url, {
          headers: { Authorization: `Bearer ${OPENAI_API_KEY}` },
        });

        ws.on("open", () => {
          console.log("sideband connected", callId);

          // Register tools and allow overrides at runtime
          ws.send(
            JSON.stringify({
              type: "session.update",
              session: {
                // Add function tools
                tools: [
                  {
                    type: "function",
                    name: "delayed_add",
                    description: "Add two numbers slowly",
                    parameters: {
                      type: "object",
                      properties: {
                        a: { type: "number" },
                        b: { type: "number" },
                      },
                      required: ["a", "b"],
                    },
                  },
                  {
                    type: "function",
                    name: "echo_upper",
                    description: "Uppercase a string",
                    parameters: {
                      type: "object",
                      properties: { text: { type: "string" } },
                      required: ["text"],
                    },
                  },
                ],
              },
            })
          );
        });

        ws.on("message", async (d) => {
          let msg: any;
          try {
            msg = JSON.parse(d.toString());
          } catch {
            console.log("sideband", d.toString());
            return;
          }

          // Observe tool call creation
          if (msg.type === "response.output_item.added" && msg.item?.type === "function_call") {
            const { call_id, name } = msg.item;
            if (call_id && name) pendingByCallId.set(call_id, { name, args: "" });
            return;
          }

          if (msg.type === "response.function_call_arguments.delta") {
            const callId = msg.call_id;
            const p = pendingByCallId.get(callId);
            if (p) p.args += msg.delta ?? "";
            return;
          }

          if (msg.type === "response.function_call_arguments.done") {
            const callId = msg.call_id;
            const p = pendingByCallId.get(callId);
            if (!p) return;
            pendingByCallId.delete(callId);

            let parsed: any = {};
            try {
              parsed = JSON.parse(p.args || msg.arguments || "{}");
            } catch {
              parsed = { _raw: p.args || msg.arguments };
            }

            // Execute tool asynchronously
            let out: any;
            try {
              if (p.name === "delayed_add") out = await delayed_add(parsed);
              else if (p.name === "echo_upper") out = await echo_upper(parsed);
              else out = { error: `unknown tool: ${p.name}` };
            } catch (e: any) {
              out = { error: String(e?.message || e) };
            }

            // Send function_call_output, then ask model to continue
            ws.send(
              JSON.stringify({
                type: "conversation.item.create",
                item: {
                  type: "function_call_output",
                  call_id: callId,
                  output: JSON.stringify(out),
                },
              })
            );
            ws.send(JSON.stringify({ type: "response.create" }));
            return;
          }

          // Debug logging
          if (msg.type === "error") {
            console.error("sideband error", msg);
          }
        });

        ws.on("close", (code, reason) =>
          console.log("sideband closed", callId, code, reason.toString())
        );
        ws.on("error", (e) => console.error("sideband error", e));
      }

      const t = await upstream.text();
      res.statusCode = upstream.status;
      res.setHeader("Content-Type", upstream.headers.get("content-type") ?? "text/plain");
      res.end(t);
      return;
    }

    if (req.method === "GET" && pathname === "/health") {
      res.writeHead(200, { "Content-Type": "text/plain" });
      res.end("ok");
      return;
    }

    res.statusCode = 404;
    res.end("not found");
  } catch (err) {
    console.error(err);
    res.statusCode = 500;
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify({ error: "internal_error" }));
  }
});

server.listen(PORT, () => console.log(`server on :${PORT}`));
```

## 7) Testing checklist

* Build Dev Client and install on device. ([Expo Documentation][9])
* Start server with `OPENAI_API_KEY` set.
* In the app: **Start** → speak; observe user transcript events and AI text deltas. ([Microsoft Learn][5])
* Tap **Take photo...** → AI should speak a description and stream text. ([GitHub][7])
* Trigger tools by saying “add 2 and 5 slowly” etc., model will call `delayed_add`; server returns tool output via Sideband and prompts continuation. ([Microsoft Learn][8])

## 8) Notes and pitfalls

* If you do not see `response.text.delta`, ensure session `modalities` includes `"text"`. Some sessions may stream only audio without text unless configured. ([OpenAI Developer Community][11])
* Ensure `input_audio_transcription` is configured to receive `conversation.item.input_audio_transcription.completed`. ([Microsoft Learn][6])
* If Sideband WS cannot connect, verify `call_id` from the `Location` header of `/v1/realtime/calls`. ([OpenAI Developer Community][12])
* Expo Camera returns JPEG Base64 when `base64: true`. Prefix with `data:image/jpeg;base64,` when sending as `input_image`. ([Expo Documentation][4])

## 9) References

* **Realtime WebRTC calls endpoint** and flow. ([OpenAI Platform][1])
* **Realtime WebSocket + server events** (GA names). ([OpenAI Platform][13])
* **OpenAI GA blog** (images, SIP, Sideband). ([OpenAI][14])
* **Agents Realtime SDK (TS) reference**. ([GitHub][15])
* **Expo Camera** docs for Base64 and permissions. ([Expo Documentation][4])
* **react-native-webrtc** + Expo Dev Client requirement. ([GitHub][2])
* **Expo Dev Client** basics. ([Expo Documentation][9])

---

[1]: https://platform.openai.com/docs/guides/realtime-webrtc?utm_source=chatgpt.com "Realtime API with WebRTC"
[2]: https://github.com/react-native-webrtc/react-native-webrtc "GitHub - react-native-webrtc/react-native-webrtc: The WebRTC module for React Native"
[3]: https://github.com/react-native-webrtc/react-native-webrtc?utm_source=chatgpt.com "The WebRTC module for React Native"
[4]: https://docs.expo.dev/versions/latest/sdk/camera/ "Camera - Expo Documentation"
[5]: https://learn.microsoft.com/en-us/azure/ai-foundry/openai/realtime-audio-reference?utm_source=chatgpt.com "Audio events reference - Azure OpenAI"
[6]: https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/realtime-audio?utm_source=chatgpt.com "How to use the GPT Realtime API for speech and audio"
[7]: https://github.com/openai/openai-python?utm_source=chatgpt.com "The official Python library for the OpenAI API"
[8]: https://learn.microsoft.com/en-us/azure/ai-foundry/openai/realtime-audio-reference "Audio events reference - Azure OpenAI | Microsoft Learn"
[9]: https://docs.expo.dev/versions/latest/sdk/dev-client/ "DevClient - Expo Documentation"
[10]: https://getstream.io/video/docs/react-native/setup/installation/expo/?utm_source=chatgpt.com "Expo - React Native Video and Audio Docs"
[11]: https://community.openai.com/t/missing-response-text-done-and-response-text-delta-events-receiving-only-audio-responses/1245579?utm_source=chatgpt.com "Missing response.text.done and response.text.delta events, ..."
[12]: https://community.openai.com/t/not-able-to-connect-to-realtime-server-side-websocket-using-call-id/1356826?utm_source=chatgpt.com "Not able to connect to realtime server side websocket ..."
[13]: https://platform.openai.com/docs/api-reference/realtime-server-events?utm_source=chatgpt.com "Realtime Server Events API Reference"
[14]: https://openai.com/index/introducing-gpt-realtime/?utm_source=chatgpt.com "Introducing gpt-realtime and Realtime API updates for ..."
[15]: https://github.com/openai/openai-agents-js/tree/main/packages/agents-realtime "openai-agents-js/packages/agents-realtime at main · openai/openai-agents-js · GitHub"
