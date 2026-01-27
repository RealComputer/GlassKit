from av.audio.stream import AudioStream
from av.audio.frame import AudioFrame
from av.audio.resampler import AudioResampler
from typing import Optional
from threads.base import BaseThread
from misc.state import ThreadStateManager, ConnectionState
from misc.types import AudioData, ProcessedAudioData
from misc.queues import BoundedQueue
from misc.config import QUEUE_TIMEOUT


class AudioProcessingThread(BaseThread):
    def __init__(
        self,
        state_manager: ThreadStateManager,
        connection_state: ConnectionState,
        input_queue: BoundedQueue[AudioData],
        output_queue: BoundedQueue[ProcessedAudioData],
    ):
        super().__init__(
            name="AudioProcessor", state_manager=state_manager, heartbeat_interval=1.0
        )
        self.connection_state = connection_state
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.resampler: Optional[AudioResampler] = None
        self.output_stream: Optional[AudioStream] = None
        self.packets_processed = 0
        self.codec_context_configured = False

    def setup(self):
        self.logger.info("Audio processing thread initialized")

    def process_iteration(self) -> bool:
        # Don't process if input is not connected
        if not self.connection_state.is_input_connected():
            return False

        audio_data = self.input_queue.get(timeout=QUEUE_TIMEOUT)

        if audio_data is None:
            return False

        try:
            self._setup_resampler_if_needed(audio_data.frame)

            processed_packets = self._transcode_frame(audio_data)

            for packet_data in processed_packets:
                if not self.output_queue.put(packet_data, timeout=QUEUE_TIMEOUT):
                    self.logger.debug(f"Dropped audio packet {packet_data.sequence}")

            self.packets_processed += 1

            if self.packets_processed % 100 == 0:
                self.logger.debug(f"Processed {self.packets_processed} audio packets")

            return True

        except Exception as e:
            self.logger.error(f"Error processing audio {audio_data.sequence}: {e}")
            return False

    def _setup_resampler_if_needed(self, frame: AudioFrame):
        if self.resampler is not None:
            return

        input_rate = frame.sample_rate
        input_layout = str(frame.layout.name)
        input_format = str(frame.format.name)

        if input_rate != 48000:
            # Get channel count from layout name
            is_stereo = (
                "stereo" in input_layout.lower()
                or "5.1" in input_layout
                or "7.1" in input_layout
            )
            self.resampler = AudioResampler(
                format="s16", layout="stereo" if is_stereo else "mono", rate=48000
            )
            self.logger.info(
                f"Audio resampler configured: {input_format}/{input_layout}/{input_rate}Hz -> s16/48kHz"
            )

    def _transcode_frame(self, audio_data: AudioData) -> list[ProcessedAudioData]:
        frames_to_encode = [audio_data.frame]

        if self.resampler:
            resampled = self.resampler.resample(audio_data.frame)
            if isinstance(resampled, list):
                frames_to_encode = resampled
            else:
                frames_to_encode = [resampled]

            # Preserve timing information on resampled frames
            for frame in frames_to_encode:
                frame.pts = audio_data.frame.pts
                frame.time_base = audio_data.frame.time_base

        processed_packets = []

        if not self.codec_context_configured:
            self._configure_output_codec(audio_data.frame)

        for frame in frames_to_encode:
            packet_data = ProcessedAudioData(
                frame=frame,
                timestamp=audio_data.timestamp,
                sequence=audio_data.sequence,
            )
            processed_packets.append(packet_data)

            self.metrics.record_audio_packet()

        return processed_packets

    def _configure_output_codec(self, frame: AudioFrame):
        self.codec_context_configured = True
        self.logger.info("Audio codec configuration complete for Opus output")

    def cleanup(self):
        self.logger.info(
            f"Audio processor cleanup - processed {self.packets_processed} packets"
        )
        self.resampler = None
        self.output_stream = None
