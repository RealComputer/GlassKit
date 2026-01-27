import numpy as np
import torch
from typing import Optional, List
from av.audio.resampler import AudioResampler
from av.audio.frame import AudioFrame
from silero_vad import load_silero_vad
from threads.base import BaseThread
from misc.state import ThreadStateManager, ConnectionState
from misc.types import AudioData, SpeechSegment
from misc.queues import BoundedQueue
from misc.config import QUEUE_TIMEOUT, CPU_THREADS


class VADThread(BaseThread):
    def __init__(
        self,
        state_manager: ThreadStateManager,
        connection_state: ConnectionState,
        input_queue: BoundedQueue[AudioData],
        output_queue: BoundedQueue[SpeechSegment],
        start_speech_prob: float = 0.1,
        keep_speech_prob: float = 0.3,
        stop_silence_ms: int = 500,
        min_segment_ms: int = 500,
        sampling_rate: int = 16000,
        chunk_size: int = 512,
    ):
        super().__init__(
            name="VAD", state_manager=state_manager, heartbeat_interval=1.0
        )
        self.connection_state = connection_state
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.sampling_rate = sampling_rate
        self.chunk_size = chunk_size
        self.chunk_bytes = chunk_size * 2
        self.start_speech_prob = start_speech_prob
        self.keep_speech_prob = keep_speech_prob
        self.stop_silence_samples = sampling_rate * stop_silence_ms // 1000
        self.min_segment_samples = sampling_rate * min_segment_ms // 1000

        self.vad: Optional[torch.nn.Module] = None
        self.resampler: Optional[AudioResampler] = None

        self.ring_buffer = bytearray()
        self.speech_buffer: List[np.ndarray] = []
        self.in_speech = False
        self.silence_samples = 0
        self.stream_time_offset = 0.0
        self.speech_start_time = 0.0
        self.segments_produced = 0

    def setup(self):
        self.logger.info("Loading Silero VAD model...")
        torch.set_num_threads(CPU_THREADS)
        vad_model = load_silero_vad()
        if isinstance(vad_model, torch.nn.Module):
            self.vad = vad_model

        self.logger.info(
            f"VAD initialized (start_prob={self.start_speech_prob:.2f}, "
            f"keep_prob={self.keep_speech_prob:.2f}, "
            f"silence={self.stop_silence_samples * 1000 // self.sampling_rate}ms, "
            f"min_segment={self.min_segment_samples * 1000 // self.sampling_rate}ms)"
        )

    def process_iteration(self) -> bool:
        if not self.connection_state.is_input_connected():
            if self.speech_buffer or self.ring_buffer:
                self.speech_buffer.clear()
                self.ring_buffer.clear()
                self.in_speech = False
                self.silence_samples = 0
            return False

        audio_data = self.input_queue.get(timeout=QUEUE_TIMEOUT)

        if audio_data is None:
            return False

        try:
            self._process_audio_frame(audio_data.frame)
            return True
        except Exception as e:
            self.logger.error(f"Error processing audio frame: {e}")
            return False

    def _setup_resampler_if_needed(self, frame: AudioFrame):
        if self.resampler is not None:
            return

        self.resampler = AudioResampler(
            format="s16", layout="mono", rate=self.sampling_rate
        )

        self.logger.info(
            f"Resampler configured: {frame.format.name}/{frame.layout.name}/{frame.sample_rate}Hz -> "
            f"s16/mono/{self.sampling_rate}Hz"
        )

    def _process_audio_frame(self, frame: AudioFrame):
        self._setup_resampler_if_needed(frame)

        if not self.resampler:
            return

        resampled_frames = self.resampler.resample(frame)

        for resampled_frame in resampled_frames:
            mono_array = resampled_frame.to_ndarray()

            if len(mono_array.shape) > 1:
                mono_array = mono_array[0]

            if mono_array.dtype != np.int16:
                if mono_array.dtype in [np.float32, np.float64]:
                    mono_array = (mono_array * 32768).astype(np.int16)
                else:
                    mono_array = mono_array.astype(np.int16)

            self.ring_buffer.extend(mono_array.tobytes())

            while len(self.ring_buffer) >= self.chunk_bytes:
                chunk_bytes = self.ring_buffer[: self.chunk_bytes]
                chunk = np.frombuffer(chunk_bytes, np.int16)
                self.ring_buffer = self.ring_buffer[self.chunk_bytes :]

                self._process_vad_chunk(chunk)

    def _process_vad_chunk(self, chunk: np.ndarray):
        if not self.vad:
            return

        chunk_float = chunk.astype(np.float32) / 32768.0
        chunk_tensor = torch.from_numpy(chunk_float)

        prob = self.vad(chunk_tensor, self.sampling_rate).item()

        if self.in_speech:
            self.speech_buffer.append(chunk)

            if prob > self.keep_speech_prob:
                self.silence_samples = 0
            else:
                self.silence_samples += self.chunk_size

                if self.silence_samples >= self.stop_silence_samples:
                    self.in_speech = False
                    self.logger.debug(
                        f"Speech ended at {self.stream_time_offset:.2f}s, queuing segment..."
                    )
                    self._queue_speech_segment()
                    self.speech_buffer.clear()
                    self.silence_samples = 0
        else:
            if prob > self.start_speech_prob:
                self.in_speech = True
                self.speech_start_time = self.stream_time_offset
                self.speech_buffer.append(chunk)
                self.silence_samples = 0
                self.logger.debug(f"Speech started at {self.speech_start_time:.2f}s")

        self.stream_time_offset += self.chunk_size / self.sampling_rate

    def _queue_speech_segment(self):
        if not self.speech_buffer:
            return

        audio = np.concatenate(self.speech_buffer, axis=0)

        if len(audio) < self.min_segment_samples:
            self.logger.debug(
                f"Speech segment too short ({len(audio)} samples), skipping"
            )
            return

        audio_float = audio.astype(np.float32) / 32768.0

        segment = SpeechSegment(
            audio=audio_float,
            start_time=self.speech_start_time,
            end_time=self.stream_time_offset,
            sample_rate=self.sampling_rate,
        )

        try:
            if not self.output_queue.put(segment, timeout=0.05):
                self.logger.warning(
                    "Speech queue full, dropping segment (backpressure)"
                )
            else:
                self.segments_produced += 1
                self.logger.debug(
                    f"Queued speech segment #{self.segments_produced} "
                    f"(duration={segment.end_time - segment.start_time:.2f}s)"
                )
        except Exception as e:
            self.logger.error(f"Error queuing speech segment: {e}")

    def cleanup(self):
        if self.speech_buffer:
            self._queue_speech_segment()

        self.logger.info(
            f"VAD cleanup - produced {self.segments_produced} speech segments"
        )

        self.ring_buffer.clear()
        self.speech_buffer.clear()
        self.vad = None
        self.resampler = None
