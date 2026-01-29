import asyncio
import json
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
import websockets
from aiortc import (
    MediaStreamTrack,
    RTCPeerConnection,
    RTCRtpReceiver,
    RTCSessionDescription,
)
from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from websockets.asyncio.client import ClientConnection

from logging_utils import get_logger
from vision import LatestFrameStore, VisionProcessor, summarize_labels

logger = get_logger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Set OPENAI_API_KEY in env")

SESSION_INSTRUCTIONS = """
# Role
- You are a helpful and cheerful expert assembly assistant.
- Your goal is to guide the user through completing an assembly project by giving step-by-step, interactive instructions.

# Personality
- Your responses should be clear, concise, and actionable.
- Limit each response to at most 3 sentences.
- Both you and the user communicate only in English.
- Always rely on the latest real-time video frame provided, which shows the current situation, and EXAMINE IT CAREFULLY before responding.
- Vary your responses for variety so they do not sound robotic.

# Rules
## Conversation Flow
### 1) Identify the item & Load instructions
- When the user first asks for help assembling a specific item, call the tools as described in the "Tools" section below.
- Use the user's description and the latest video frame to identify which item from "list_items" is being assembled and select that item for "load_item_instructions".

### 2) Guide the user
- Guide the user step by step, providing the next step, answering questions, and correcting errors based on the instructions loaded.
- Each step from the "Assembly Instructions" in the loaded instructions can be used in your response as is. Do not include multiple steps in one response; give only one step at a time.
- Always describe the appearance of each part (e.g., size, shape) to avoid confusion.
- PAY EXTRA ATTENTION to the user selecting the correct parts. After the user corrects a mistake, guide them back to the defined steps.
- Continue until all steps are completed or the user confirms completion.

### 3) End
- When the assembly is complete, congratulate the user.

## Audio
- Only respond to clear voice audio.
- Do not include any sound effects or onomatopoeic expressions in your responses.

## Clarification
- If the user's voice audio is heard but unclear (e.g., ambiguous input/unintelligible) or if you did not understand the user, ask for clarification, e.g., "I didn't hear that clearly—could you say it again?"
- If the video frame is unclear or unframed, ask for clarification, e.g., "I didn't get a clear look—could you show it again?"

# Tools
- When the user first asks for help with assembling a specific item, you MUST call the "list_items()" and "load_item_instructions(item_name)" tools sequentially before giving any assembly steps for that item.
- Before these tool calls, in the same turn, say one short line like "I'm looking up the instructions now." Then call these tools immediately.
- After you have successfully loaded instructions for that item, do not call these tools again unless the user wants to switch to a different item or the previous item choice was incorrect.
- When calling tools, do not ask for any user confirmation. Be proactive.
""".strip()

ITEM_DATA_DIR = Path(__file__).with_name("items")

session_config = {
    "type": "realtime",
    "model": "gpt-realtime",
    "audio": {
        "input": {
            "noise_reduction": {"type": "near_field"},
            "transcription": {"language": "en", "model": "whisper-1"},
            "turn_detection": {
                "type": "semantic_vad",
                "create_response": False,
                "interrupt_response": False,
            },
        },
        "output": {"voice": "marin"},
    },
    "instructions": SESSION_INSTRUCTIONS,
    "tools": [
        {
            "type": "function",
            "name": "list_items",
            "description": (
                "List all available item names for which assembly instructions exist. "
                "Returns an array of strings; each string is a valid `item_name` that "
                "can be passed to `load_item_instructions`."
            ),
        },
        {
            "type": "function",
            "name": "load_item_instructions",
            "description": (
                "Load the assembly instructions for the given item name. Returns the "
                "full text content for that item."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": (
                            "An item name chosen from the array returned by "
                            "`list_items`; must match one of those strings."
                        ),
                    }
                },
                "required": ["item_name"],
            },
        },
    ],
}

