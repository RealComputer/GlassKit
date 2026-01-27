import av
from av.container import InputContainer
from av.video.frame import VideoFrame
from av.audio.frame import AudioFrame
from av.error import TimeoutError, FFmpegError
from typing import Optional, Any
from threads.base import BaseThread
from misc.state import ThreadStateManager, ConnectionState
from misc.types import VideoData, AudioData
from misc.queues import BoundedQueue
from misc.config import IN_URL, CONNECTION_TIMEOUT, ENABLE_TRANSCRIPTION


class InputThread(BaseThread):
    def __init__(
        self,
        state_manager: ThreadStateManager,
        connection_state: ConnectionState,
        video_queue: BoundedQueue[VideoData],
        audio_queue: BoundedQueue[AudioData],
        vad_queue: Optional[BoundedQueue[AudioData]] = None,
    ):
        super().__init__(
            name="InputDemuxer", state_manager=state_manager, heartbeat_interval=1.0
        )
        self.connection_state = connection_state
        self.video_queue = video_queue
        self.audio_queue = audio_queue
        self.vad_queue = vad_queue
        self.in_container: Optional[InputContainer] = None
        self.demux_iterator: Optional[Any] = None
        self.has_audio = False
        self.has_video = False
        self.frame_sequence = 0
        self.audio_sequence = 0
        self.stream_time = 0.0
        self.waiting_logged = False

    def setup(self):
        self.logger.info(f"Starting input thread, listening on {IN_URL}")

    def process_iteration(self) -> bool:
        if not self.in_container:
            if not self._connect():
                # Return True to indicate we processed (attempted connection)
                # BaseThread will add minimal sleep if needed
                return True
            # Connected successfully, set up demux iterator
            if self.in_container:
                self.demux_iterator = self.in_container.demux()
            return True

        try:
            # Process single packet per iteration for responsiveness
            return self._process_single_packet()
        except (TimeoutError, StopIteration):
            self._disconnect()
            return False
        except (FFmpegError, OSError) as e:
            if "Immediate exit requested" not in str(e):
                self.logger.warning(f"Stream error: {e}")
            self._disconnect()
            return False

    def _connect(self) -> bool:
        try:
            if not self.waiting_logged:
                self.logger.info("Waiting for RTMP publisher...")
                self.waiting_logged = True

            self.in_container = av.open(
                IN_URL, mode="r", options={"listen": "1"}, timeout=CONNECTION_TIMEOUT
            )

            self.has_video = len(self.in_container.streams.video) > 0
            self.has_audio = len(self.in_container.streams.audio) > 0

            metadata: dict[str, Any] = {
                "has_video": self.has_video,
                "has_audio": self.has_audio,
            }

            if self.has_video:
                video_stream = self.in_container.streams.video[0]
                metadata["video_codec"] = video_stream.codec_context.name
                metadata["video_width"] = video_stream.codec_context.width
                metadata["video_height"] = video_stream.codec_context.height
                metadata["video_fps"] = float(video_stream.average_rate or 0)

            if self.has_audio:
                audio_stream = self.in_container.streams.audio[0]
                metadata["audio_codec"] = audio_stream.codec_context.name
                metadata["audio_rate"] = audio_stream.codec_context.sample_rate
                metadata["audio_channels"] = audio_stream.codec_context.channels

            self.connection_state.set_input_connected(True, metadata)
            self.logger.info(f"Publisher connected: {metadata}")

            self.frame_sequence = 0
            self.audio_sequence = 0
            self.stream_time = 0.0
            self.waiting_logged = False

            return True

        except TimeoutError:
            return False
        except (FFmpegError, OSError) as e:
            if "Immediate exit requested" in str(e):
                return False
            self.logger.error(f"Connection error: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected connection error: {e}")
            return False

    def _disconnect(self):
        self.demux_iterator = None

        if self.in_container:
            try:
                self.in_container.close()
            except Exception:
                pass
            self.in_container = None

        self.connection_state.set_input_connected(False)
        self.logger.info("Publisher disconnected")
        self.waiting_logged = False

        # Clear all queues when input disconnects
        self.logger.debug("Clearing queues after disconnect")
        self.video_queue.clear()
        self.audio_queue.clear()
        if self.vad_queue:
            self.vad_queue.clear()

    def _process_single_packet(self) -> bool:
        """Process a single packet per iteration for better responsiveness."""
        if not self.demux_iterator:
            return False

        try:
            # Get next packet without blocking indefinitely
            packet = next(self.demux_iterator)

            if packet.stream.type == "video" and self.has_video:
                frames = packet.decode()
                for frame in frames:
                    if isinstance(frame, VideoFrame):
                        self._process_video_frame(frame)

            elif packet.stream.type == "audio" and self.has_audio:
                frames = packet.decode()
                for frame in frames:
                    if isinstance(frame, AudioFrame):
                        self._process_audio_frame(frame)

            return True  # Processed a packet

        except StopIteration:
            # Stream ended
            raise

    def _process_video_frame(self, frame: VideoFrame):
        timestamp = float(frame.time) if frame.time else self.stream_time

        video_data = VideoData(
            frame=frame, timestamp=timestamp, sequence=self.frame_sequence
        )

        if not self.video_queue.put(video_data, timeout=0.001):
            self.metrics.record_dropped_frame()
            self.logger.debug(f"Dropped video frame {self.frame_sequence}")

        self.frame_sequence += 1
        self.stream_time = timestamp

    def _process_audio_frame(self, frame: AudioFrame):
        timestamp = float(frame.time) if frame.time else self.stream_time

        audio_data = AudioData(
            frame=frame, timestamp=timestamp, sequence=self.audio_sequence
        )

        self.audio_queue.put(audio_data, timeout=0.001)

        if ENABLE_TRANSCRIPTION and self.vad_queue:
            self.vad_queue.put(audio_data, timeout=0.001)

        self.audio_sequence += 1

    def cleanup(self):
        self._disconnect()
        self.logger.info("Input thread cleanup complete")
