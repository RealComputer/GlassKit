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


class OvershootEnabledRequest(BaseModel):
    enabled: bool


manager: OrigamiSessionManager | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global manager

    overshoot_api_key = os.getenv("OVERSHOOT_API_KEY", "").strip()
    overshoot_enabled = _env_bool("ORIGAMI_OVERSHOOT_ENABLED", default=True)
    if overshoot_enabled and not overshoot_api_key:
        raise RuntimeError("Set OVERSHOOT_API_KEY in backend/.env")

    overshoot_api_url = os.getenv(
        "OVERSHOOT_API_URL",
        DEFAULT_OVERSHOOT_API_URL,
    ).strip()
    overshoot_model = os.getenv("OVERSHOOT_MODEL", DEFAULT_OVERSHOOT_MODEL).strip()
    steps_path = Path(__file__).with_name("assets") / "origami_steps.json"
    debug_composite_dir_raw = os.getenv(
        "ORIGAMI_DEBUG_OVERSHOOT_COMPOSITE_DIR", ""
    ).strip()
    debug_composite_dir = (
        Path(debug_composite_dir_raw).expanduser() if debug_composite_dir_raw else None
    )

    manager = OrigamiSessionManager(
        overshoot_api_url=overshoot_api_url,
        overshoot_api_key=overshoot_api_key,
        overshoot_model=overshoot_model,
        steps_path=steps_path,
        overshoot_enabled=overshoot_enabled,
        save_overshoot_composites=_env_bool(
            "ORIGAMI_DEBUG_SAVE_OVERSHOOT_COMPOSITES",
            default=False,
        ),
        debug_composite_dir=debug_composite_dir,
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


@app.get("/debug/overshoot")
async def get_overshoot_enabled() -> dict[str, bool]:
    current = require_manager()
    return current.overshoot_status()


@app.post("/debug/overshoot")
async def set_overshoot_enabled(payload: OvershootEnabledRequest) -> dict[str, bool]:
    current = require_manager()
    return await current.set_overshoot_enabled(payload.enabled)


def require_manager() -> OrigamiSessionManager:
    if manager is None:
        raise HTTPException(
            status_code=503, detail="Session manager is not initialized"
        )
    return manager


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


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
      background: #000;
      color: #f5f5f5;
    }
    html {
      height: 100%;
      background: #000;
    }
    body {
      margin: 0;
      height: 100%;
      overflow: hidden;
      background: #000;
    }
    main {
      box-sizing: border-box;
      position: relative;
      width: 100vw;
      height: 100vh;
      height: 100dvh;
      display: flex;
      align-items: stretch;
      justify-content: center;
      overflow: hidden;
      background: #000;
    }
    #status {
      color: #d8ffe4;
      font-size: 12px;
      line-height: 1.35;
      min-width: 100%;
      text-align: center;
      text-shadow: 0 0 8px rgba(0, 255, 96, 0.7);
    }
    video {
      display: block;
      width: auto;
      height: 100vh;
      height: 100dvh;
      max-width: none;
      background: #000;
      object-fit: contain;
    }
    footer {
      position: absolute;
      z-index: 3;
      left: 50%;
      bottom: 14px;
      transform: translateX(-50%);
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 8px;
      max-width: calc(100vw - 24px);
      padding: 8px;
      opacity: 0;
      pointer-events: none;
      transition: opacity 140ms ease;
      border: 1px solid rgba(0, 255, 96, 0.42);
      border-radius: 8px;
      background: rgba(0, 0, 0, 0.72);
      backdrop-filter: blur(8px);
    }
    video:hover + footer,
    footer:hover,
    main:focus-within footer {
      opacity: 1;
      pointer-events: auto;
    }
    button {
      appearance: none;
      border: 1px solid #16a34a;
      border-radius: 6px;
      background: #031208;
      color: #ecfff2;
      font: inherit;
      font-size: 13px;
      padding: 8px 11px;
      cursor: pointer;
      box-shadow: 0 0 14px rgba(0, 255, 96, 0.16);
    }
    button:hover {
      background: #083817;
    }
    button:disabled {
      color: #66756a;
      cursor: default;
    }
    @media (max-width: 720px) {
      #status {
        white-space: normal;
      }
      footer {
        bottom: 8px;
      }
      button {
        font-size: 12px;
        padding: 7px 9px;
      }
    }
  </style>
</head>
<body>
  <main>
    <video id="video" autoplay playsinline muted></video>
    <footer>
      <div id="status">Connecting...</div>
      <button data-command="session.start">Start</button>
      <button data-command="manual.prev">Previous</button>
      <button data-command="manual.next">Next</button>
      <button data-command="auto.toggle">Toggle Auto</button>
      <button data-command="session.reset">Reset</button>
      <button id="visionButton" type="button">Vision: --</button>
    </footer>
  </main>
  <script>
    const statusEl = document.getElementById("status");
    const videoEl = document.getElementById("video");
    const buttons = Array.from(document.querySelectorAll("button[data-command]"));
    const visionButton = document.getElementById("visionButton");
    let pc;
    let dc;
    let visionEnabled = true;

    function setStatus(text) {
      statusEl.textContent = text;
    }

    function setButtons(enabled) {
      for (const button of buttons) button.disabled = !enabled;
      visionButton.disabled = !enabled;
    }

    function send(type) {
      if (!dc || dc.readyState !== "open") return;
      dc.send(JSON.stringify({ type }));
    }

    function updateVisionButton() {
      visionButton.textContent = `Vision: ${visionEnabled ? "On" : "Off"}`;
    }

    async function setVisionEnabled(enabled) {
      const response = await fetch("/debug/overshoot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      if (!response.ok) throw new Error(`Vision toggle failed: HTTP ${response.status}`);
      const payload = await response.json();
      visionEnabled = Boolean(payload.enabled);
      updateVisionButton();
    }

    async function loadVisionState() {
      const response = await fetch("/debug/overshoot");
      if (!response.ok) return;
      const payload = await response.json();
      visionEnabled = Boolean(payload.enabled);
      updateVisionButton();
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
            if (typeof payload.overshoot_enabled === "boolean") {
              visionEnabled = payload.overshoot_enabled;
              updateVisionButton();
            }
            setStatus(
              `Step ${payload.step_number}/${payload.step_count} | ` +
              `${payload.phase} | auto ${payload.auto_check_enabled ? "on" : "off"} | ` +
              `vision ${visionEnabled ? "on" : "off"}`
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
    visionButton.addEventListener("click", () => {
      setVisionEnabled(!visionEnabled).catch((error) => {
        setStatus(error.message || "Vision toggle failed");
      });
    });

    updateVisionButton();
    loadVisionState().catch(() => {});
    connect().catch((error) => {
      setButtons(false);
      setStatus(error.message || "Connection failed");
    });
  </script>
</body>
</html>
"""
