from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from livekit import rtc
from PIL import Image

from .constants import (
    FOLD_CHECK_PUBLISH_MAX_BITRATE_BPS,
    FOLD_CHECK_VIDEO_FPS,
    FOLD_CHECK_PROMPT_INTERVAL_SECONDS,
    FOLD_CHECK_RECONNECT_INGEST_TIMEOUT_SECONDS,
    FOLD_CHECK_STREAM_READY_TIMEOUT_SECONDS,
    FOLD_CHECK_STREAM_STATUS_POLL_SECONDS,
    OVERSHOOT_KEEPALIVE_INTERVAL_SECONDS,
    PHASE_GUIDING,
)
from .fold_check import compose_fold_check_image
from .origami_config import OrigamiStep
from .overshoot_client import OvershootClient, OvershootStreamLease
from .fold_check_diagnostics import FoldCheckDiagnostics
from .overshoot_livekit import (
    OvershootLiveKitPublisher,
    capture_image,
    connect_overshoot_publisher,
    refresh_livekit_publish_token,
)
from .payload_utils import _compact_json
from .recording import FoldCheckInputRecorder
from .rendering import _frame_to_image
from .session_state import OrigamiSession, SessionEvent

logger = logging.getLogger("uvicorn.error")


class FoldCheckRuntime:
    def __init__(
        self,
        *,
        auto_check_available: bool,
        overshoot_api_key: str,
        model: str,
        sessions: dict[str, OrigamiSession],
        sessions_lock: asyncio.Lock,
        current_step_for: Callable[[OrigamiSession], OrigamiStep],
        reference_image_for: Callable[[OrigamiStep], Image.Image],
        save_composites: bool,
        debug_composite_dir: Path,
        record_inputs: bool,
        input_recording_dir: Path,
    ) -> None:
        self._auto_check_available = auto_check_available
        self._client = OvershootClient(api_key=overshoot_api_key, model=model)
        self._diagnostics = FoldCheckDiagnostics(
            save_composites=save_composites,
            composite_dir=debug_composite_dir,
            record_inputs=record_inputs,
            input_recording_dir=input_recording_dir,
        )
        self._sessions = sessions
        self._sessions_lock = sessions_lock
        self._current_step_for = current_step_for
        self._reference_image_for = reference_image_for
        self._video_source_close_tasks: set[asyncio.Task[None]] = set()

    async def close(self) -> None:
        source_close_tasks = list(self._video_source_close_tasks)
        if source_close_tasks:
            await asyncio.gather(*source_close_tasks, return_exceptions=True)
        await self._diagnostics.close()
        await self._client.close()

    async def sync_for_current_step(self, session: OrigamiSession) -> None:
        if not self._auto_check_available:
            return
        if session.phase != PHASE_GUIDING or not session.auto_check_enabled:
            return

        fold_check = session.fold_check
        if not fold_check.is_running():
            if fold_check.has_runtime_resources():
                await self.stop(session)
            if await session.camera_frames.latest() is None:
                return
            await self._start(session)
            return

        step = self._current_step_for(session)
        self._switch_prompt(session, step.criteria)

    async def maybe_save_debug_composite(self, session: OrigamiSession) -> None:
        if not self._diagnostics.save_composites:
            return
        step = self._current_step_for(session)
        reference = self._reference_image_for(step)
        await self._diagnostics.maybe_save_composite(
            session=session,
            step=step,
            reference=reference,
        )

    async def stop(self, session: OrigamiSession) -> None:
        fold_check = session.fold_check
        fold_check.runtime_epoch += 1
        snapshot = fold_check.clear_runtime()

        tasks: list[asyncio.Task[None]] = []
        current_task = asyncio.current_task()
        for task in snapshot.tasks():
            if task is None:
                continue
            task.cancel()
            if task is not current_task:
                tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        if snapshot.input_recorder is not None:
            self._diagnostics.schedule_input_recorder_stop(snapshot.input_recorder)
        if snapshot.video_source is not None:
            await snapshot.video_source.aclose()
        if snapshot.room is not None:
            await snapshot.room.disconnect()
        if snapshot.stream_id:
            await self._client.close_stream(snapshot.stream_id)

    def _switch_prompt(self, session: OrigamiSession, prompt: str) -> None:
        if not session.fold_check.update_prompt(prompt):
            return
        logger.info(
            "session=%s fold-check prompt switched step=%s",
            session.session_id,
            session.step_index + 1,
        )

    async def _start(self, session: OrigamiSession) -> None:
        first_item = await session.camera_frames.latest()
        if first_item is None:
            return

        step = self._current_step_for(session)
        runtime_epoch = session.fold_check.begin_runtime_epoch(step.criteria)
        first_camera = _frame_to_image(first_item[1], fallback_size=(1024, 768))
        frame_size = first_camera.size

        stream: OvershootStreamLease | None = None
        publisher: OvershootLiveKitPublisher | None = None
        recorder: FoldCheckInputRecorder | None = None

        try:
            stream = await self._client.create_stream()
            publisher = await self._connect_publisher(
                session=session,
                runtime_epoch=runtime_epoch,
                stream=stream,
                frame_size=frame_size,
            )

            current = await self._session_if_current(session.session_id, runtime_epoch)
            if current is None:
                await publisher.close()
                await self._client.close_stream(stream.stream_id)
                return

            recorder = self._diagnostics.start_input_recorder(current)
            fold_check = current.fold_check
            fold_check.stream_id = stream.stream_id
            fold_check.lease_ttl_seconds = stream.ttl_seconds
            fold_check.room = publisher.room
            fold_check.video_source = publisher.source
            fold_check.frame_size = frame_size
            fold_check.publish_url = stream.publish_url
            fold_check.publish_token = stream.publish_token
            fold_check.publisher_epoch = 1
            fold_check.prompt_resume_publisher_epoch = 0
            fold_check.clear_reconnect_ingest_gate()
            fold_check.livekit_recovering = False
            fold_check.input_recorder = recorder
            fold_check.publish_task = asyncio.create_task(
                self._run_publisher(
                    current.session_id,
                    runtime_epoch,
                    fold_check.publisher_epoch,
                    publisher.source,
                    frame_size,
                    recorder,
                ),
                name=f"fold-check-publisher-{current.session_id}-{runtime_epoch}",
            )
            fold_check.prompt_task = asyncio.create_task(
                self._run_prompt_loop(
                    current.session_id,
                    stream.stream_id,
                    runtime_epoch,
                ),
                name=f"fold-check-prompts-{current.session_id}-{runtime_epoch}",
            )
            fold_check.keepalive_task = asyncio.create_task(
                self._run_keepalive(
                    current.session_id,
                    stream.stream_id,
                    stream.ttl_seconds,
                    runtime_epoch,
                ),
                name=f"fold-check-keepalive-{current.session_id}-{runtime_epoch}",
            )
            logger.info(
                "session=%s fold-check started step=%s stream_id=%s "
                "runtime_epoch=%s livekit_track=%s frame_size=%sx%s max_bitrate=%s",
                current.session_id,
                current.step_index + 1,
                stream.stream_id,
                runtime_epoch,
                publisher.publication.sid,
                frame_size[0],
                frame_size[1],
                FOLD_CHECK_PUBLISH_MAX_BITRATE_BPS,
            )
        except Exception:
            fold_check = session.fold_check
            if (
                publisher is not None
                and fold_check.video_source is not publisher.source
            ):
                await publisher.close()
            if recorder is not None and fold_check.input_recorder is not recorder:
                await self._diagnostics.stop_input_recorder(recorder)
            if stream is not None and fold_check.stream_id != stream.stream_id:
                await self._client.close_stream(stream.stream_id)
            await self.stop(session)
            raise

    async def _connect_publisher(
        self,
        *,
        session: OrigamiSession,
        runtime_epoch: int,
        stream: OvershootStreamLease,
        frame_size: tuple[int, int],
    ) -> OvershootLiveKitPublisher:
        return await connect_overshoot_publisher(
            session_id=session.session_id,
            runtime_epoch=runtime_epoch,
            publish_url=stream.publish_url,
            publish_token=stream.publish_token,
            frame_size=frame_size,
            on_disconnected=lambda room, reason: self._schedule_livekit_reconnect(
                session,
                runtime_epoch,
                room,
                reason,
            ),
        )

    def _schedule_livekit_reconnect(
        self,
        session: OrigamiSession,
        runtime_epoch: int,
        disconnected_room: rtc.Room,
        reason: Any,
    ) -> None:
        fold_check = session.fold_check
        if fold_check.runtime_epoch != runtime_epoch:
            return
        if fold_check.room is not disconnected_room:
            return
        reconnect_task = fold_check.reconnect_task
        if reconnect_task is not None and not reconnect_task.done():
            return

        fold_check.start_recovery()
        task = asyncio.create_task(
            self._recover_livekit_connection(
                session.session_id,
                runtime_epoch,
                disconnected_room,
                reason,
            ),
            name=f"fold-check-livekit-reconnect-{session.session_id}-{runtime_epoch}",
        )
        fold_check.reconnect_task = task

        def on_done(done_task: asyncio.Task[None]) -> None:
            if session.fold_check.reconnect_task is done_task:
                session.fold_check.reconnect_task = None
            try:
                done_task.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception(
                    "session=%s fold-check livekit reconnect task crashed",
                    session.session_id,
                )

        task.add_done_callback(on_done)

    async def _recover_livekit_connection(
        self,
        session_id: str,
        runtime_epoch: int,
        disconnected_room: rtc.Room,
        reason: Any,
    ) -> None:
        publisher: OvershootLiveKitPublisher | None = None
        committed = False
        try:
            session = await self._session_if_current(session_id, runtime_epoch)
            if session is None or session.fold_check.room is not disconnected_room:
                return

            fold_check = session.fold_check
            stream_id = fold_check.stream_id
            publish_url = fold_check.publish_url
            publish_token = fold_check.publish_token
            frame_size = fold_check.frame_size
            recorder = fold_check.input_recorder
            if (
                stream_id is None
                or publish_url is None
                or publish_token is None
                or frame_size is None
            ):
                logger.error(
                    "session=%s fold-check livekit reconnect missing credentials "
                    "runtime_epoch=%s",
                    session_id,
                    runtime_epoch,
                )
                await self._notify_closed(
                    session_id,
                    runtime_epoch,
                    "livekit_reconnect_missing_credentials",
                )
                return

            logger.warning(
                "session=%s fold-check livekit reconnecting after disconnect "
                "reason=%s runtime_epoch=%s",
                session_id,
                reason,
                runtime_epoch,
            )
            old_publish_task = fold_check.publish_task
            fold_check.publish_task = None
            if old_publish_task is not None:
                old_publish_task.cancel()
                await asyncio.gather(old_publish_task, return_exceptions=True)

            resume_after_frame_at_ms = await self._client.last_frame_at_ms(stream_id)
            publisher = await connect_overshoot_publisher(
                session_id=session_id,
                runtime_epoch=runtime_epoch,
                publish_url=publish_url,
                publish_token=publish_token,
                frame_size=frame_size,
                on_disconnected=lambda room, new_reason: (
                    self._schedule_livekit_reconnect(
                        session,
                        runtime_epoch,
                        room,
                        new_reason,
                    )
                ),
            )
            if not publisher.room.isconnected():
                raise RuntimeError("Fold check LiveKit publisher disconnected on join")

            current = await self._session_if_current(session_id, runtime_epoch)
            if current is None or current.fold_check.room is not disconnected_room:
                return

            current_fold_check = current.fold_check
            old_source = current_fold_check.video_source
            current_fold_check.publisher_epoch += 1
            publisher_epoch = current_fold_check.publisher_epoch
            current_fold_check.room = publisher.room
            current_fold_check.video_source = publisher.source
            current_fold_check.prompt_resume_after_publisher_epoch = (
                publisher_epoch if resume_after_frame_at_ms is not None else 0
            )
            current_fold_check.prompt_resume_after_frame_at_ms = (
                resume_after_frame_at_ms
            )
            current_fold_check.prompt_resume_deadline_at = (
                time.monotonic() + FOLD_CHECK_RECONNECT_INGEST_TIMEOUT_SECONDS
                if resume_after_frame_at_ms is not None
                else 0.0
            )
            current_fold_check.publish_task = asyncio.create_task(
                self._run_publisher(
                    current.session_id,
                    runtime_epoch,
                    publisher_epoch,
                    publisher.source,
                    frame_size,
                    recorder,
                ),
                name=f"fold-check-publisher-{current.session_id}-{runtime_epoch}",
            )
            committed = True
            if old_source is not None and old_source is not publisher.source:
                self._schedule_video_source_close(old_source, session_id)
            logger.info(
                "session=%s fold-check livekit reconnected runtime_epoch=%s "
                "publisher_epoch=%s livekit_track=%s",
                session_id,
                runtime_epoch,
                publisher_epoch,
                publisher.publication.sid,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "session=%s fold-check livekit reconnect failed", session_id
            )
            await self._notify_closed(
                session_id,
                runtime_epoch,
                "livekit_reconnect_failed",
            )
        finally:
            if not committed and publisher is not None:
                await publisher.close()

    async def _run_publisher(
        self,
        session_id: str,
        runtime_epoch: int,
        publisher_epoch: int,
        source: rtc.VideoSource,
        frame_size: tuple[int, int],
        recorder: FoldCheckInputRecorder | None,
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
                    next_frame_at + 1.0 / FOLD_CHECK_VIDEO_FPS,
                    time.monotonic(),
                )

                session = await self._session_if_current(session_id, runtime_epoch)
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

                step = self._current_step_for(session)
                reference = self._reference_image_for(step)
                image = compose_fold_check_image(camera, reference)
                if image.size != frame_size:
                    image = image.resize(frame_size, Image.Resampling.LANCZOS)

                capture_image(source, image)
                frame_count += 1

                fold_check = session.fold_check
                if (
                    fold_check.livekit_recovering
                    and publisher_epoch >= fold_check.prompt_resume_publisher_epoch
                ):
                    fold_check.livekit_recovering = False
                    fold_check.prompt_resume_publisher_epoch = 0
                    logger.info(
                        "session=%s fold-check prompts resumed after "
                        "post-reconnect frame runtime_epoch=%s publisher_epoch=%s",
                        session_id,
                        runtime_epoch,
                        publisher_epoch,
                    )
                now = time.monotonic()
                if now - last_log_at >= 30.0:
                    logger.info(
                        "session=%s fold-check published frames=%s runtime_epoch=%s "
                        "publisher_epoch=%s",
                        session_id,
                        frame_count,
                        runtime_epoch,
                        publisher_epoch,
                    )
                    last_log_at = now
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("session=%s fold-check publisher crashed", session_id)
            await self._notify_closed(session_id, runtime_epoch, "publisher_failed")

    async def _run_keepalive(
        self,
        session_id: str,
        stream_id: str,
        ttl_seconds: int | None,
        runtime_epoch: int,
    ) -> None:
        interval_seconds = OVERSHOOT_KEEPALIVE_INTERVAL_SECONDS
        if ttl_seconds is not None:
            interval_seconds = min(interval_seconds, max(ttl_seconds / 2.0, 5.0))
        try:
            while True:
                await asyncio.sleep(interval_seconds)
                session = await self._session_if_current(session_id, runtime_epoch)
                if session is None:
                    return
                result = await self._client.keepalive(stream_id)
                if result is None:
                    await session.queue.put(
                        SessionEvent(
                            kind="fold_check.closed",
                            payload={
                                "runtime_epoch": runtime_epoch,
                                "reason": "keepalive_failed",
                            },
                        )
                    )
                    return
                fold_check = session.fold_check
                if result.publish_url:
                    fold_check.publish_url = result.publish_url
                if result.publish_token:
                    fold_check.publish_token = result.publish_token
                    if fold_check.room is not None:
                        refresh_livekit_publish_token(
                            fold_check.room,
                            result.publish_token,
                        )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("session=%s keepalive crashed", session_id)
            await self._notify_closed(session_id, runtime_epoch, "keepalive_failed")

    async def _run_prompt_loop(
        self,
        session_id: str,
        stream_id: str,
        runtime_epoch: int,
    ) -> None:
        try:
            ready = await self._wait_for_first_frame(
                session_id, stream_id, runtime_epoch
            )
            if not ready:
                await self._notify_closed(
                    session_id,
                    runtime_epoch,
                    "first_frame_timeout",
                )
                return

            while True:
                started_at = time.monotonic()
                session = await self._wait_for_prompt_slot(
                    session_id,
                    stream_id,
                    runtime_epoch,
                )
                if session is None:
                    return
                await self._request_fold_check(session, stream_id, runtime_epoch)

                elapsed = time.monotonic() - started_at
                await asyncio.sleep(
                    max(0.0, FOLD_CHECK_PROMPT_INTERVAL_SECONDS - elapsed)
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("session=%s fold-check prompt loop crashed", session_id)
            await self._notify_closed(session_id, runtime_epoch, "prompt_loop_failed")

    async def _wait_for_prompt_slot(
        self,
        session_id: str,
        stream_id: str,
        runtime_epoch: int,
    ) -> OrigamiSession | None:
        while True:
            session = await self._session_if_current(session_id, runtime_epoch)
            if session is None:
                return None
            if session.phase != PHASE_GUIDING or not session.auto_check_enabled:
                await asyncio.sleep(0.1)
                continue

            fold_check = session.fold_check
            if fold_check.prompts_are_recovering():
                await asyncio.sleep(0.1)
                continue

            if fold_check.prompt_resume_after_frame_at_ms is not None:
                ingest_ready = await self._check_reconnect_ingest(
                    session=session,
                    stream_id=stream_id,
                    runtime_epoch=runtime_epoch,
                )
                if ingest_ready is None:
                    return None
                if not ingest_ready:
                    continue
            return session

    async def _check_reconnect_ingest(
        self,
        *,
        session: OrigamiSession,
        stream_id: str,
        runtime_epoch: int,
    ) -> bool | None:
        fold_check = session.fold_check
        resume_after_frame_at_ms = fold_check.prompt_resume_after_frame_at_ms
        if resume_after_frame_at_ms is None:
            return True

        gate_publisher_epoch = fold_check.prompt_resume_after_publisher_epoch
        gate_deadline_at = fold_check.prompt_resume_deadline_at
        last_frame_at_ms = await self._client.last_frame_at_ms(stream_id)
        current = await self._session_if_current(session.session_id, runtime_epoch)
        if current is None:
            return None

        current_fold_check = current.fold_check
        if (
            current_fold_check.prompt_resume_after_frame_at_ms
            != resume_after_frame_at_ms
            or current_fold_check.prompt_resume_after_publisher_epoch
            != gate_publisher_epoch
        ):
            return False
        if (
            current_fold_check.livekit_recovering
            or current_fold_check.publisher_epoch < gate_publisher_epoch
        ):
            await asyncio.sleep(0.1)
            return False
        if last_frame_at_ms is None or last_frame_at_ms <= resume_after_frame_at_ms:
            if gate_deadline_at > 0 and time.monotonic() >= gate_deadline_at:
                logger.error(
                    "session=%s fold-check reconnect ingest timed out "
                    "runtime_epoch=%s publisher_epoch=%s baseline_ms=%s "
                    "last_frame_at_ms=%s",
                    session.session_id,
                    runtime_epoch,
                    gate_publisher_epoch,
                    resume_after_frame_at_ms,
                    last_frame_at_ms,
                )
                await self._notify_closed(
                    session.session_id,
                    runtime_epoch,
                    "reconnect_ingest_timeout",
                )
                return None
            await asyncio.sleep(FOLD_CHECK_STREAM_STATUS_POLL_SECONDS)
            return False

        current_fold_check.clear_reconnect_ingest_gate()
        return True

    async def _request_fold_check(
        self,
        session: OrigamiSession,
        stream_id: str,
        runtime_epoch: int,
    ) -> None:
        step_index = session.step_index
        prompt = self._current_step_for(session).criteria
        publisher_epoch = session.fold_check.publisher_epoch
        completion = await self._client.chat_completion(
            stream_id=stream_id,
            prompt=prompt,
        )
        received_at = time.monotonic()
        if completion is None:
            return

        logger.info(
            "session=%s fold-check completion result=%s usage=%s cache=%s",
            session.session_id,
            completion.text,
            _compact_json(completion.usage),
            _compact_json(completion.cache),
        )
        current = await self._session_if_current(session.session_id, runtime_epoch)
        if current is None:
            return

        fold_check = current.fold_check
        if (
            fold_check.livekit_recovering
            or fold_check.prompt_resume_after_frame_at_ms is not None
            or fold_check.publisher_epoch != publisher_epoch
        ):
            logger.info(
                "session=%s fold-check completion ignored during "
                "publisher recovery runtime_epoch=%s "
                "request_publisher_epoch=%s current_publisher_epoch=%s",
                session.session_id,
                runtime_epoch,
                publisher_epoch,
                fold_check.publisher_epoch,
            )
            return

        await current.queue.put(
            SessionEvent(
                kind="fold_check.result",
                payload={
                    "runtime_epoch": runtime_epoch,
                    "step_index": step_index,
                    "_received_at": received_at,
                    "prompt": prompt,
                    "result": completion.text,
                    "ok": True,
                    "completion_id": completion.completion_id,
                },
            )
        )

    async def _wait_for_first_frame(
        self,
        session_id: str,
        stream_id: str,
        runtime_epoch: int,
    ) -> bool:
        deadline = time.monotonic() + FOLD_CHECK_STREAM_READY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            session = await self._session_if_current(session_id, runtime_epoch)
            if session is None:
                return False
            status = await self._client.stream_status(stream_id)
            if status is not None:
                if status.last_frame_at_ms is not None:
                    logger.info(
                        "session=%s fold-check first frame ready stream_id=%s",
                        session_id,
                        stream_id,
                    )
                    return True
                if status.state == "ended":
                    logger.error(
                        "session=%s fold-check stream ended before first frame body=%s",
                        session_id,
                        _compact_json(status.raw),
                    )
                    return False
            await asyncio.sleep(FOLD_CHECK_STREAM_STATUS_POLL_SECONDS)
        return False

    async def _notify_closed(
        self,
        session_id: str,
        runtime_epoch: int,
        reason: str | None,
    ) -> None:
        session = await self._session_if_current(session_id, runtime_epoch)
        if session is None:
            return
        await session.queue.put(
            SessionEvent(
                kind="fold_check.closed",
                payload={"runtime_epoch": runtime_epoch, "reason": reason},
            )
        )

    async def _session_if_current(
        self,
        session_id: str,
        runtime_epoch: int,
    ) -> OrigamiSession | None:
        async with self._sessions_lock:
            session = self._sessions.get(session_id)
        if session is None or session.destroyed:
            return None
        if session.fold_check.runtime_epoch != runtime_epoch:
            return None
        return session

    def _schedule_video_source_close(
        self,
        source: rtc.VideoSource,
        session_id: str,
    ) -> None:
        task = asyncio.create_task(
            self._close_video_source(source, session_id),
            name=f"fold-check-video-source-close-{session_id}",
        )
        self._video_source_close_tasks.add(task)
        task.add_done_callback(self._video_source_close_tasks.discard)

    async def _close_video_source(
        self,
        source: rtc.VideoSource,
        session_id: str,
    ) -> None:
        try:
            await source.aclose()
        except Exception:
            logger.warning(
                "session=%s failed to close old fold-check video source",
                session_id,
                exc_info=True,
            )
