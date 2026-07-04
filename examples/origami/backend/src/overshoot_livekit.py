from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from livekit import rtc
from PIL import Image

from .constants import OVERSHOOT_FPS, OVERSHOOT_PUBLISH_MAX_BITRATE_BPS

logger = logging.getLogger("uvicorn.error")

DisconnectedCallback = Callable[[rtc.Room, Any], None]


@dataclass(frozen=True)
class OvershootLiveKitPublisher:
    room: rtc.Room
    source: rtc.VideoSource
    publication: Any

    async def close(self) -> None:
        await self.source.aclose()
        await self.room.disconnect()


async def connect_overshoot_publisher(
    *,
    session_id: str,
    generation: int,
    publish_url: str,
    publish_token: str,
    frame_size: tuple[int, int],
    on_disconnected: DisconnectedCallback,
) -> OvershootLiveKitPublisher:
    room = rtc.Room()
    source: rtc.VideoSource | None = None

    @room.on("connection_state_changed")
    def on_connection_state_changed(state: Any) -> None:
        logger.info(
            "session=%s overshoot livekit state=%s generation=%s",
            session_id,
            state,
            generation,
        )

    @room.on("reconnecting")
    def on_reconnecting() -> None:
        logger.info(
            "session=%s overshoot livekit reconnecting generation=%s",
            session_id,
            generation,
        )

    @room.on("reconnected")
    def on_reconnected() -> None:
        logger.info(
            "session=%s overshoot livekit reconnected generation=%s",
            session_id,
            generation,
        )

    @room.on("disconnected")
    def on_disconnected_event(*args: Any) -> None:
        reason = args[0] if args else None
        logger.info(
            "session=%s overshoot livekit disconnected reason=%s generation=%s",
            session_id,
            reason,
            generation,
        )
        on_disconnected(room, reason)

    try:
        await room.connect(
            publish_url,
            publish_token,
            options=rtc.RoomOptions(auto_subscribe=False, dynacast=False),
        )
        source = rtc.VideoSource(frame_size[0], frame_size[1])
        track = rtc.LocalVideoTrack.create_video_track(
            "origami-reference-composite",
            source,
        )
        publication = await room.local_participant.publish_track(
            track,
            _track_publish_options(),
        )
        return OvershootLiveKitPublisher(room, source, publication)
    except BaseException:
        if source is not None:
            await source.aclose()
        await room.disconnect()
        raise


def refresh_livekit_publish_token(room: rtc.Room, publish_token: str) -> None:
    room_with_private_state = cast(Any, room)
    if getattr(room_with_private_state, "_token", None) == publish_token:
        return
    setattr(room_with_private_state, "_token", publish_token)
    room_with_private_state.emit("token_refreshed")


def capture_image(source: rtc.VideoSource, image: Image.Image) -> None:
    source.capture_frame(
        _video_frame_from_image(image),
        timestamp_us=int(time.monotonic() * 1_000_000),
    )


def _track_publish_options() -> rtc.TrackPublishOptions:
    return rtc.TrackPublishOptions(
        source=rtc.TrackSource.SOURCE_CAMERA,
        simulcast=False,
        video_codec=rtc.VideoCodec.H264,
        video_encoding=rtc.VideoEncoding(
            max_framerate=OVERSHOOT_FPS,
            max_bitrate=OVERSHOOT_PUBLISH_MAX_BITRATE_BPS,
        ),
        degradation_preference=cast(
            Any,
            rtc.DegradationPreference.MAINTAIN_RESOLUTION,
        ),
    )


def _video_frame_from_image(image: Image.Image) -> rtc.VideoFrame:
    rgba = image.convert("RGBA")
    return rtc.VideoFrame(
        rgba.width,
        rgba.height,
        rtc.VideoBufferType.RGBA,
        rgba.tobytes(),
    )
