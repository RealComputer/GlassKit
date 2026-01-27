from typing import Optional, Tuple, Any
import cv2
import numpy as np
from numpy.typing import NDArray
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from misc.logging import get_logger
from misc.config import (
    MODEL_PATH,
    FACE_SCORE_THRESHOLD,
    FACE_NMS_THRESHOLD,
    FACE_TOP_K,
    HEAD_CAPTURE_PADDING_RATIO,
)
from shared.consent_file_utils import get_consent_filepath


logger = get_logger(__name__)


class ConsentCapture:
    @classmethod
    def save_head_image(
        cls, frame: NDArray[Any], speaker_name: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[NDArray[np.float32]]]:
        h, w = frame.shape[:2]

        detector: Any = cv2.FaceDetectorYN.create(
            model=str(MODEL_PATH),
            config="",
            input_size=(w, h),
            score_threshold=FACE_SCORE_THRESHOLD,
            nms_threshold=FACE_NMS_THRESHOLD,
            top_k=FACE_TOP_K,
        )

        _, faces = detector.detect(frame)

        if faces is None or len(faces) == 0:
            logger.warning("No faces detected in consent frame, skipping capture")
            return None, None

        largest_face_idx = 0
        largest_area = 0
        for i in range(len(faces)):
            x, y, face_w, face_h = faces[i][:4]
            area = face_w * face_h
            if area > largest_area:
                largest_area = area
                largest_face_idx = i

        face_coords = faces[largest_face_idx]
        x, y, face_w, face_h = face_coords[:4].astype(int)

        # Use larger padding for head capture to include whole head
        padding = int(min(face_w, face_h) * HEAD_CAPTURE_PADDING_RATIO)
        x1 = max(0, x - padding)
        y1 = max(0, y - padding)
        x2 = min(w, x + face_w + padding)
        y2 = min(h, y + face_h + padding)

        head_image = frame[y1:y2, x1:x2]

        # Use the utility function to get the filepath
        filepath = get_consent_filepath(speaker_name)
        success = cv2.imwrite(str(filepath), head_image, [cv2.IMWRITE_JPEG_QUALITY, 95])

        if not success:
            raise IOError(f"Failed to save head image to {filepath}")

        logger.info(
            f"Consent head image saved: {filepath} (face area: {face_w}x{face_h})"
        )
        return str(filepath), face_coords
