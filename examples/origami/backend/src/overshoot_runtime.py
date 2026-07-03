from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import httpx
from livekit import rtc
from PIL import Image

from .constants import (
    DEBUG_COMPOSITE_INTERVAL_SECONDS,
    OVERSHOOT_CHAT_COMPLETION_TIMEOUT_SECONDS,
    OVERSHOOT_FPS,
    OVERSHOOT_KEEPALIVE_INTERVAL_SECONDS,
    OVERSHOOT_PROMPT_INTERVAL_SECONDS,
    OVERSHOOT_PUBLISH_MAX_BITRATE_BPS,
    OVERSHOOT_STREAM_READY_TIMEOUT_SECONDS,
    OVERSHOOT_STREAM_STATUS_POLL_SECONDS,
    PHASE_GUIDING,
)
from .origami_config import OrigamiStep
from .overshoot_payloads import (
    _compact_json,
    _parse_positive_int,
    _response_text,
)
from .recording import OvershootInputRecorder
from .rendering import _compose_reference_image, _frame_to_image, _save_jpeg
from .session_state import OrigamiSession, SessionEvent

logger = logging.getLogger("uvicorn.error")

_CREATE_STREAM_RETRY_DELAYS = (1.0, 2.0, 4.0)
_CHAT_COMPLETION_RETRY_DELAYS = (0.5, 1.0, 2.0)
_KEEPALIVE_RETRY_DELAYS = (1.0, 1.0, 1.0)


