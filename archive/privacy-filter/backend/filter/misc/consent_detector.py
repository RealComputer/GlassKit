import os
import sys
import json
from pathlib import Path
from typing import TypedDict
from llama_cpp import Llama, llama_log_set
from misc.logging import get_logger
from ctypes import CFUNCTYPE, c_int, c_char_p, c_void_p

# Define the C callback type: (level, text, user_data) -> None
LOG_CB = CFUNCTYPE(None, c_int, c_char_p, c_void_p)


# Keep a global reference so it isn't GC'd
def _log_sink(_level, _text, _user_data):
    # swallow everything; or forward to Python logging if you want
    return None


_log_cb = LOG_CB(_log_sink)

llama_log_set(_log_cb, c_void_p())


class ConsentResult(TypedDict):
    consent: bool
    speaker: str | None


class ConsentDetector:
    def __init__(self, model_path: str | None = None):
        self.logger = get_logger(self.__class__.__name__)
        if model_path is None:
            BASE_DIR = Path(__file__).parent.parent
            self.model_path = str(BASE_DIR / "Phi-3.1-mini-4k-instruct-Q4_K_M.gguf")
        else:
            self.model_path = model_path
        self.llm: Llama | None = None
        self._initialize_model()

    def _initialize_model(self):
        if not os.path.exists(self.model_path):
            self.logger.error(f"Model file not found: {self.model_path}")
            return

        try:
            self.logger.info(f"Loading LLM model from {self.model_path}")
            self.llm = Llama(
                model_path=self.model_path,
                n_gpu_layers=-1,
                verbose=False,
            )

            self.logger.info("LLM model loaded successfully")
        except Exception as e:
            self.logger.error(f"Failed to load LLM model: {e}")
            self.llm = None

    def detect_consent(self, transcript_text: str) -> ConsentResult:
        """
        Detect consent to be recorded and extract individual's name from transcript.

        Args:
            transcript_text: English transcript (few sentences)

        Returns:
            {
                "consent": bool,
                "speaker": str or None
            }
        """
        if not self.llm:
            return {"consent": False, "speaker": None}

        if not transcript_text or len(transcript_text.strip()) < 3:
            return {"consent": False, "speaker": None}

        try:
            system_prompt = """Check if the transcript (may contain errors) includes explicit consent to recording. Extract the consenting person's name if mentioned, or return UNKNOWN. Use the latest matching phrase, such as:

- I consent to be recorded
- You can record me
- My name is AAA. I agree to be on camera.
- I'm BBB. You have my permission to record."""

            user_prompt = f"Transcript:\n{transcript_text}"

            response = self.llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={
                    "type": "json_object",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "consent": {"type": "boolean"},
                            "speaker": {"type": ["string"]},
                        },
                        "required": ["consent", "speaker"],
                        "additionalProperties": False,
                    },
                },
                temperature=0.1,
                max_tokens=256,
            )

            result_json = "{}"
            if isinstance(response, dict):
                result_json = (
                    response.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "{}")
                    or "{}"
                )

            self.logger.debug(f"Raw LLM response: {result_json}")
            result = json.loads(result_json)

            if result.get("speaker") == "UNKNOWN":
                result["speaker"] = None

            if result.get("consent"):
                self.logger.info(
                    f"[CONSENT DETECTED] Name: {result.get('speaker', 'Unknown')}"
                )
            else:
                self.logger.debug("No consent detected in transcript")

            return result

        except Exception as e:
            self.logger.error(f"Error detecting consent: {e}")
            return {"consent": False, "speaker": None}

    def __del__(self):
        self.llm = None


_consent_detector: ConsentDetector | None = None


def get_consent_detector() -> ConsentDetector | None:
    """Get singleton instance of ConsentDetector."""
    global _consent_detector
    if _consent_detector is None:
        try:
            _consent_detector = ConsentDetector()
        except Exception:
            return None
    return _consent_detector


if __name__ == "__main__":
    import sys
    import time

    transcript = sys.argv[1] if len(sys.argv) > 1 else ""
    detector = ConsentDetector()

    start_time = time.time()
    output = detector.detect_consent(transcript)
    elapsed_time = time.time() - start_time

    print(f"Result: {output}")
    print(f"Time taken: {elapsed_time:.3f} seconds")