vision_store = LatestFrameStore()
vision_processor = VisionProcessor(vision_store)
vision_peers: set[RTCPeerConnection] = set()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    warmup_task = asyncio.create_task(vision_processor.warmup())
    try:
        yield
    finally:
        if not warmup_task.done():
            warmup_task.cancel()
            with suppress(asyncio.CancelledError):
                await warmup_task
        coros = [pc.close() for pc in list(vision_peers)]
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)
        vision_peers.clear()


app = FastAPI(lifespan=lifespan)


@app.post("/session")
async def session(request: Request) -> Response:
    sdp_bytes = await request.body()
    sdp = sdp_bytes.decode()

    form = {
        "sdp": (None, sdp),
        "session": (None, json.dumps(session_config)),
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        upstream = await client.post(
            "https://api.openai.com/v1/realtime/calls",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            files=form,
        )

    call_id = _extract_call_id(upstream.headers.get("location"))
    if upstream.is_success and call_id:
        task = asyncio.create_task(start_sideband(call_id))
        task.add_done_callback(_log_task_exception)

    return Response(
        content=upstream.text,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "text/plain"),
    )


@app.post("/vision/session")
async def vision_session(request: Request) -> Response:
    sdp_bytes = await request.body()
    sdp = sdp_bytes.decode()

    offer = RTCSessionDescription(sdp=sdp, type="offer")
    pc = RTCPeerConnection()
    transceiver = pc.addTransceiver("video", direction="recvonly")
    _prefer_video_codec(transceiver, "video/H264")
    vision_peers.add(pc)

    @pc.on("connectionstatechange")
    async def on_connection_state_change() -> None:
        logger.info("vision: connection state %s", pc.connectionState)
        if pc.connectionState in {"failed", "closed", "disconnected"}:
            await pc.close()
            vision_peers.discard(pc)

    @pc.on("track")
    def on_track(track: MediaStreamTrack) -> None:
        if track.kind == "video":
            task = asyncio.create_task(vision_processor.consume(track))
            task.add_done_callback(_log_task_exception)
        else:
            logger.info("vision: ignoring track kind=%s", track.kind)

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return PlainTextResponse(pc.localDescription.sdp)


def _extract_call_id(location: str | None) -> str | None:
    if not location:
        return None
    return location.rstrip("/").split("/")[-1] or None


def _prefer_video_codec(transceiver: Any, mime_type: str) -> None:
    try:
        capabilities = RTCRtpReceiver.getCapabilities("video")
    except Exception:
        logger.exception("vision: failed to read video capabilities")
        return
    if capabilities is None:
        logger.warning("vision: no video capabilities; using default codec order")
        return

    mime_type = mime_type.lower()
    preferences = [
        codec for codec in capabilities.codecs if codec.mimeType.lower() == mime_type
    ]
    if not preferences:
        logger.warning("vision: %s not available; using default codec order", mime_type)
        return

    transceiver.setCodecPreferences(preferences)
    logger.info("vision: preferring %s for inbound video", mime_type)


def _log_task_exception(task: asyncio.Task[Any]) -> None:
    try:
        task.result()
    except Exception:
        logger.exception("sideband task failed")


def _is_user_audio_item(item: dict[str, Any]) -> bool:
    if item.get("type") != "message" or item.get("role") != "user":
        return False
    content = item.get("content") or []
    return any(part.get("type") == "input_audio" for part in content)


async def _send_latest_frame(ws: ClientConnection, item_id: str) -> None:
    latest = await vision_store.wait_for(timeout=0.5)
    if not latest:
        logger.warning("vision: no frame available for item %s", item_id)
        await ws.send(json.dumps({"type": "response.create"}))
        return

    logger.info(
        "vision: sending frame for item %s (%s)",
        item_id,
        summarize_labels(latest.labels),
    )
    payload = {
        "type": "conversation.item.create",
        "previous_item_id": item_id,
        "item": {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_image",
                    "image_url": latest.data_uri,
                    "detail": "high",
                }
            ],
        },
    }
    await ws.send(json.dumps(payload))
    await ws.send(json.dumps({"type": "response.create"}))


