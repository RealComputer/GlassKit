import threading
import time
from typing import Optional
from collections import deque
from misc.types import StreamMetrics
from misc.logging import get_logger


logger = get_logger(__name__)


class MetricsCollector:
    def __init__(self, window_size: int = 100):
        self._lock = threading.RLock()
        self._metrics = StreamMetrics()
        self._fps_window = deque(maxlen=window_size)
        self._last_frame_time: Optional[float] = None
        self._start_time = time.time()

    def record_frame(self, faces_detected: int = 0):
        with self._lock:
            current_time = time.time()

            self._metrics.frames_processed += 1
            self._metrics.faces_detected_total += faces_detected

            if self._last_frame_time is not None:
                frame_interval = current_time - self._last_frame_time
                if frame_interval > 0:
                    instant_fps = 1.0 / frame_interval
                    self._fps_window.append(instant_fps)

                    if len(self._fps_window) > 0:
                        self._metrics.average_fps = sum(self._fps_window) / len(
                            self._fps_window
                        )

            self._last_frame_time = current_time

    def record_audio_packet(self):
        with self._lock:
            self._metrics.audio_packets_processed += 1

    def record_dropped_frame(self):
        with self._lock:
            self._metrics.frames_dropped += 1

    def record_transcription(self):
        with self._lock:
            self._metrics.transcriptions_completed += 1

    def update_queue_depth(self, queue_name: str, depth: int):
        with self._lock:
            if self._metrics.queue_depths is None:
                self._metrics.queue_depths = {}
            self._metrics.queue_depths[queue_name] = depth

    def get_metrics(self) -> StreamMetrics:
        with self._lock:
            metrics_copy = StreamMetrics(
                frames_processed=self._metrics.frames_processed,
                frames_dropped=self._metrics.frames_dropped,
                audio_packets_processed=self._metrics.audio_packets_processed,
                faces_detected_total=self._metrics.faces_detected_total,
                transcriptions_completed=self._metrics.transcriptions_completed,
                average_fps=self._metrics.average_fps,
                queue_depths=self._metrics.queue_depths.copy()
                if self._metrics.queue_depths
                else {},
            )
            return metrics_copy

    def get_uptime(self) -> float:
        return time.time() - self._start_time

    def reset(self):
        with self._lock:
            self._metrics = StreamMetrics()
            self._fps_window.clear()
            self._last_frame_time = None
            self._start_time = time.time()

    def log_summary(self):
        metrics = self.get_metrics()
        uptime = self.get_uptime()

        logger.info(
            f"Metrics Summary - Uptime: {uptime:.1f}s, "
            f"Frames: {metrics.frames_processed} (dropped: {metrics.frames_dropped}), "
            f"FPS: {metrics.average_fps:.1f}, "
            f"Audio packets: {metrics.audio_packets_processed}, "
            f"Faces: {metrics.faces_detected_total}, "
            f"Transcriptions: {metrics.transcriptions_completed}"
        )

        if metrics.queue_depths:
            queue_info = ", ".join(
                [f"{k}: {v}" for k, v in metrics.queue_depths.items()]
            )
            logger.info(f"Queue depths - {queue_info}")


_metrics_collector: Optional[MetricsCollector] = None
_metrics_lock = threading.Lock()


def get_metrics_collector() -> MetricsCollector:
    global _metrics_collector
    if _metrics_collector is None:
        with _metrics_lock:
            if _metrics_collector is None:
                _metrics_collector = MetricsCollector()
    return _metrics_collector
