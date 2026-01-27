from pathlib import Path
import os


BASE_DIR = Path(__file__).parent.parent

IN_URL = os.getenv("FILTER_IN_URL", "rtmp://0.0.0.0:1935/live/stream")
OUT_URL = os.getenv("FILTER_OUT_URL", "rtsp://127.0.0.1:8554/filtered")
FPS = int(os.getenv("FILTER_FPS", "30"))

FACE_BLUR_KERNEL = (99, 99)
FACE_ANONYMIZATION_MODE = os.getenv(
    "FACE_ANONYMIZATION_MODE", "blur"
)  # "blur" or "solid_ellipse"
FACE_SCORE_THRESHOLD = float(os.getenv("FACE_SCORE_THRESHOLD", "0.6"))
FACE_NMS_THRESHOLD = float(os.getenv("FACE_NMS_THRESHOLD", "0.3"))
FACE_TOP_K = int(os.getenv("FACE_TOP_K", "500"))
FACE_MIN_CONFIDENCE = float(os.getenv("FACE_MIN_CONFIDENCE", "0.5"))

# Asymmetric face padding ratios for better coverage
FACE_PADDING_TOP = float(os.getenv("FACE_PADDING_TOP", "0.5"))  # More padding for hair
FACE_PADDING_BOTTOM = float(
    os.getenv("FACE_PADDING_BOTTOM", "0.15")
)  # Less padding for chin
FACE_PADDING_LEFT = float(os.getenv("FACE_PADDING_LEFT", "0.25"))
FACE_PADDING_RIGHT = float(os.getenv("FACE_PADDING_RIGHT", "0.25"))

HEAD_CAPTURE_PADDING_RATIO = float(
    os.getenv("HEAD_CAPTURE_PADDING_RATIO", "0.3")
)  # Larger padding for head captures
FACE_CACHE_DURATION_MS = float(os.getenv("FACE_CACHE_DURATION_MS", "100.0"))

MODEL_PATH = BASE_DIR / "face_detection_yunet_2023mar.onnx"

CONNECTION_TIMEOUT = (5.0, 1.0)

VIDEO_CODEC = os.getenv("VIDEO_CODEC", "libx264")
VIDEO_PRESET = os.getenv("VIDEO_PRESET", "veryfast")
VIDEO_TUNE = os.getenv("VIDEO_TUNE", "zerolatency")
VIDEO_PIX_FMT = os.getenv("VIDEO_PIX_FMT", "yuv420p")

RTSP_TRANSPORT = os.getenv("RTSP_TRANSPORT", "tcp")

VIDEO_QUEUE_SIZE = int(os.getenv("VIDEO_QUEUE_SIZE", "60"))
AUDIO_QUEUE_SIZE = int(os.getenv("AUDIO_QUEUE_SIZE", "200"))
VAD_QUEUE_SIZE = int(os.getenv("VAD_QUEUE_SIZE", "20"))
SPEECH_QUEUE_SIZE = int(os.getenv("SPEECH_QUEUE_SIZE", "20"))
OUTPUT_QUEUE_SIZE = int(os.getenv("OUTPUT_QUEUE_SIZE", "60"))

QUEUE_TIMEOUT = float(os.getenv("QUEUE_TIMEOUT", "0.1"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s"

THREAD_MONITOR_INTERVAL = float(os.getenv("THREAD_MONITOR_INTERVAL", "10.0"))
THREAD_HEALTH_TIMEOUT = float(os.getenv("THREAD_HEALTH_TIMEOUT", "120.0"))

ENABLE_METRICS = os.getenv("ENABLE_METRICS", "true").lower() == "true"
METRICS_PORT = int(os.getenv("METRICS_PORT", "8080"))

ENABLE_TRANSCRIPTION = os.getenv("ENABLE_TRANSCRIPTION", "true").lower() == "true"
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small.en")
WHISPER_THREADS = int(os.getenv("WHISPER_THREADS", "1"))

DISABLE_VIDEO_PROCESSING = (
    os.getenv("DISABLE_VIDEO_PROCESSING", "false").lower() == "true"
)

cpu_threads_env = os.getenv("CPU_THREADS")
if cpu_threads_env:
    CPU_THREADS = int(cpu_threads_env)
else:
    cpu_count = os.cpu_count()
    CPU_THREADS = max(4, cpu_count // 2) if cpu_count else 4
