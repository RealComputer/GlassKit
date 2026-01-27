from dataclasses import dataclass
from typing import Optional, Union
from enum import Enum
import numpy as np
from av.video.frame import VideoFrame
from av.audio.frame import AudioFrame


class ThreadState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class QueueStrategy(Enum):
    BLOCK = "block"
    DROP_OLDEST = "drop_oldest"
    DROP_NEWEST = "drop_newest"


@dataclass
class VideoData:
    frame: VideoFrame
    timestamp: float
    sequence: int


@dataclass
class AudioData:
    frame: AudioFrame
    timestamp: float
    sequence: int


@dataclass
class TranscriptionData:
    audio: np.ndarray
    start_time: float
    end_time: float


@dataclass
class SpeechSegment:
    audio: np.ndarray
    start_time: float
    end_time: float
    sample_rate: int


@dataclass
class ProcessedVideoData:
    frame: VideoFrame
    timestamp: float
    sequence: int
    faces_detected: int = 0


@dataclass
class ProcessedAudioData:
    frame: AudioFrame
    timestamp: float
    sequence: int


@dataclass
class StreamMetrics:
    frames_processed: int = 0
    frames_dropped: int = 0
    audio_packets_processed: int = 0
    faces_detected_total: int = 0
    transcriptions_completed: int = 0
    average_fps: float = 0.0
    queue_depths: Optional[dict[str, int]] = None

    def __post_init__(self):
        if self.queue_depths is None:
            self.queue_depths = {}


FrameData = Union[VideoData, AudioData]
ProcessedData = Union[ProcessedVideoData, ProcessedAudioData]
