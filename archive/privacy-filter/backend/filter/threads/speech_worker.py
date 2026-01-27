import time
from typing import Optional
from faster_whisper import WhisperModel
from threads.base import BaseThread
from misc.state import ThreadStateManager, ConsentState
from misc.types import SpeechSegment
from misc.queues import BoundedQueue
from misc.config import QUEUE_TIMEOUT, CPU_THREADS, WHISPER_MODEL
from misc.consent_detector import get_consent_detector


class SpeechWorkerThread(BaseThread):
    def __init__(
        self,
        state_manager: ThreadStateManager,
        consent_state: ConsentState,
        input_queue: BoundedQueue[SpeechSegment],
        worker_id: int = 0,
    ):
        super().__init__(
            name=f"SpeechWorker-{worker_id}",
            state_manager=state_manager,
            heartbeat_interval=5.0,
        )
        self.input_queue = input_queue
        self.consent_state = consent_state
        self.worker_id = worker_id
        self.asr: Optional[WhisperModel] = None
        self.consent_detector = None
        self.transcriptions_completed = 0
        self.segments_dropped = 0

    def setup(self):
        self.logger.info(f"Loading Whisper model: {WHISPER_MODEL}")
        self.asr = WhisperModel(
            model_size_or_path=WHISPER_MODEL,
            device="cpu",
            compute_type="int8",
            cpu_threads=CPU_THREADS,
        )
        self.logger.info(
            f"Speech worker {self.worker_id} initialized with model={WHISPER_MODEL}"
        )

        self.consent_detector = get_consent_detector()
        if self.consent_detector:
            self.logger.info("Consent detector initialized")
        else:
            self.logger.warning("Consent detector not available")

    def process_iteration(self) -> bool:
        segment = self.input_queue.get(timeout=QUEUE_TIMEOUT)

        if segment is None:
            return False

        try:
            self._transcribe_segment(segment)
            return True
        except Exception as e:
            self.logger.error(f"Error transcribing segment: {e}")
            return False

    def _transcribe_segment(self, segment: SpeechSegment):
        if not self.asr:
            return

        try:
            queue_depth = self.input_queue.qsize()

            if queue_depth > 10:
                self.segments_dropped += 1
                self.logger.warning(
                    f"Queue depth high ({queue_depth}), dropping old segment "
                    f"(dropped={self.segments_dropped})"
                )
                return

            start_time = time.time()

            segments, _info = self.asr.transcribe(
                segment.audio, beam_size=5, language="en"
            )

            texts = []
            for seg in segments:
                text = seg.text.strip()
                if text:
                    texts.append(text)

            if texts:
                full_text = " ".join(texts)
                inference_time = time.time() - start_time
                segment_duration = segment.end_time - segment.start_time

                self.logger.info(f"[Transcription] {full_text}")
                self.logger.debug(
                    f"Transcribed {segment_duration:.2f}s segment in {inference_time:.2f}s "
                    f"(realtime factor: {inference_time / segment_duration:.2f}x)"
                )

                if self.consent_detector:
                    try:
                        consent_result = self.consent_detector.detect_consent(full_text)
                        if consent_result.get("consent"):
                            name = consent_result.get("speaker", "Unknown")
                            self.consent_state.set_consent(
                                name if name != "Unknown" else None
                            )
                            self.logger.info(f"[CONSENT DETECTED] Individual: {name}")
                    except Exception as e:
                        self.logger.error(f"Error in consent detection: {e}")

                self.transcriptions_completed += 1
                self.metrics.record_transcription()

        except Exception as e:
            self.logger.error(f"Error in transcription: {e}")

    def cleanup(self):
        while True:
            try:
                segment = self.input_queue.get(timeout=0.1)
                if segment is None:
                    break
                self._transcribe_segment(segment)
            except Exception:
                break

        self.logger.info(
            f"Speech worker {self.worker_id} cleanup - "
            f"completed {self.transcriptions_completed} transcriptions, "
            f"dropped {self.segments_dropped} segments"
        )

        self.asr = None
