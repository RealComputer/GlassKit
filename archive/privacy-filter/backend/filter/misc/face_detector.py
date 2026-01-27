"""Optimized face detection and anonymization module for real-time video privacy.

This module provides high-performance face detection using YuNet neural network
with intelligent caching and frame resizing optimizations. Key features:

- YuNet-based face detection with configurable confidence thresholds
- Adaptive frame resizing for faster processing of high-resolution streams
- Face detection caching to reduce CPU usage (configurable cache duration)
- Gaussian blur anonymization with adjustable padding for natural appearance
- Thread-safe singleton pattern for global detector instance
- Comprehensive performance metrics and cache hit rate monitoring

The detector automatically handles different input resolutions and maintains
consistent detection quality while optimizing for real-time performance.
"""

import threading
import time
from typing import Any, Tuple, List, Dict
import numpy as np
from numpy.typing import NDArray
import cv2
from av.video.frame import VideoFrame

from misc.logging import get_logger
from misc.face_recognizer import get_face_recognizer
from misc.config import (
    MODEL_PATH,
    FACE_BLUR_KERNEL,
    FACE_ANONYMIZATION_MODE,
    FACE_SCORE_THRESHOLD,
    FACE_NMS_THRESHOLD,
    FACE_TOP_K,
    FACE_MIN_CONFIDENCE,
    FACE_PADDING_TOP,
    FACE_PADDING_BOTTOM,
    FACE_PADDING_LEFT,
    FACE_PADDING_RIGHT,
    FACE_CACHE_DURATION_MS,
)

# Detection optimization constants
TARGET_MAX_SIDE = 640  # Max side length for detection (balance speed/accuracy)
DEFAULT_INPUT_SIZE = (320, 320)  # YuNet default input size
STATS_LOG_INTERVAL_MS = 30000  # Log cache statistics every 30 seconds


def _resize_for_detection(bgr: NDArray[Any]) -> tuple[NDArray[Any], float]:
    """
    Resize frame for faster detection if it exceeds TARGET_MAX_SIDE.

    Args:
        bgr: Input BGR image array

    Returns:
        Tuple of (resized image, scale factor)
    """
    h, w = bgr.shape[:2]
    scale = 1.0

    # Only resize if the image is larger than target
    if max(h, w) > TARGET_MAX_SIDE:
        scale = TARGET_MAX_SIDE / max(h, w)
        new_w = int(w * scale)
        new_h = int(h * scale)
        bgr = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    return bgr, scale


