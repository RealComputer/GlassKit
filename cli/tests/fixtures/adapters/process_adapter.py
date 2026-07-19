from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

_write_lock = threading.Lock()
_active_lock = threading.Lock()
_active: dict[int, tuple[threading.Thread, threading.Event]] = {}
_adapter_config: dict[str, Any] = {}
_initialize_config: dict[str, Any] = {}


def _send(message: dict[str, Any]) -> None:
    encoded = json.dumps(message, allow_nan=False, separators=(",", ":"))
    with _write_lock:
        sys.stdout.write(encoded + "\n")
        sys.stdout.flush()


def _append_lifecycle(event: str) -> None:
    if path := _adapter_config.get("lifecyclePath"):
        with Path(path).open("a", encoding="utf-8") as output:
            output.write(event + "\n")


def _error(request_id: int, error: BaseException) -> None:
    _send(
        {
            "id": request_id,
            "error": {"message": str(error), "stack": "fixture adapter stack"},
        }
    )


def _observation(sample: dict[str, Any], target: dict[str, Any]) -> Any:
    image = sample["image"]
    png = base64.b64decode(image["dataBase64"], validate=True)
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("sample image is not a PNG")
    if _adapter_config.get("booleanByTimestamp"):
        return sample["timestampS"] >= 1.0
    return {
        "target": target["id"],
        "targetIndex": target["index"],
        "targetLabel": target["label"],
        "targetConfig": target["config"],
        "timestampS": sample["timestampS"],
        "frameIndex": sample["frameIndex"],
        "sampleIndex": sample["sampleIndex"],
        "videoPath": sample["videoPath"],
        "caseName": sample["caseName"],
        "image": {
            "mimeType": image["mimeType"],
            "width": image["width"],
            "height": image["height"],
            "byteLength": len(png),
        },
        "initializeConfig": _initialize_config,
    }


def _evaluate(request: dict[str, Any], cancelled: threading.Event) -> None:
    request_id = request["id"]
    try:
        params = request["params"]
        if _adapter_config.get("exitDuringEvaluate"):
            sys.stderr.write("fixture process exited during evaluate\n")
            sys.stderr.flush()
            os._exit(7)
        if _adapter_config.get("exitWithInheritedPipes"):
            subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"],
            )
            sys.stderr.write("fixture leader exited with inherited pipes\n")
            sys.stderr.flush()
            os._exit(9)
        if _adapter_config.get("invalidStdout"):
            sys.stdout.write("this log accidentally used stdout\n")
            sys.stdout.flush()
            return
        delay = float(_adapter_config.get("delayS", 0))
        if _adapter_config.get("reverseDelay"):
            delay *= 4 - params["sample"]["sampleIndex"]
        deadline = time.monotonic() + delay
        while time.monotonic() < deadline:
            if cancelled.wait(timeout=min(0.01, deadline - time.monotonic())):
                raise RuntimeError("evaluation cancelled")
        if cancelled.is_set():
            raise RuntimeError("evaluation cancelled")
        if "failMessage" in _adapter_config:
            raise RuntimeError(str(_adapter_config["failMessage"]))
        if request["method"] == "evaluate":
            result: Any = _observation(params["sample"], params["target"])
        else:
            result = [
                _observation(sample, params["target"]) for sample in params["samples"]
            ]
        _send({"id": request_id, "result": result})
    except BaseException as error:
        _error(request_id, error)
    finally:
        with _active_lock:
            _active.pop(request_id, None)


def _start_evaluation(request: dict[str, Any]) -> None:
    request_id = request["id"]
    cancelled = threading.Event()
    thread = threading.Thread(target=_evaluate, args=(request, cancelled))
    with _active_lock:
        _active[request_id] = (thread, cancelled)
    thread.start()


def _cancel(request_id: int) -> None:
    with _active_lock:
        active = _active.get(request_id)
    if active is not None:
        active[1].set()


def _close(request_id: int) -> None:
    if _adapter_config.get("hangOnClose"):
        time.sleep(30)
    while True:
        with _active_lock:
            threads = [thread for thread, _ in _active.values()]
        if not threads:
            break
        for thread in threads:
            thread.join()
    _append_lifecycle("close")
    if _adapter_config.get("inheritPipesAfterClose"):
        subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
        )
    _send({"id": request_id, "result": None})
    if _adapter_config.get("invalidStdoutAfterClose"):
        sys.stdout.write("late stdout corruption\n")
        sys.stdout.flush()


def main() -> None:
    global _adapter_config, _initialize_config

    for raw_line in sys.stdin:
        request = json.loads(raw_line)
        method = request["method"]
        if method == "initialize":
            params = request["params"]
            _initialize_config = params["config"]
            _adapter_config = dict(_initialize_config["config"])
            if message := _adapter_config.get("stderrMessage"):
                sys.stderr.write(str(message) + "\n")
                sys.stderr.flush()
            if _adapter_config.get("exitWithInheritedPipesOnInitialize"):
                subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                )
                sys.stderr.write("fixture leader exited during initialize\n")
                sys.stderr.flush()
                os._exit(8)
            _append_lifecycle("initialize")
            strategy = _adapter_config.get("strategy", "individual")
            protocol_version = (
                999
                if _adapter_config.get("invalidProtocolVersion")
                else params["protocolVersion"]
            )
            _send(
                {
                    "id": request["id"],
                    "result": {
                        "protocolVersion": protocol_version,
                        "capabilities": {
                            "evaluate": strategy in {"individual", "both"},
                            "evaluateMany": strategy in {"batch", "both"},
                        },
                    },
                }
            )
        elif method in {"evaluate", "evaluateMany"}:
            _start_evaluation(request)
        elif method == "cancel":
            _cancel(request["params"]["id"])
        elif method == "close":
            _close(request["id"])
            return
        else:
            _error(request["id"], RuntimeError(f"unknown method: {method}"))


if __name__ == "__main__":
    main()
