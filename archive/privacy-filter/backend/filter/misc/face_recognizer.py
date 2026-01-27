import threading
from typing import Any, Optional, Tuple, List
from pathlib import Path
import numpy as np
from numpy.typing import NDArray
import face_recognition

from misc.logging import get_logger

# face_recognition library uses 0.6 as default tolerance
# Lower values make face recognition more strict
FACE_DISTANCE_THRESHOLD = 0.5

logger = get_logger(__name__)


class FaceRecognizer:
    def __init__(self) -> None:
        self.logger = get_logger(__name__)
        self._lock = threading.Lock()
        self._init_database()
        self.logger.info("Face recognizer initialized with face_recognition library")

    def _init_database(self) -> None:
        # Flat list of (file_path, name, encoding) tuples
        # face_recognition uses 128-dimensional encodings
        self.consented_faces: List[Tuple[Path, str, NDArray[np.float64]]] = []
        self.logger.info("Consented faces database initialized")

    def extract_feature(
        self, face_img: NDArray[Any], face_coords: NDArray[np.float32]
    ) -> Optional[NDArray[np.float64]]:
        """Extract face encoding from image using face_recognition library.

        Args:
            face_img: BGR image containing the face
            face_coords: Face coordinates from YuNet detector [x, y, w, h, ...]

        Returns:
            128-dimensional face encoding or None if extraction fails
        """
        try:
            # Convert BGR to RGB
            rgb_img = face_img[:, :, ::-1].copy()

            # Ensure the image is in the right format
            if rgb_img.dtype != np.uint8:
                rgb_img = rgb_img.astype(np.uint8)

            # Convert YuNet bbox to face_recognition format
            # YuNet gives [x, y, width, height, ...]
            # face_recognition expects [(top, right, bottom, left)]
            x, y, w, h = face_coords[:4].astype(int)

            # Add some padding to the bounding box
            img_h, img_w = rgb_img.shape[:2]
            padding = int(min(w, h) * 0.1)  # 10% padding

            top = max(0, y - padding)
            right = min(img_w, x + w + padding)
            bottom = min(img_h, y + h + padding)
            left = max(0, x - padding)

            # Ensure valid bounding box
            if right <= left or bottom <= top:
                self.logger.warning(
                    f"Invalid bbox: top={top}, right={right}, bottom={bottom}, left={left}"
                )
                return None

            # Get face encoding for the specific location
            # Pass the full image and the known face location
            face_location = [(top, right, bottom, left)]

            # Try to get encoding with the known face location
            # num_jitters=1 for faster processing (default is 1)
            encodings = face_recognition.face_encodings(
                rgb_img,
                known_face_locations=face_location,
                num_jitters=1,
                model="small",
            )

            if encodings:
                return encodings[0]
            else:
                # If that fails, try auto-detection on cropped region as fallback
                face_crop = rgb_img[top:bottom, left:right]
                if face_crop.size > 0:
                    encodings = face_recognition.face_encodings(
                        face_crop, num_jitters=1, model="small"
                    )
                    if encodings:
                        self.logger.debug("Got encoding from cropped region fallback")
                        return encodings[0]

                self.logger.debug(
                    f"No face encoding extracted for bbox ({left},{top},{right},{bottom})"
                )
                return None

        except Exception as e:
            self.logger.error(f"Failed to extract face encoding: {e}")
            return None

    def add_consented_face(
        self, name: str, encoding: NDArray[np.float64], file_path: Path
    ) -> None:
        with self._lock:
            # Normalize name to lowercase for consistency
            name_lower = name.lower()
            # Check if this file already exists and remove it first
            self.consented_faces = [
                entry for entry in self.consented_faces if entry[0] != file_path
            ]
            # Add the new entry
            self.consented_faces.append((file_path, name_lower, encoding))
            self.logger.info(
                f"Added consented face for: {name_lower} from {file_path.name} (total faces: {len(self.consented_faces)})"
            )

    def remove_consented_face_by_file(self, file_path: Path) -> None:
        """Remove a specific face feature by file path."""
        with self._lock:
            original_count = len(self.consented_faces)
            self.consented_faces = [
                entry for entry in self.consented_faces if entry[0] != file_path
            ]
            removed_count = original_count - len(self.consented_faces)

            if removed_count > 0:
                self.logger.info(
                    f"Removed consent face from {file_path.name} (remaining: {len(self.consented_faces)})"
                )

    def match_face(self, encoding: NDArray[np.float64]) -> Tuple[bool, Optional[str]]:
        """Match a face encoding against the database of consented faces.

        Args:
            encoding: 128-dimensional face encoding to match

        Returns:
            Tuple of (is_recognized, name or None)
        """
        with self._lock:
            if not self.consented_faces:
                return False, None

            # Extract known encodings and names
            known_encodings = [entry[2] for entry in self.consented_faces]
            known_names = [entry[1] for entry in self.consented_faces]

            # Calculate distances to all known faces
            distances = face_recognition.face_distance(known_encodings, encoding)

            # Find the best match
            if len(distances) > 0:
                best_match_index = np.argmin(distances)
                best_distance = distances[best_match_index]

                # Check if the best match is within threshold
                if best_distance <= FACE_DISTANCE_THRESHOLD:
                    return True, known_names[best_match_index]

            return False, None

    def get_consented_count(self) -> int:
        """Get the total number of consented face entries."""
        with self._lock:
            return len(self.consented_faces)

    def get_unique_consented_count(self) -> int:
        """Get the number of unique individuals with consent."""
        with self._lock:
            unique_names = set(entry[1] for entry in self.consented_faces)
            return len(unique_names)

    def clear_database(self) -> None:
        with self._lock:
            self.consented_faces.clear()
            self.logger.info("Cleared consented faces database")


_face_recognizer: Optional[FaceRecognizer] = None
_face_recognizer_lock = threading.Lock()


def get_face_recognizer() -> FaceRecognizer:
    global _face_recognizer
    if _face_recognizer is None:
        with _face_recognizer_lock:
            if _face_recognizer is None:
                _face_recognizer = FaceRecognizer()
    return _face_recognizer
