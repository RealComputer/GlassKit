import asyncio
import json
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, AsyncIterator

from aiortc import (
    MediaStreamTrack,
    RTCPeerConnection,
    RTCRtpReceiver,
    RTCSessionDescription,
)
from aiortc.rtcdatachannel import RTCDataChannel
from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse

from logging_utils import get_logger
from speedrun import SpeedrunController, load_speedrun_config
from vision import DetectionResult, VisionProcessor

logger = get_logger(__name__)

SPEEDRUN_CONFIG_PATH = Path(__file__).with_name("speedrun_config.json")

speedrun_controller = SpeedrunController(load_speedrun_config(SPEEDRUN_CONFIG_PATH))
vision_processor: VisionProcessor | None = None
vision_peers: set[RTCPeerConnection] = set()
data_channels: set[RTCDataChannel] = set()


async def _handle_detection(result: DetectionResult) -> None:
    event = await speedrun_controller.on_detection(result.detected_classes)
    if event:
        await _broadcast(event)


def _ensure_vision_processor() -> VisionProcessor:
    global vision_processor
    if vision_processor is None:
        vision_processor = VisionProcessor(on_result=_handle_detection)
    return vision_processor


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    processor = _ensure_vision_processor()
    warmup_task = asyncio.create_task(processor.warmup())
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
        data_channels.clear()


app = FastAPI(lifespan=lifespan)


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

    @pc.on("datachannel")
    def on_datachannel(channel: RTCDataChannel) -> None:
        logger.info("vision: data channel opened %s", channel.label)
        data_channels.add(channel)

        @channel.on("message")
        def on_message(message: Any) -> None:
            if isinstance(message, str):
                asyncio.create_task(_handle_client_message(message))
            else:
                logger.info("vision: ignoring non-text data channel message")

        @channel.on("close")
        def on_close() -> None:
            data_channels.discard(channel)

        if channel.readyState == "open":
            asyncio.create_task(_send_initial(channel))
        else:

            @channel.on("open")
            def on_open() -> None:
                asyncio.create_task(_send_initial(channel))

    @pc.on("track")
    def on_track(track: MediaStreamTrack) -> None:
        if track.kind == "video":
            processor = _ensure_vision_processor()
            task = asyncio.create_task(processor.consume(track))
            task.add_done_callback(_log_task_exception)
        else:
            logger.info("vision: ignoring track kind=%s", track.kind)

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return PlainTextResponse(pc.localDescription.sdp)


async def _send_initial(channel: RTCDataChannel) -> None:
    await _send_channel_json(channel, speedrun_controller.config.client_payload())
    await _send_channel_json(channel, speedrun_controller.state_payload())


async def _handle_client_message(raw_text: str) -> None:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.info("vision: failed to parse message %s", raw_text)
        return
    if not isinstance(payload, dict):
        return

    events = await speedrun_controller.on_client_message(payload)
    for event in events:
        await _broadcast(event)


async def _broadcast(payload: dict[str, Any]) -> None:
    if not data_channels:
        return
    message = json.dumps(payload)
    for channel in list(data_channels):
        if channel.readyState != "open":
            data_channels.discard(channel)
            continue
        try:
            channel.send(message)
        except Exception:
            logger.exception("vision: failed to send data channel message")
            data_channels.discard(channel)


async def _send_channel_json(channel: RTCDataChannel, payload: dict[str, Any]) -> None:
    if channel.readyState != "open":
        return
    try:
        channel.send(json.dumps(payload))
    except Exception:
        logger.exception("vision: failed to send initial state")


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
        logger.exception("vision task failed")
