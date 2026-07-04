from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from aiortc import RTCPeerConnection
from aiortc.rtcdatachannel import RTCDataChannel
from av import VideoFrame

from .constants import PHASE_WAITING

if TYPE_CHECKING:
    from livekit import rtc

    from .recording import FoldCheckInputRecorder


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


@dataclass(frozen=True)
class FoldCheckRuntimeSnapshot:
    stream_id: str | None
    room: rtc.Room | None
    video_source: rtc.VideoSource | None
    input_recorder: FoldCheckInputRecorder | None
    publish_task: asyncio.Task[None] | None
    prompt_task: asyncio.Task[None] | None
    keepalive_task: asyncio.Task[None] | None
    reconnect_task: asyncio.Task[None] | None

    def tasks(self) -> tuple[asyncio.Task[None] | None, ...]:
        return (
            self.publish_task,
            self.prompt_task,
            self.keepalive_task,
            self.reconnect_task,
        )


@dataclass
class FoldCheckRuntimeState:
    generation: int = 0
    stream_id: str | None = None
    lease_ttl_seconds: int | None = None
    room: rtc.Room | None = None
    video_source: rtc.VideoSource | None = None
    frame_size: tuple[int, int] | None = None
    publish_url: str | None = None
    publish_token: str | None = None
    publisher_epoch: int = 0
    prompt_resume_publisher_epoch: int = 0
    prompt_resume_after_publisher_epoch: int = 0
    prompt_resume_after_frame_at_ms: int | None = None
    prompt_resume_deadline_at: float = 0.0
    livekit_recovering: bool = False
    publish_task: asyncio.Task[None] | None = None
    prompt_task: asyncio.Task[None] | None = None
    keepalive_task: asyncio.Task[None] | None = None
    reconnect_task: asyncio.Task[None] | None = None
    input_recorder: FoldCheckInputRecorder | None = None
    active_prompt: str | None = None
    ignore_results_until: float = 0.0
    last_debug_composite_save_at: float = 0.0

    def is_running(self) -> bool:
        return (
            self.stream_id is not None
            and self.room is not None
            and self.video_source is not None
        )

    def has_runtime_resources(self) -> bool:
        return any(
            resource is not None
            for resource in (
                self.stream_id,
                self.room,
                self.video_source,
                self.publish_task,
                self.prompt_task,
                self.keepalive_task,
                self.reconnect_task,
                self.input_recorder,
            )
        )

    def begin_generation(self, prompt: str) -> int:
        self.generation += 1
        self.active_prompt = prompt
        return self.generation

    def mark_guiding_step_started(self, now: float, grace_seconds: float) -> None:
        self.ignore_results_until = now + grace_seconds

    def clear_prompt_tracking(self) -> None:
        self.active_prompt = None
        self.ignore_results_until = 0.0

    def update_prompt(self, prompt: str) -> bool:
        if self.active_prompt == prompt:
            return False
        self.active_prompt = prompt
        return True

    def start_recovery(self) -> None:
        self.livekit_recovering = True
        self.prompt_resume_publisher_epoch = self.publisher_epoch + 1

    def prompts_are_recovering(self) -> bool:
        return (
            self.livekit_recovering
            or self.publisher_epoch < self.prompt_resume_publisher_epoch
        )

    def clear_reconnect_ingest_gate(self) -> None:
        self.prompt_resume_after_publisher_epoch = 0
        self.prompt_resume_after_frame_at_ms = None
        self.prompt_resume_deadline_at = 0.0

    def clear_runtime(self) -> FoldCheckRuntimeSnapshot:
        snapshot = FoldCheckRuntimeSnapshot(
            stream_id=self.stream_id,
            room=self.room,
            video_source=self.video_source,
            input_recorder=self.input_recorder,
            publish_task=self.publish_task,
            prompt_task=self.prompt_task,
            keepalive_task=self.keepalive_task,
            reconnect_task=self.reconnect_task,
        )
        self.stream_id = None
        self.lease_ttl_seconds = None
        self.room = None
        self.video_source = None
        self.frame_size = None
        self.publish_url = None
        self.publish_token = None
        self.publisher_epoch = 0
        self.prompt_resume_publisher_epoch = 0
        self.clear_reconnect_ingest_gate()
        self.livekit_recovering = False
        self.publish_task = None
        self.prompt_task = None
        self.keepalive_task = None
        self.reconnect_task = None
        self.input_recorder = None
        return snapshot


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
    fold_check: FoldCheckRuntimeState = field(default_factory=FoldCheckRuntimeState)
    guiding_step_started_at: float = 0.0


@dataclass
class DemoViewer:
    viewer_id: str
    pc: RTCPeerConnection
    data_channel: RTCDataChannel | None = None
