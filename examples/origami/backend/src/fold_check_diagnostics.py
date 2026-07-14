from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from PIL import Image

from .constants import (
    DEBUG_COMPOSITE_INTERVAL_SECONDS,
    FOLD_CHECK_VIDEO_FPS,
    PHASE_GUIDING,
)
from .fold_check import compose_fold_check_image
from .origami_config import OrigamiStep
from .recording import FoldCheckInputRecorder
from .rendering import _frame_to_image, _save_jpeg
from .session_state import OrigamiSession

logger = logging.getLogger("uvicorn.error")


class FoldCheckDiagnostics:
    def __init__(
        self,
        *,
        save_composites: bool,
        composite_dir: Path,
        record_inputs: bool,
        input_recording_dir: Path,
    ) -> None:
        self.save_composites = save_composites
        self._composite_dir = composite_dir
        self._record_inputs = record_inputs
        self._input_recording_dir = input_recording_dir
        self._recorder_stop_tasks: set[asyncio.Task[None]] = set()

    async def close(self) -> None:
        tasks = list(self._recorder_stop_tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def maybe_save_composite(
        self,
        *,
        session: OrigamiSession,
        step: OrigamiStep,
        reference: Image.Image,
        negative_reference: Image.Image | None,
    ) -> None:
        if not self.save_composites:
            return
        if session.phase != PHASE_GUIDING:
            return

        now = asyncio.get_running_loop().time()
        fold_check = session.fold_check
        if (
            now - fold_check.last_debug_composite_save_at
            < DEBUG_COMPOSITE_INTERVAL_SECONDS
        ):
            return
        fold_check.last_debug_composite_save_at = now

        camera_item = await session.camera_frames.latest()
        if camera_item is None:
            return

        camera = _frame_to_image(camera_item[1], fallback_size=(1024, 768))
        image = compose_fold_check_image(
            camera,
            reference,
            negative_reference=negative_reference,
        )
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = self._composite_dir / (
            f"{timestamp}_step-{session.step_index + 1:02d}_"
            f"{session.session_id[:8]}.jpg"
        )
        try:
            await asyncio.to_thread(_save_jpeg, image, path)
        except Exception:
            logger.exception("failed to save fold-check debug composite to %s", path)

    def start_input_recorder(
        self,
        session: OrigamiSession,
    ) -> FoldCheckInputRecorder | None:
        if not self._record_inputs:
            return None

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = self._input_recording_dir / (
            f"{timestamp}_session-{session.session_id[:8]}.mp4"
        )
        recorder = FoldCheckInputRecorder(path, fps=FOLD_CHECK_VIDEO_FPS)
        try:
            recorder.start()
        except Exception:
            logger.exception("failed to start fold-check input recorder path=%s", path)
            return None
        return recorder

    def schedule_input_recorder_stop(
        self,
        recorder: FoldCheckInputRecorder,
    ) -> None:
        task = asyncio.create_task(
            self.stop_input_recorder(recorder),
            name=f"fold-check-input-recorder-stop-{recorder.path.stem}",
        )
        self._recorder_stop_tasks.add(task)
        task.add_done_callback(self._recorder_stop_tasks.discard)

    async def stop_input_recorder(
        self,
        recorder: FoldCheckInputRecorder,
    ) -> None:
        try:
            await recorder.stop()
        except Exception:
            logger.exception(
                "failed to stop fold-check input recorder path=%s", recorder.path
            )
