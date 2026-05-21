from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from session_manager import (
    DEFAULT_OVERSHOOT_API_URL,
    DEFAULT_OVERSHOOT_MODEL,
    OrigamiSessionManager,
)


class WebRTCOfferRequest(BaseModel):
    offer_sdp: str


manager: OrigamiSessionManager | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global manager

    overshoot_api_key = os.getenv("OVERSHOOT_API_KEY", "").strip()
    if not overshoot_api_key:
        raise RuntimeError("Set OVERSHOOT_API_KEY in backend/.env")

    overshoot_api_url = os.getenv(
        "OVERSHOOT_API_URL",
        DEFAULT_OVERSHOOT_API_URL,
    ).strip()
    overshoot_model = os.getenv("OVERSHOOT_MODEL", DEFAULT_OVERSHOOT_MODEL).strip()
    steps_path = Path(__file__).with_name("assets") / "origami_steps.json"

    manager = OrigamiSessionManager(
        overshoot_api_url=overshoot_api_url,
        overshoot_api_key=overshoot_api_key,
        overshoot_model=overshoot_model,
        steps_path=steps_path,
    )
    try:
        yield
    finally:
        current = manager
        manager = None
        if current is not None:
            await current.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/session/media")
async def create_media_session(payload: WebRTCOfferRequest) -> dict[str, str]:
    current = require_manager()
    return await current.create_media_session(payload.offer_sdp)


@app.get("/demo", response_class=HTMLResponse)
async def demo() -> str:
    return DEMO_HTML


@app.post("/demo/session")
async def create_demo_session(payload: WebRTCOfferRequest) -> dict[str, str]:
    current = require_manager()
    return await current.create_demo_session(payload.offer_sdp)


def require_manager() -> OrigamiSessionManager:
    if manager is None:
        raise HTTPException(
            status_code=503, detail="Session manager is not initialized"
        )
    return manager


DEMO_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Origami Guide Demo</title>
  <style>
    :root {
      color-scheme: dark;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #111;
      color: #f5f5f5;
    }
    body {
      margin: 0;
      min-height: 100vh;
      background: #111;
    }
    main {
      box-sizing: border-box;
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr auto;
      gap: 14px;
      padding: 18px;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    h1 {
      margin: 0;
      font-size: 20px;
      font-weight: 650;
      letter-spacing: 0;
    }
    #status {
      color: #cfcfcf;
      font-size: 13px;
      white-space: nowrap;
    }
    video {
      width: 100%;
      height: 100%;
      min-height: 0;
      background: #000;
      object-fit: contain;
      border: 1px solid #333;
    }
    footer {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }
    button {
      appearance: none;
      border: 1px solid #555;
      border-radius: 6px;
      background: #222;
      color: #fff;
      font: inherit;
      font-size: 14px;
      padding: 9px 13px;
      cursor: pointer;
    }
    button:disabled {
      color: #777;
      cursor: default;
    }
    @media (max-width: 720px) {
      main {
        padding: 10px;
      }
      header {
        align-items: flex-start;
        flex-direction: column;
        gap: 6px;
      }
      #status {
        white-space: normal;
      }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Origami Guide Demo</h1>
      <div id="status">Connecting...</div>
    </header>
    <video id="video" autoplay playsinline muted></video>
    <footer>
      <button data-command="session.start">Start</button>
      <button data-command="manual.prev">Previous</button>
      <button data-command="manual.next">Next</button>
      <button data-command="auto.toggle">Toggle Auto</button>
      <button data-command="session.reset">Reset</button>
    </footer>
  </main>
  <script>
    const statusEl = document.getElementById("status");
    const videoEl = document.getElementById("video");
    const buttons = Array.from(document.querySelectorAll("button[data-command]"));
    let pc;
    let dc;

    function setStatus(text) {
      statusEl.textContent = text;
    }

    function setButtons(enabled) {
      for (const button of buttons) button.disabled = !enabled;
    }

    function send(type) {
      if (!dc || dc.readyState !== "open") return;
      dc.send(JSON.stringify({ type }));
    }

    function waitForIceGatheringComplete(peerConnection) {
      if (peerConnection.iceGatheringState === "complete") return Promise.resolve();
      return new Promise((resolve) => {
        const timeout = setTimeout(resolve, 15000);
        peerConnection.addEventListener("icegatheringstatechange", () => {
          if (peerConnection.iceGatheringState === "complete") {
            clearTimeout(timeout);
            resolve();
          }
        });
      });
    }

    async function connect() {
      setButtons(false);
      pc = new RTCPeerConnection();
      pc.addTransceiver("video", { direction: "recvonly" });
      dc = pc.createDataChannel("demo-events");

      pc.addEventListener("track", (event) => {
        videoEl.srcObject = event.streams[0];
      });
      pc.addEventListener("connectionstatechange", () => {
        setStatus(`Connection: ${pc.connectionState}`);
      });
      dc.addEventListener("open", () => {
        setButtons(true);
        setStatus("Connected");
      });
      dc.addEventListener("close", () => {
        setButtons(false);
        setStatus("Data channel closed");
      });
      dc.addEventListener("message", (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === "hud.state") {
            setStatus(
              `Step ${payload.step_number}/${payload.step_count} | ` +
              `${payload.phase} | auto ${payload.auto_check_enabled ? "on" : "off"}`
            );
          } else if (payload.message) {
            setStatus(payload.message);
          }
        } catch (_) {
          // Ignore unknown demo messages.
        }
      });

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await waitForIceGatheringComplete(pc);
      const response = await fetch("/demo/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ offer_sdp: pc.localDescription.sdp }),
      });
      if (!response.ok) {
        throw new Error(`Demo session failed: HTTP ${response.status}`);
      }
      const answer = await response.json();
      await pc.setRemoteDescription({ type: "answer", sdp: answer.answer_sdp });
    }

    for (const button of buttons) {
      button.addEventListener("click", () => send(button.dataset.command));
    }

    connect().catch((error) => {
      setButtons(false);
      setStatus(error.message || "Connection failed");
    });
  </script>
</body>
</html>
"""