class FaceDetector:
    """Face detector and blurring processor using YuNet."""

    def __init__(self) -> None:
        """Initialize the YuNet face detector with caching and optimization."""
        self.logger = get_logger(__name__)
        self._init_detector()
        self._init_cache()
        self._init_statistics()

    def _init_detector(self) -> None:
        """Initialize the YuNet face detection model."""
        # Type as Any since cv2.FaceDetectorYN is not fully typed
        self.detector: Any = cv2.FaceDetectorYN.create(
            model=str(MODEL_PATH),
            config="",
            input_size=DEFAULT_INPUT_SIZE,  # Will be adjusted per frame
            score_threshold=FACE_SCORE_THRESHOLD,
            nms_threshold=FACE_NMS_THRESHOLD,
            top_k=FACE_TOP_K,
            backend_id=cv2.dnn.DNN_BACKEND_OPENCV,
            target_id=cv2.dnn.DNN_TARGET_CPU,
        )
        # Track current input size to avoid unnecessary updates
        self.current_input_size: tuple[int, int] | None = None

    def _init_cache(self) -> None:
        """Initialize face detection caching system."""
        self.cached_faces: list[tuple[int, int, int, int]] | None = None
        self.cache_timestamp: float = 0
        self.cache_duration_ms: float = FACE_CACHE_DURATION_MS

    def _init_statistics(self) -> None:
        """Initialize performance monitoring statistics."""
        self.cache_hits: int = 0
        self.cache_misses: int = 0
        self.last_stats_log: float = 0

    def blur_faces_in_frame(self, frame: VideoFrame) -> tuple[VideoFrame, int]:
        """
        Detect and blur faces in a VideoFrame.

        Args:
            frame: Input video frame

        Returns:
            Tuple of (VideoFrame with faces blurred, number of faces blurred)
        """
        # Convert PyAV frame to NumPy array (BGR format)
        bgr = frame.to_ndarray(format="bgr24")
        h, w = bgr.shape[:2]

        # Get face rectangles (from cache or fresh detection)
        face_rectangles = self._get_face_rectangles(bgr, w, h)

        # Log statistics periodically
        self._log_statistics_if_needed()

        # If no faces detected, return original frame
        if not face_rectangles:
            return frame, 0

        # Apply blur to detected faces
        bgr_blurred = self._apply_blur_to_faces(bgr, face_rectangles)

        # Convert back to VideoFrame, preserving timing information
        return self._create_output_frame(bgr_blurred, frame), len(face_rectangles)

    def process_faces_with_recognition(
        self, frame: VideoFrame, enable_recognition: bool = True
    ) -> Tuple[VideoFrame, int, Dict[str, Any]]:
        """
        Detect faces and selectively blur based on consent recognition.

        Args:
            frame: Input video frame
            enable_recognition: Whether to use face recognition

        Returns:
            Tuple of (processed frame, total faces detected, recognition info)
        """
        bgr = frame.to_ndarray(format="bgr24")
        h, w = bgr.shape[:2]

        faces = self._detect_faces_raw(bgr, w, h)

        if faces is None or len(faces) == 0:
            return frame, 0, {}

        recognizer = get_face_recognizer() if enable_recognition else None
        blurred_count = 0
        recognized_faces: List[Dict[str, Any]] = []

        for i in range(len(faces)):
            face_coords = faces[i]
            x, y, face_w, face_h = face_coords[:4].astype(int)

            is_recognized = False
            name = None

            if recognizer and recognizer.get_consented_count() > 0:
                try:
                    encoding = recognizer.extract_feature(bgr, face_coords)
                    if encoding is not None:
                        is_recognized, name = recognizer.match_face(encoding)
                    else:
                        self.logger.debug(f"Could not extract encoding for face {i}")
                except Exception as e:
                    self.logger.debug(f"Face recognition failed for face {i}: {e}")

            if not is_recognized:
                rectangle = self._calculate_padded_bbox(x, y, face_w, face_h, w, h)
                self._anonymize_region(bgr, *rectangle)
                blurred_count += 1
            else:
                recognized_faces.append({"bbox": (x, y, face_w, face_h), "name": name})

                if name:
                    cv2.putText(
                        bgr,
                        name,
                        (x, max(y - 15, 25)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1.2,
                        (0, 255, 0),
                        3,
                        cv2.LINE_AA,
                    )

        recognition_info = {
            "total_faces": len(faces),
            "blurred_faces": blurred_count,
            "recognized_faces": recognized_faces,
        }

        return self._create_output_frame(bgr, frame), len(faces), recognition_info

    def _detect_faces_raw(
        self, bgr: NDArray[Any], width: int, height: int
    ) -> NDArray[np.float32] | None:
        """Get raw face detection results without caching."""
        return self._detect_faces(bgr, width, height)

    def _get_face_rectangles(
        self, bgr: NDArray[Any], width: int, height: int
    ) -> list[tuple[int, int, int, int]]:
        """Get face rectangles from cache or perform fresh detection."""
        current_time_ms = time.time() * 1000
        cache_age_ms = current_time_ms - self.cache_timestamp

        # Check if cache is valid
        if self._is_cache_valid(cache_age_ms):
            self.cache_hits += 1
            return self.cached_faces or []

        # Cache miss - perform face detection
        self.cache_misses += 1
        faces = self._detect_faces(bgr, width, height)

        # Update cache
        self.cached_faces = (
            self._extract_face_rectangles(faces, width, height)
            if faces is not None
            else []
        )
        self.cache_timestamp = current_time_ms

        return self.cached_faces

    def _is_cache_valid(self, cache_age_ms: float) -> bool:
        """Check if cached face detection results are still valid."""
        return self.cached_faces is not None and cache_age_ms <= self.cache_duration_ms

    def _detect_faces(
        self, bgr: NDArray[Any], width: int, height: int
    ) -> NDArray[np.float32] | None:
        """Perform face detection on the given image."""
        # Resize frame for faster detection if needed
        bgr_small, scale = _resize_for_detection(bgr)
        h_small, w_small = bgr_small.shape[:2]

        # Log resize optimization info on first detection or size change
        if scale != 1.0 and self.current_input_size != (w_small, h_small):
            self.logger.debug(
                f"Resizing frame from {width}x{height} to {w_small}x{h_small} "
                f"(scale: {scale:.2f}) for faster detection"
            )

        # Update detector input size if dimensions changed
        self._update_detector_size(w_small, h_small)

        # Detect faces on resized image
        _, faces_result = self.detector.detect(bgr_small)
        faces: NDArray[np.float32] | None = faces_result

        # Scale coordinates back to original size if we resized
        if faces is not None and scale != 1.0:
            faces[:, :4] /= scale

        return faces

    def _update_detector_size(self, width: int, height: int) -> None:
        """Update detector input size if it has changed."""
        new_size = (width, height)
        if self.current_input_size != new_size:
            self.detector.setInputSize(new_size)
            self.current_input_size = new_size

    def _log_statistics_if_needed(self) -> None:
        """Log cache statistics periodically."""
        current_time_ms = time.time() * 1000
        if current_time_ms - self.last_stats_log > STATS_LOG_INTERVAL_MS:
            total = self.cache_hits + self.cache_misses
            if total > 0:
                hit_rate = (self.cache_hits / total) * 100
                self.logger.info(
                    f"Face detection cache stats: {self.cache_hits} hits, "
                    f"{self.cache_misses} misses, {hit_rate:.1f}% hit rate"
                )
            self.last_stats_log = current_time_ms

    def _create_output_frame(
        self, bgr: NDArray[Any], original_frame: VideoFrame
    ) -> VideoFrame:
        """Create output VideoFrame with preserved timing information."""
        new_frame = VideoFrame.from_ndarray(bgr, format="bgr24")
        new_frame.pts = original_frame.pts
        new_frame.time_base = original_frame.time_base
        return new_frame

    def _extract_face_rectangles(
        self, faces: NDArray[np.float32], width: int, height: int
    ) -> list[tuple[int, int, int, int]]:
        """
        Extract and validate face rectangles from detection results.

        Args:
            faces: Array of detected faces from YuNet
            width: Image width
            height: Image height

        Returns:
            List of (x1, y1, x2, y2) face rectangles with padding
        """
        rectangles = []
        for i in range(len(faces)):
            rectangle = self._process_single_face(faces[i], width, height)
            if rectangle:
                rectangles.append(rectangle)
        return rectangles

    def _process_single_face(
        self, face_row: NDArray[np.float32], width: int, height: int
    ) -> tuple[int, int, int, int] | None:
        """Process a single face detection result into a padded rectangle."""
        x, y, face_w, face_h, score = map(float, face_row[:5])

        # Skip low confidence detections
        if score < FACE_MIN_CONFIDENCE:
            return None

        # Calculate padded bounding box
        return self._calculate_padded_bbox(x, y, face_w, face_h, width, height)

    def _calculate_padded_bbox(
        self, x: float, y: float, w: float, h: float, img_width: int, img_height: int
    ) -> tuple[int, int, int, int]:
        """Calculate padded bounding box coordinates with asymmetric padding."""
        # Use face dimensions as base for calculating padding
        base_size = min(w, h)

        # Apply asymmetric padding
        padding_top = int(base_size * FACE_PADDING_TOP)
        padding_bottom = int(base_size * FACE_PADDING_BOTTOM)
        padding_left = int(base_size * FACE_PADDING_LEFT)
        padding_right = int(base_size * FACE_PADDING_RIGHT)

        # Calculate padded coordinates with boundary checks
        x1 = int(max(0, x - padding_left))
        y1 = int(max(0, y - padding_top))
        x2 = int(min(img_width - 1, x + w + padding_right))
        y2 = int(min(img_height - 1, y + h + padding_bottom))

        return (x1, y1, x2, y2)

    def _apply_blur_to_faces(
        self, bgr: NDArray[Any], face_rectangles: list[tuple[int, int, int, int]]
    ) -> NDArray[Any]:
        """
        Apply anonymization (blur or solid ellipse) to detected face regions.

        Args:
            bgr: BGR image array
            face_rectangles: List of (x1, y1, x2, y2) face rectangles

        Returns:
            Image with faces anonymized
        """
        for x1, y1, x2, y2 in face_rectangles:
            self._anonymize_region(bgr, x1, y1, x2, y2)
        return bgr

    def _anonymize_region(
        self, bgr: NDArray[Any], x1: int, y1: int, x2: int, y2: int
    ) -> None:
        """Apply anonymization (blur or solid ellipse) to a specific region."""
        if FACE_ANONYMIZATION_MODE == "solid_ellipse":
            self._fill_solid_ellipse(bgr, x1, y1, x2, y2)
        else:  # default to blur
            self._blur_region(bgr, x1, y1, x2, y2)

    def _blur_region(
        self, bgr: NDArray[Any], x1: int, y1: int, x2: int, y2: int
    ) -> None:
        """Apply Gaussian blur to a specific region of the image."""
        roi = bgr[y1:y2, x1:x2]
        if roi.size > 0:
            roi_blurred = cv2.GaussianBlur(roi, FACE_BLUR_KERNEL, 0)
            bgr[y1:y2, x1:x2] = roi_blurred

    def _fill_solid_ellipse(
        self, bgr: NDArray[Any], x1: int, y1: int, x2: int, y2: int
    ) -> None:
        """Fill a solid opaque ellipse over the face region."""
        # Calculate center of the region
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2

        # Calculate ellipse axes based on face dimensions
        width = x2 - x1
        height = y2 - y1

        # Use half dimensions for ellipse axes (axes are radii, not diameters)
        axes = (width // 2, height // 2)

        # Draw filled solid ellipse (opaque mask)
        cv2.ellipse(bgr, (center_x, center_y), axes, 0, 0, 360, (0, 0, 0), -1)


# Global face detector instance
_face_detector: FaceDetector | None = None
_face_detector_lock = threading.Lock()


def get_face_detector() -> FaceDetector:
    """
    Get or create the global face detector instance (thread-safe).

    Returns:
        FaceDetector instance
    """
    global _face_detector
    if _face_detector is None:
        with _face_detector_lock:
            # Double-check pattern for thread safety
            if _face_detector is None:
                _face_detector = FaceDetector()
    return _face_detector
