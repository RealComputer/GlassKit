import time
import threading
from typing import Optional, List
from misc.state import ThreadStateManager, ConnectionState, ConsentState
from misc.types import (
    VideoData,
    AudioData,
    ProcessedVideoData,
    ProcessedAudioData,
    SpeechSegment,
    QueueStrategy,
)
from misc.queues import BoundedQueue
from misc.config import (
    VIDEO_QUEUE_SIZE,
    AUDIO_QUEUE_SIZE,
    VAD_QUEUE_SIZE,
    SPEECH_QUEUE_SIZE,
    OUTPUT_QUEUE_SIZE,
    ENABLE_TRANSCRIPTION,
    WHISPER_THREADS,
)
from misc.logging import get_logger
from misc.shutdown import get_shutdown_handler, is_shutting_down
from misc.metrics import get_metrics_collector
from misc.consent_manager import get_consent_manager
from threads.input import InputThread
from threads.video import VideoProcessingThread
from threads.audio import AudioProcessingThread
from threads.vad import VADThread
from threads.speech_worker import SpeechWorkerThread
from threads.output import OutputMuxerThread
from threads.monitor import HealthMonitorThread


logger = get_logger(__name__)


class Pipeline:
    def __init__(self):
        self.state_manager = ThreadStateManager()
        self.connection_state = ConnectionState()
        self.consent_state = ConsentState()
        self.shutdown_handler = get_shutdown_handler()
        self.metrics = get_metrics_collector()
        self.consent_manager = get_consent_manager(self.consent_state)

        self.video_input_queue: BoundedQueue[VideoData] = BoundedQueue(
            VIDEO_QUEUE_SIZE, QueueStrategy.DROP_OLDEST, "video_input"
        )

        self.audio_input_queue: BoundedQueue[AudioData] = BoundedQueue(
            AUDIO_QUEUE_SIZE, QueueStrategy.DROP_OLDEST, "audio_input"
        )

        self.vad_queue: Optional[BoundedQueue[AudioData]] = None
        self.speech_queue: Optional[BoundedQueue[SpeechSegment]] = None

        if ENABLE_TRANSCRIPTION:
            self.vad_queue = BoundedQueue(
                VAD_QUEUE_SIZE, QueueStrategy.DROP_NEWEST, "vad"
            )
            self.speech_queue = BoundedQueue(
                SPEECH_QUEUE_SIZE, QueueStrategy.DROP_OLDEST, "speech"
            )

        self.video_output_queue: BoundedQueue[ProcessedVideoData] = BoundedQueue(
            OUTPUT_QUEUE_SIZE, QueueStrategy.DROP_OLDEST, "video_output"
        )

        self.audio_output_queue: BoundedQueue[ProcessedAudioData] = BoundedQueue(
            OUTPUT_QUEUE_SIZE, QueueStrategy.DROP_OLDEST, "audio_output"
        )

        self.threads: List[threading.Thread] = []
        self._setup_threads()

    def _setup_threads(self):
        self.input_thread = InputThread(
            self.state_manager,
            self.connection_state,
            self.video_input_queue,
            self.audio_input_queue,
            self.vad_queue,
        )
        self.threads.append(self.input_thread)

        self.video_processor = VideoProcessingThread(
            self.state_manager,
            self.connection_state,
            self.consent_state,
            self.video_input_queue,
            self.video_output_queue,
        )
        self.threads.append(self.video_processor)

        self.audio_processor = AudioProcessingThread(
            self.state_manager,
            self.connection_state,
            self.audio_input_queue,
            self.audio_output_queue,
        )
        self.threads.append(self.audio_processor)

        if ENABLE_TRANSCRIPTION and self.vad_queue and self.speech_queue:
            self.vad_thread = VADThread(
                self.state_manager,
                self.connection_state,
                self.vad_queue,
                self.speech_queue,
            )
            self.threads.append(self.vad_thread)

            for i in range(WHISPER_THREADS):
                speech_worker = SpeechWorkerThread(
                    self.state_manager,
                    self.consent_state,
                    self.speech_queue,
                    worker_id=i,
                )
                self.threads.append(speech_worker)

        self.output_thread = OutputMuxerThread(
            self.state_manager,
            self.connection_state,
            self.video_output_queue,
            None,  # No raw audio queue - using processed audio
            self.audio_output_queue,
        )
        self.threads.append(self.output_thread)

        queues = {
            "video_input": self.video_input_queue,
            "audio_input": self.audio_input_queue,
            "video_output": self.video_output_queue,
            "audio_output": self.audio_output_queue,
        }

        if self.vad_queue:
            queues["vad"] = self.vad_queue
        if self.speech_queue:
            queues["speech"] = self.speech_queue

        self.monitor_thread = HealthMonitorThread(self.state_manager, queues)
        self.threads.append(self.monitor_thread)

        self.shutdown_handler.register_cleanup(self._cleanup)

    def start(self):
        logger.info("Starting pipeline...")

        # Load existing consent files before starting threads
        logger.info("Loading existing consent files...")
        self.consent_manager.load_existing_consents()

        # Start consent monitoring
        self.consent_manager.start_monitoring()

        self.shutdown_handler.register_signal_handlers()

        for thread in self.threads:
            thread.start()
            logger.info(f"Started thread: {thread.name}")

        logger.info("All threads started successfully")

    def wait(self):
        logger.info("Pipeline running. Press Ctrl-C to stop...")

        try:
            while not is_shutting_down():
                time.sleep(1)

                if not self.state_manager.all_healthy(timeout_seconds=120.0):
                    unhealthy = [
                        name
                        for name in self.state_manager.get_all_states()
                        if not self.state_manager.is_healthy(name, 120.0)
                    ]
                    if unhealthy:
                        logger.warning(f"Unhealthy threads detected: {unhealthy}")

        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")

        self.stop()

    def stop(self):
        logger.info("Stopping pipeline...")

        self.shutdown_handler.initiate_shutdown()

        # Stop consent monitoring
        self.consent_manager.stop_monitoring()

        for thread in self.threads:
            if hasattr(thread, "stop") and callable(getattr(thread, "stop")):
                getattr(thread, "stop")()

        logger.info("Waiting for threads to finish...")

        for thread in self.threads:
            thread.join(timeout=5.0)
            if thread.is_alive():
                logger.warning(f"Thread {thread.name} did not stop cleanly")
            else:
                logger.info(f"Thread {thread.name} stopped")

        self.metrics.log_summary()

        logger.info("Pipeline stopped")

    def _cleanup(self):
        logger.info("Running pipeline cleanup...")

        self.video_input_queue.clear()
        self.audio_input_queue.clear()
        self.video_output_queue.clear()
        self.audio_output_queue.clear()

        if self.vad_queue:
            self.vad_queue.clear()
        if self.speech_queue:
            self.speech_queue.clear()

        logger.info("Pipeline cleanup complete")