async def start_sideband(call_id: str) -> None:
    url = f"wss://api.openai.com/v1/realtime?call_id={call_id}"

    try:
        async with websockets.connect(
            url,
            additional_headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        ) as ws:
            logger.info("sideband: connected %s", call_id)

            sent_images: set[str] = set()

            async for raw in ws:
                raw_text = raw.decode() if isinstance(raw, bytes) else raw
                try:
                    msg = json.loads(raw_text)
                except json.JSONDecodeError:
                    logger.info("sideband: message parse error %s", raw_text)
                    continue

                msg_type = msg.get("type")
                if msg_type == "conversation.item.created":
                    item = msg.get("item") or {}
                    item_id = item.get("id")
                    if (
                        isinstance(item_id, str)
                        and item_id
                        and item_id not in sent_images
                        and _is_user_audio_item(item)
                    ):
                        sent_images.add(item_id)
                        await _send_latest_frame(ws, item_id)

                response = msg.get("response") or {}
                output_items = response.get("output") or []
                fn_call = next(
                    (
                        item
                        for item in output_items
                        if item.get("type") == "function_call"
                        and item.get("status") == "completed"
                    ),
                    None,
                )

                if (
                    msg.get("type") == "response.done"
                    and response.get("status") == "completed"
                    and fn_call
                ):
                    logger.info("tool call: %s", json.dumps(fn_call))
                    args = _parse_arguments(fn_call.get("arguments"))

                    try:
                        output = await run_tool(str(fn_call.get("name") or ""), args)
                        payload = {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "function_call_output",
                                "call_id": fn_call.get("call_id"),
                                "output": output,
                            },
                        }
                    except Exception as error:
                        payload = {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "function_call_output",
                                "call_id": fn_call.get("call_id"),
                                "output": json.dumps({"error": str(error)}),
                            },
                        }

                    await ws.send(json.dumps(payload))
                    await ws.send(json.dumps({"type": "response.create"}))
    except websockets.ConnectionClosed as exc:
        logger.info("sideband: closed %s %s %s", call_id, exc.code, exc.reason)
    except Exception:
        logger.exception("sideband error: error")


def _parse_arguments(raw_args: Any) -> dict[str, Any]:
    if isinstance(raw_args, dict):
        return raw_args
    if raw_args is None:
        return {}
    if isinstance(raw_args, str):
        try:
            return json.loads(raw_args)
        except json.JSONDecodeError:
            return {}
    return {}


async def run_tool(name: str, args: dict[str, Any]) -> str:
    if name == "list_items":
        items = await list_item_names()
        return json.dumps(items)
    if name == "load_item_instructions":
        return await load_item_instructions(args)
    return f'Error: unknown tool "{name}"'


async def load_item_instructions(args: dict[str, Any]) -> str:
    raw_name = args.get("item_name", "")
    requested_name = (
        raw_name.strip() if isinstance(raw_name, str) else str(raw_name).strip()
    )

    if not requested_name:
        raise ValueError("item_name is required")

    available = await list_item_names()
    match = next(
        (name for name in available if name.lower() == requested_name.lower()),
        None,
    )

    if not match:
        if not available:
            raise ValueError(f"Unknown item: {requested_name}. No item files found.")
        raise ValueError(
            f"Unknown item: {requested_name}. Available items: {', '.join(available)}"
        )

    return (ITEM_DATA_DIR / f"{match}.txt").read_text(encoding="utf-8")


async def list_item_names() -> list[str]:
    try:
        entries = [
            entry
            for entry in ITEM_DATA_DIR.iterdir()
            if entry.is_file() and entry.suffix.lower() == ".txt"
        ]
    except FileNotFoundError:
        return []

    names = [entry.stem for entry in entries]
    return sorted(names, key=str.lower)
