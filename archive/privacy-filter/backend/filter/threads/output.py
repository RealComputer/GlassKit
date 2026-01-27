import av
from av.container import OutputContainer
from av.video.stream import VideoStream
from av.audio.stream import AudioStream
from av.audio.resampler import AudioResampler
from typing import Optional, Dict, Any
from threads.base import BaseThread
from misc.state import ThreadStateManager, ConnectionState
from misc.types import ProcessedVideoData, ProcessedAudioData, AudioData
from misc.queues import BoundedQueue
from misc.config import (
    OUT_URL,
    FPS,
    CONNECTION_TIMEOUT,
    VIDEO_CODEC,
    VIDEO_PRESET,
    VIDEO_TUNE,
    VIDEO_PIX_FMT,
    RTSP_TRANSPORT,
)


class OutputMuxerThread(BaseThread):
    def __init__(
        self,
        state_manager: ThreadStateManager,
        connection_state: ConnectionState,
        video_queue: BoundedQueue[ProcessedVideoData],
        audio_queue: Optional[BoundedQueue[AudioData]],
        audio_processed_queue: Optional[BoundedQueue[ProcessedAudioData]] = None,
    ):
        super().__init__(
            name="OutputMuxer", state_manager=state_manager, heartbeat_interval=1.0
        )
        self.connection_state = connection_state
        self.video_queue = video_queue
        self.audio_queue = audio_queue
        self.audio_processed_queue = audio_processed_queue
        self.out_container: Optional[OutputContainer] = None
        self.video_stream: Optional[VideoStream] = None
        self.audio_stream: Optional[AudioStream] = None
        self.resampler: Optional[AudioResampler] = None
        self.stream_metadata: Dict[str, Any] = {}
        self.frames_written = 0
        self.audio_packets_written = 0

    def setup(self):
        self.logger.info(f"Output muxer initialized, will push to {OUT_URL}")

    def process_iteration(self) -> bool:
        if not self.connection_state.is_input_connected():
            if self.out_container:
                self._disconnect()
            return False

        if not self.out_container:
            metadata = self.connection_state.get_stream_metadata()
            if metadata and metadata.get("has_video"):
                if not self._connect(metadata):
                    return False
            else:
                return False

        processed = False

        video_data = self.video_queue.get_nowait()
        if video_data:
            self._process_video(video_data)
            processed = True

        if self.audio_stream:
            if self.audio_processed_queue:
                audio_data = self.audio_processed_queue.get_nowait()
                if audio_data:
                    self._process_processed_audio(audio_data)
                    processed = True
            elif self.audio_queue:
                audio_data = self.audio_queue.get_nowait()
                if audio_data:
                    self._process_raw_audio(audio_data)
                    processed = True

        return processed

    def _connect(self, metadata: Dict[str, Any]) -> bool:
        try:
            self.logger.info(f"Connecting to RTSP output: {OUT_URL}")

            self.out_container = av.open(
                OUT_URL,
                mode="w",
                format="rtsp",
                options={"rtsp_transport": RTSP_TRANSPORT},
                timeout=CONNECTION_TIMEOUT,
            )

            if metadata.get("has_video"):
                video_stream = self.out_container.add_stream(
                    VIDEO_CODEC,
                    rate=FPS,
                    options={"preset": VIDEO_PRESET, "tune": VIDEO_TUNE},
                )
                if isinstance(video_stream, VideoStream):
                    self.video_stream = video_stream
                    self.video_stream.width = metadata["video_width"]
                    self.video_stream.height = metadata["video_height"]
                    self.video_stream.pix_fmt = VIDEO_PIX_FMT

                self.logger.info(
                    f"Video stream configured: {metadata['video_width']}x{metadata['video_height']} @ {FPS}fps"
                )

            if metadata.get("has_audio"):
                codec_name = "libopus"
                self.audio_stream = self.out_container.add_stream(
                    codec_name, rate=48000
                )

                if isinstance(self.audio_stream, AudioStream):
                    channels = metadata.get("audio_channels", 2)
                    self.audio_stream.codec_context.layout = (
                        "stereo" if channels > 1 else "mono"
                    )
                    self.audio_stream.codec_context.sample_rate = 48000

                    input_rate = metadata.get("audio_rate", 48000)
                    if input_rate != 48000:
                        self.resampler = AudioResampler(
                            format="s16",
                            layout="stereo" if channels > 1 else "mono",
                            rate=48000,
                        )
                        self.logger.info(
                            f"Audio resampler configured: {input_rate}Hz -> 48kHz"
                        )

                    self.logger.info(
                        f"Audio stream configured: Opus @ 48kHz, {channels} channels"
                    )

            self.connection_state.set_output_connected(True)
            self.stream_metadata = metadata
            self.frames_written = 0
            self.audio_packets_written = 0

            return True

        except Exception as e:
            self.logger.error(f"Failed to connect to output: {e}")
            if self.out_container:
                try:
                    self.out_container.close()
                except Exception:
                    pass
                self.out_container = None
            return False

    def _disconnect(self):
        if self.video_stream and self.out_container:
            try:
                for packet in self.video_stream.encode():
                    self.out_container.mux(packet)
            except Exception:
                pass

        if self.out_container:
            try:
                self.out_container.close()
            except Exception:
                pass
            self.out_container = None

        self.video_stream = None
        self.audio_stream = None
        self.resampler = None
        self.connection_state.set_output_connected(False)

        # Clear output queues when disconnecting
        self.logger.debug("Clearing output queues after disconnect")
        self.video_queue.clear()
        if self.audio_queue:
            self.audio_queue.clear()
        if self.audio_processed_queue:
            self.audio_processed_queue.clear()

        self.logger.info(
            f"Output disconnected - wrote {self.frames_written} frames, "
            f"{self.audio_packets_written} audio packets"
        )

    def _process_video(self, video_data: ProcessedVideoData):
        if not self.video_stream or not self.out_container:
            return

        try:
            for packet in self.video_stream.encode(video_data.frame):
                self.out_container.mux(packet)

            self.frames_written += 1

            if self.frames_written % 100 == 0:
                self.logger.debug(f"Written {self.frames_written} frames to output")

        except Exception as e:
            self.logger.error(f"Error writing video frame: {e}")
            self._disconnect()

    def _process_raw_audio(self, audio_data: AudioData):
        if not self.audio_stream or not self.out_container:
            return

        try:
            frames_to_encode = [audio_data.frame]

            if self.resampler:
                resampled = self.resampler.resample(audio_data.frame)
                if isinstance(resampled, list):
                    frames_to_encode = resampled
                else:
                    frames_to_encode = [resampled]

            for frame in frames_to_encode:
                for packet in self.audio_stream.encode(frame):
                    self.out_container.mux(packet)

            self.audio_packets_written += 1

        except Exception as e:
            self.logger.error(f"Error writing audio: {e}")

    def _process_processed_audio(self, audio_data: ProcessedAudioData):
        if not self.audio_stream or not self.out_container:
            return

        try:
            for packet in self.audio_stream.encode(audio_data.frame):
                self.out_container.mux(packet)
            self.audio_packets_written += 1
        except Exception as e:
            self.logger.error(f"Error writing processed audio: {e}")

    def cleanup(self):
        self._disconnect()
        self.logger.info("Output muxer cleanup complete")
