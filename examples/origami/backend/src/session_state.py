from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from aiortc import RTCPeerConnection
from aiortc.rtcdatachannel import RTCDataChannel
from av import VideoFrame

from .constants import PHASE_WAITING


@dataclass
class SessionEvent:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


class LatestFrameBuffer:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._latest: tuple[int, VideoFrame] | None = None
        self._counter = 0
        self._closed = False

    async def update(self, frame: VideoFrame) -> None:
        async with self._condition:
            if self._closed:
                return
            self._counter += 1
            self._latest = (self._counter, frame)
            self._condition.notify_all()

    async def latest(self) -> tuple[int, VideoFrame] | None:
        async with self._condition:
            return self._latest

    async def wait_for_new(
        self,
        last_id: int | None,
        *,
        timeout_seconds: float,
    ) -> tuple[int, VideoFrame] | None:
        deadline = time.monotonic() + timeout_seconds
        async with self._condition:
            while not self._closed:
                if self._latest is not None and (
                    last_id is None or self._latest[0] != last_id
                ):
                    return self._latest
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return self._latest
                try:
                    await asyncio.wait_for(self._condition.wait(), timeout=remaining)
                except TimeoutError:
                    return self._latest
            return None

    async def close(self) -> None:
        async with self._condition:
            self._closed = True
            self._condition.notify_all()


@dataclass
class OrigamiSession:
    session_id: str
    queue: asyncio.Queue[SessionEvent] = field(default_factory=asyncio.Queue)
    loop_task: asyncio.Task[None] | None = None
    media_pc: RTCPeerConnection | None = None
    data_channel: RTCDataChannel | None = None
    phase: str = PHASE_WAITING
    step_index: int = 0
    auto_check_enabled: bool = True
    true_streak: int = 0
    destroyed: bool = False
    track_counter: int = 0
    camera_frames: LatestFrameBuffer = field(default_factory=LatestFrameBuffer)
    track_tasks: list[asyncio.Task[None]] = field(default_factory=list)
    done_task: asyncio.Task[None] | None = None
    overshoot_generation: int = 0
    overshoot_pc: RTCPeerConnection | None = None
    overshoot_stream_id: str | None = None
    overshoot_lease_ttl_seconds: int | None = None
    overshoot_ws_task: asyncio.Task[None] | None = None
    overshoot_keepalive_task: asyncio.Task[None] | None = None
    overshoot_stats_task: asyncio.Task[None] | None = None
    active_prompt_text: str | None = None
    guiding_step_started_at: float = 0.0
    overshoot_ignore_results_until: float = 0.0
    last_debug_composite_save_at: float = 0.0


@dataclass
class DemoViewer:
    viewer_id: str
    pc: RTCPeerConnection
    data_channel: RTCDataChannel | None = None