class OvershootRuntimeMixin:
    _auto_check_available: bool
    _debug_composite_dir: Path
    _overshoot_api_key: str
    _overshoot_api_url: str
    _overshoot_http: httpx.AsyncClient
    _overshoot_model: str
    _overshoot_input_recording_dir: Path
    _overshoot_input_recorder_stop_tasks: set[asyncio.Task[None]]
    _record_overshoot_inputs: bool
    _save_overshoot_composites: bool
    _sessions: dict[str, OrigamiSession]
    _sessions_lock: asyncio.Lock
    _steps: list[OrigamiStep]

    def current_step_for(self, session: OrigamiSession) -> OrigamiStep:
        raise NotImplementedError

    def reference_image_for(self, step: OrigamiStep) -> Image.Image:
        raise NotImplementedError

    async def _sync_overshoot_for_current_step(self, session: OrigamiSession) -> None:
        if not self._auto_check_available:
            return
        if session.phase != PHASE_GUIDING or not session.auto_check_enabled:
            return

        if (
            session.overshoot_stream_id is None
            or session.overshoot_room is None
            or session.overshoot_video_source is None
        ):
            if (
                session.overshoot_stream_id is not None
                or session.overshoot_room is not None
                or session.overshoot_video_source is not None
            ):
                await self._stop_overshoot_runtime(session)
            if await session.camera_frames.latest() is None:
                return
            await self._start_overshoot_runtime(session)
            return

        step = self.current_step_for(session)
        await self._switch_overshoot_prompt(session, step.prompt)

    async def _switch_overshoot_prompt(
        self,
        session: OrigamiSession,
        prompt: str,
    ) -> None:
        if session.active_prompt_text == prompt:
            return
        session.active_prompt_text = prompt
        logger.info(
            "session=%s overshoot prompt switched step=%s",
            session.session_id,
            session.step_index + 1,
        )

    async def _maybe_save_overshoot_debug_composite(
        self, session: OrigamiSession
    ) -> None:
        if not self._save_overshoot_composites:
            return
        if session.phase != PHASE_GUIDING:
            return

        now = time.monotonic()
        if (
            now - session.last_debug_composite_save_at
            < DEBUG_COMPOSITE_INTERVAL_SECONDS
        ):
            return
        session.last_debug_composite_save_at = now

        camera_item = await session.camera_frames.latest()
        if camera_item is None:
            return

        step = self.current_step_for(session)
        camera = _frame_to_image(camera_item[1], fallback_size=(1024, 768))
        reference = self.reference_image_for(step)
        image = _compose_reference_image(camera, reference, "Reference shape")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = self._debug_composite_dir / (
            f"{timestamp}_step-{session.step_index + 1:02d}_"
            f"{session.session_id[:8]}.jpg"
        )
        try:
            await asyncio.to_thread(_save_jpeg, image, path)
        except Exception:
            logger.exception("failed to save Overshoot debug composite to %s", path)

    def _start_overshoot_input_recorder(
        self,
        session: OrigamiSession,
        generation: int,
    ) -> OvershootInputRecorder | None:
        if not self._record_overshoot_inputs:
            return None

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = self._overshoot_input_recording_dir / (
            f"{timestamp}_step-{session.step_index + 1:02d}_"
            f"generation-{generation:04d}_{session.session_id[:8]}.mp4"
        )
        recorder = OvershootInputRecorder(path, fps=OVERSHOOT_FPS)
        try:
            recorder.start()
        except Exception:
            logger.exception("failed to start Overshoot input recorder path=%s", path)
            return None
        return recorder

    def _schedule_overshoot_input_recorder_stop(
        self,
        recorder: OvershootInputRecorder,
    ) -> None:
        task = asyncio.create_task(
            self._stop_overshoot_input_recorder(recorder),
            name=f"overshoot-input-recorder-stop-{recorder.path.stem}",
        )
        self._overshoot_input_recorder_stop_tasks.add(task)
        task.add_done_callback(self._overshoot_input_recorder_stop_tasks.discard)

    async def _stop_overshoot_input_recorder(
        self,
        recorder: OvershootInputRecorder,
    ) -> None:
        try:
            await recorder.stop()
        except Exception:
            logger.exception(
                "failed to stop Overshoot input recorder path=%s", recorder.path
            )

    async def _start_overshoot_runtime(self, session: OrigamiSession) -> None:
        first_item = await session.camera_frames.latest()
        if first_item is None:
            return

        step = self._steps[session.step_index]
        generation = session.overshoot_generation + 1
        session.overshoot_generation = generation
        session.active_prompt_text = step.prompt

        first_camera = _frame_to_image(first_item[1], fallback_size=(1024, 768))
        frame_size = first_camera.size
        created_stream_id: str | None = None
        room: rtc.Room | None = None
        source: rtc.VideoSource | None = None
        recorder: OvershootInputRecorder | None = None

        try:
            data = await self._create_overshoot_stream()
            stream_id = _stream_id_from_response(data)
            publish_url, publish_token = _publish_details_from_response(data)
            ttl_seconds = _parse_positive_int(data.get("ttl_seconds"))
            if ttl_seconds is None:
                ttl_seconds = _parse_positive_int(
                    (data.get("lease") or {}).get("ttl_seconds")
                )

            if not stream_id or not publish_url or not publish_token:
                if stream_id:
                    await self._close_overshoot_stream(stream_id)
                raise RuntimeError(
                    "Overshoot response missing stream id or publish info"
                )
            created_stream_id = stream_id

            room = rtc.Room()

            @room.on("connection_state_changed")
            def on_connection_state_changed(state: Any) -> None:
                logger.info(
                    "session=%s overshoot livekit state=%s generation=%s",
                    session.session_id,
                    state,
                    generation,
                )

            @room.on("reconnecting")
            def on_reconnecting() -> None:
                logger.info(
                    "session=%s overshoot livekit reconnecting generation=%s",
                    session.session_id,
                    generation,
                )

            @room.on("reconnected")
            def on_reconnected() -> None:
                logger.info(
                    "session=%s overshoot livekit reconnected generation=%s",
                    session.session_id,
                    generation,
                )

            @room.on("disconnected")
            def on_disconnected(*args: Any) -> None:
                reason = args[0] if args else None
                logger.info(
                    "session=%s overshoot livekit disconnected reason=%s generation=%s",
                    session.session_id,
                    reason,
                    generation,
                )
                asyncio.create_task(
                    self._notify_overshoot_closed(
                        session.session_id,
                        generation,
                        f"livekit_disconnected:{reason}",
                    )
                )

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
                rtc.TrackPublishOptions(
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
                ),
            )

            current = await self._get_session_if_current(
                session.session_id,
                generation,
            )
            if current is None:
                await source.aclose()
                await room.disconnect()
                await self._close_overshoot_stream(stream_id)
                return

            recorder = self._start_overshoot_input_recorder(current, generation)
            current.overshoot_stream_id = stream_id
            current.overshoot_lease_ttl_seconds = ttl_seconds
            current.overshoot_room = room
            current.overshoot_video_source = source
            current.overshoot_frame_size = frame_size
            current.overshoot_publish_token = publish_token
            current.overshoot_input_recorder = recorder
            current.overshoot_publish_task = asyncio.create_task(
                self._run_overshoot_livekit_publisher(
                    current.session_id,
                    generation,
                    source,
                    frame_size,
                    recorder,
                ),
                name=f"overshoot-publisher-{current.session_id}-{generation}",
            )
            current.overshoot_prompt_task = asyncio.create_task(
                self._run_overshoot_prompt_loop(
                    current.session_id,
                    stream_id,
                    generation,
                ),
                name=f"overshoot-prompts-{current.session_id}-{generation}",
            )
            current.overshoot_keepalive_task = asyncio.create_task(
                self._run_overshoot_keepalive(
                    current.session_id,
                    stream_id,
                    ttl_seconds,
                    generation,
                ),
                name=f"overshoot-keepalive-{current.session_id}-{generation}",
            )
            logger.info(
                "session=%s overshoot started step=%s stream_id=%s "
                "generation=%s livekit_track=%s frame_size=%sx%s max_bitrate=%s",
                current.session_id,
                current.step_index + 1,
                stream_id,
                generation,
                publication.sid,
                frame_size[0],
                frame_size[1],
                OVERSHOOT_PUBLISH_MAX_BITRATE_BPS,
            )
        except Exception:
            if source is not None and session.overshoot_video_source is not source:
                await source.aclose()
            if room is not None and session.overshoot_room is not room:
                await room.disconnect()
            if (
                recorder is not None
                and session.overshoot_input_recorder is not recorder
            ):
                await self._stop_overshoot_input_recorder(recorder)
            if created_stream_id and session.overshoot_stream_id != created_stream_id:
                await self._close_overshoot_stream(created_stream_id)
            await self._stop_overshoot_runtime(session)
            raise

    async def _create_overshoot_stream(self) -> dict[str, Any]:
        for attempt, delay in enumerate((0.0, *_CREATE_STREAM_RETRY_DELAYS), start=1):
            if delay:
                await asyncio.sleep(delay)
            response = await self._overshoot_http.post("/streams")
            if response.is_success:
                data = response.json()
                if not isinstance(data, dict):
                    raise RuntimeError("Overshoot stream response was not an object")
                return data
            if response.status_code == 503 and attempt <= len(
                _CREATE_STREAM_RETRY_DELAYS
            ):
                logger.warning(
                    "Overshoot stream create unavailable attempt=%s status=%s body=%s",
                    attempt,
                    response.status_code,
                    _response_text(response),
                )
                continue
            raise RuntimeError(
                "Failed to create Overshoot stream "
                f"(HTTP {response.status_code}): {_response_text(response)}"
            )
        raise RuntimeError("Failed to create Overshoot stream")

    async def _stop_overshoot_runtime(self, session: OrigamiSession) -> None:
        session.overshoot_generation += 1
        stream_id = session.overshoot_stream_id
        room = session.overshoot_room
        source = session.overshoot_video_source
        recorder = session.overshoot_input_recorder
        session.overshoot_stream_id = None
        session.overshoot_lease_ttl_seconds = None
        session.overshoot_room = None
        session.overshoot_video_source = None
        session.overshoot_frame_size = None
        session.overshoot_publish_token = None
        session.overshoot_input_recorder = None
        tasks: list[asyncio.Task[None]] = []
        for task in (
            session.overshoot_publish_task,
            session.overshoot_prompt_task,
            session.overshoot_keepalive_task,
        ):
            if task is not None:
                task.cancel()
                tasks.append(task)
        session.overshoot_publish_task = None
        session.overshoot_prompt_task = None
        session.overshoot_keepalive_task = None
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if recorder is not None:
            self._schedule_overshoot_input_recorder_stop(recorder)
        if source is not None:
            await source.aclose()
        if room is not None:
            await room.disconnect()
        if stream_id:
            await self._close_overshoot_stream(stream_id)

    async def _run_overshoot_livekit_publisher(
        self,
        session_id: str,
        generation: int,
        source: rtc.VideoSource,
        frame_size: tuple[int, int],
        recorder: OvershootInputRecorder | None,
    ) -> None:
        last_frame_id: int | None = None
        next_frame_at = time.monotonic()
        frame_count = 0
        last_log_at = time.monotonic()
        try:
            while True:
                now = time.monotonic()
                if next_frame_at > now:
                    await asyncio.sleep(next_frame_at - now)
                next_frame_at = max(
                    next_frame_at + 1.0 / OVERSHOOT_FPS,
                    time.monotonic(),
                )

                session = await self._get_session_if_current(session_id, generation)
                if session is None:
                    return

                item = await session.camera_frames.wait_for_new(
                    last_frame_id,
                    timeout_seconds=0.2,
                )
                if item is None:
                    continue
                last_frame_id = item[0]

                camera = _frame_to_image(item[1], fallback_size=frame_size)
                if recorder is not None:
                    recorder.record(camera)

                step = self.current_step_for(session)
                reference = self.reference_image_for(step)
                image = _compose_reference_image(camera, reference, "Reference shape")
                if image.size != frame_size:
                    image = image.resize(frame_size, Image.Resampling.LANCZOS)

                source.capture_frame(
                    _livekit_video_frame_from_image(image),
                    timestamp_us=int(time.monotonic() * 1_000_000),
                )
                frame_count += 1
                now = time.monotonic()
                if now - last_log_at >= 30.0:
                    logger.info(
                        "session=%s overshoot published frames=%s generation=%s",
                        session_id,
                        frame_count,
                        generation,
                    )
                    last_log_at = now
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("session=%s overshoot publisher crashed", session_id)
            await self._notify_overshoot_closed(
                session_id,
                generation,
                "publisher_failed",
            )

    async def _run_overshoot_keepalive(
        self,
        session_id: str,
        stream_id: str,
        ttl_seconds: int | None,
        generation: int,
    ) -> None:
        interval_seconds = OVERSHOOT_KEEPALIVE_INTERVAL_SECONDS
        if ttl_seconds is not None:
            interval_seconds = min(interval_seconds, max(ttl_seconds / 2.0, 5.0))
        try:
            while True:
                await asyncio.sleep(interval_seconds)
                session = await self._get_session_if_current(session_id, generation)
                if session is None:
                    return
                data = await self._post_overshoot_keepalive(stream_id)
                if data is None:
                    await session.queue.put(
                        SessionEvent(
                            kind="overshoot.closed",
                            payload={
                                "generation": generation,
                                "reason": "keepalive_failed",
                            },
                        )
                    )
                    return
                token = _publish_token_from_response(data)
                if token:
                    session.overshoot_publish_token = token
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("session=%s keepalive crashed", session_id)
            await self._notify_overshoot_closed(
                session_id,
                generation,
                "keepalive_failed",
            )

    async def _post_overshoot_keepalive(
        self,
        stream_id: str,
    ) -> dict[str, Any] | None:
        for attempt, delay in enumerate((0.0, *_KEEPALIVE_RETRY_DELAYS), start=1):
            if delay:
                await asyncio.sleep(delay)
            try:
                response = await self._overshoot_http.post(
                    f"/streams/{stream_id}/keepalive"
                )
            except httpx.HTTPError as error:
                logger.warning(
                    "stream=%s keepalive request failed attempt=%s error=%s",
                    stream_id,
                    attempt,
                    error,
                )
                continue
            if response.is_success:
                data = response.json()
                return data if isinstance(data, dict) else {}
            retryable = response.status_code in {500, 502, 503, 504}
            logger.warning(
                "stream=%s keepalive failed attempt=%s status=%s body=%s",
                stream_id,
                attempt,
                response.status_code,
                _response_text(response),
            )
            if not retryable:
                return None
        return None

    async def _run_overshoot_prompt_loop(
        self,
        session_id: str,
        stream_id: str,
        generation: int,
    ) -> None:
        try:
            ready = await self._wait_for_overshoot_first_frame(
                session_id,
                stream_id,
                generation,
            )
            if not ready:
                await self._notify_overshoot_closed(
                    session_id,
                    generation,
                    "first_frame_timeout",
                )
                return

            while True:
                started_at = time.monotonic()
                session = await self._get_session_if_current(session_id, generation)
                if session is None:
                    return
                if session.phase != PHASE_GUIDING or not session.auto_check_enabled:
                    await asyncio.sleep(0.1)
                    continue

                step_index = session.step_index
                prompt = self.current_step_for(session).prompt
                completion = await self._post_overshoot_chat_completion(
                    stream_id=stream_id,
                    session_id=session_id,
                    prompt=prompt,
                )
                received_at = time.monotonic()
                if completion is not None:
                    text = _chat_completion_text(completion)
                    logger.info(
                        "session=%s overshoot completion result=%s usage=%s cache=%s",
                        session_id,
                        text,
                        _compact_json(completion.get("usage")),
                        _compact_json(_completion_cache_metadata(completion)),
                    )
                    current = await self._get_session_if_current(
                        session_id,
                        generation,
                    )
                    if current is None:
                        return
                    await current.queue.put(
                        SessionEvent(
                            kind="overshoot.result",
                            payload={
                                "generation": generation,
                                "step_index": step_index,
                                "_received_at": received_at,
                                "prompt": prompt,
                                "result": text,
                                "ok": True,
                                "completion_id": completion.get("id"),
                            },
                        )
                    )

                elapsed = time.monotonic() - started_at
                await asyncio.sleep(
                    max(0.0, OVERSHOOT_PROMPT_INTERVAL_SECONDS - elapsed)
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("session=%s overshoot prompt loop crashed", session_id)
            await self._notify_overshoot_closed(
                session_id,
                generation,
                "prompt_loop_failed",
            )

    async def _wait_for_overshoot_first_frame(
        self,
        session_id: str,
        stream_id: str,
        generation: int,
    ) -> bool:
        deadline = time.monotonic() + OVERSHOOT_STREAM_READY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            session = await self._get_session_if_current(session_id, generation)
            if session is None:
                return False
            try:
                response = await self._overshoot_http.get(f"/streams/{stream_id}")
            except httpx.HTTPError as error:
                logger.warning(
                    "stream=%s status poll failed error=%s",
                    stream_id,
                    error,
                )
                await asyncio.sleep(OVERSHOOT_STREAM_STATUS_POLL_SECONDS)
                continue
            if response.is_success:
                data = response.json()
                if isinstance(data, dict) and data.get("last_frame_at_ms") is not None:
                    logger.info(
                        "session=%s overshoot first frame ready stream_id=%s",
                        session_id,
                        stream_id,
                    )
                    return True
                if isinstance(data, dict) and data.get("state") == "ended":
                    logger.error(
                        "session=%s overshoot stream ended before first frame body=%s",
                        session_id,
                        _compact_json(data),
                    )
                    return False
            else:
                logger.warning(
                    "stream=%s status poll failed status=%s body=%s",
                    stream_id,
                    response.status_code,
                    _response_text(response),
                )
            await asyncio.sleep(OVERSHOOT_STREAM_STATUS_POLL_SECONDS)
        return False

    async def _post_overshoot_chat_completion(
        self,
        *,
        stream_id: str,
        session_id: str,
        prompt: str,
    ) -> dict[str, Any] | None:
        payload = {
            "model": self._overshoot_model,
            "thread_id": session_id,
            "temperature": 0,
            "max_tokens": 8,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You verify origami fold completion from a live camera "
                        "view. Return exactly true or false with no explanation."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"{prompt}\n\n"
                                "Return exactly true or false. Do not include "
                                "any other text."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"ovs://streams/{stream_id}?frame_index=-1"
                            },
                        },
                    ],
                },
            ],
        }
        for attempt, delay in enumerate((0.0, *_CHAT_COMPLETION_RETRY_DELAYS), start=1):
            if delay:
                await asyncio.sleep(delay)
            try:
                response = await self._overshoot_http.post(
                    "/chat/completions",
                    json=payload,
                    timeout=OVERSHOOT_CHAT_COMPLETION_TIMEOUT_SECONDS,
                )
            except httpx.HTTPError as error:
                logger.warning(
                    "stream=%s chat completion failed attempt=%s error=%s",
                    stream_id,
                    attempt,
                    error,
                )
                continue
            if response.is_success:
                data = response.json()
                return data if isinstance(data, dict) else {}
            if response.status_code in {401, 402, 403, 404}:
                raise RuntimeError(
                    "Overshoot chat completion failed "
                    f"(HTTP {response.status_code}): {_response_text(response)}"
                )
            retryable = response.status_code in {429, 500, 502, 503, 504}
            logger.warning(
                "stream=%s chat completion failed attempt=%s status=%s body=%s",
                stream_id,
                attempt,
                response.status_code,
                _response_text(response),
            )
            if not retryable:
                return None
        return None

    async def _notify_overshoot_closed(
        self,
        session_id: str,
        generation: int,
        reason: str | None,
    ) -> None:
        session = await self._get_session_if_current(session_id, generation)
        if session is None:
            return
        await session.queue.put(
            SessionEvent(
                kind="overshoot.closed",
                payload={"generation": generation, "reason": reason},
            )
        )

    async def _get_session_if_current(
        self,
        session_id: str,
        generation: int,
    ) -> OrigamiSession | None:
        async with self._sessions_lock:
            session = self._sessions.get(session_id)
        if session is None or session.destroyed:
            return None
        if session.overshoot_generation != generation:
            return None
        return session

    async def _close_overshoot_stream(self, stream_id: str) -> None:
        try:
            response = await self._overshoot_http.delete(f"/streams/{stream_id}")
        except httpx.HTTPError as error:
            logger.warning("stream=%s close failed error=%s", stream_id, error)
            return
        if not response.is_success and response.status_code != 404:
            logger.warning(
                "stream=%s close failed status=%s body=%s",
                stream_id,
                response.status_code,
                _response_text(response),
            )


def _stream_id_from_response(data: dict[str, Any]) -> str:
    return str(data.get("id") or data.get("stream_id") or "").strip()


def _publish_details_from_response(data: dict[str, Any]) -> tuple[str, str]:
    publish = data.get("publish")
    if not isinstance(publish, dict):
        publish = data.get("livekit")
    if not isinstance(publish, dict):
        publish = {}
    url = str(publish.get("url") or "").strip()
    token = str(
        publish.get("token")
        or publish.get("livekit_token")
        or data.get("livekit_token")
        or ""
    ).strip()
    return url, token


def _publish_token_from_response(data: dict[str, Any]) -> str:
    return _publish_details_from_response(data)[1]


def _livekit_video_frame_from_image(image: Image.Image) -> rtc.VideoFrame:
    rgba = image.convert("RGBA")
    return rtc.VideoFrame(
        rgba.width,
        rgba.height,
        rtc.VideoBufferType.RGBA,
        rgba.tobytes(),
    )


def _chat_completion_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts).strip()
    return ""


def _completion_cache_metadata(data: dict[str, Any]) -> Any:
    overshoot = data.get("overshoot")
    if not isinstance(overshoot, dict):
        return None
    return overshoot.get("cache")
