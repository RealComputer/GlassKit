import signal
import threading
from typing import Callable, List, Optional
from types import FrameType
from misc.logging import get_logger


logger = get_logger(__name__)


class ShutdownHandler:
    def __init__(self):
        self._shutdown_event = threading.Event()
        self._cleanup_callbacks: List[Callable] = []
        self._lock = threading.Lock()
        self._original_handlers = {}
        self._shutdown_in_progress = False

    def register_signal_handlers(self):
        self._original_handlers[signal.SIGINT] = signal.signal(
            signal.SIGINT, self._signal_handler
        )
        self._original_handlers[signal.SIGTERM] = signal.signal(
            signal.SIGTERM, self._signal_handler
        )
        logger.info("Signal handlers registered for graceful shutdown")

    def restore_signal_handlers(self):
        for sig, handler in self._original_handlers.items():
            signal.signal(sig, handler)
        self._original_handlers.clear()

    def _signal_handler(self, signum: int, frame: Optional[FrameType]):
        signal_name = signal.Signals(signum).name
        logger.info(f"Received {signal_name}, initiating graceful shutdown...")
        self.initiate_shutdown()

    def initiate_shutdown(self):
        with self._lock:
            if self._shutdown_in_progress:
                logger.warning("Shutdown already in progress")
                return
            self._shutdown_in_progress = True

        self._shutdown_event.set()

        threading.Thread(target=self._execute_cleanup, daemon=False).start()

    def _execute_cleanup(self):
        logger.info("Starting cleanup procedures...")

        for callback in reversed(self._cleanup_callbacks):
            try:
                callback()
            except Exception as e:
                logger.error(f"Error during cleanup callback: {e}")

        logger.info("Cleanup completed")

    def register_cleanup(self, callback: Callable):
        with self._lock:
            self._cleanup_callbacks.append(callback)

    def is_shutdown_requested(self) -> bool:
        return self._shutdown_event.is_set()

    def wait_for_shutdown(self, timeout: Optional[float] = None) -> bool:
        return self._shutdown_event.wait(timeout)

    def reset(self):
        with self._lock:
            self._shutdown_event.clear()
            self._shutdown_in_progress = False


_shutdown_handler: Optional[ShutdownHandler] = None
_handler_lock = threading.Lock()


def get_shutdown_handler() -> ShutdownHandler:
    global _shutdown_handler
    if _shutdown_handler is None:
        with _handler_lock:
            if _shutdown_handler is None:
                _shutdown_handler = ShutdownHandler()
    return _shutdown_handler


def is_shutting_down() -> bool:
    handler = get_shutdown_handler()
    return handler.is_shutdown_requested()


def wait_for_shutdown(timeout: Optional[float] = None) -> bool:
    handler = get_shutdown_handler()
    return handler.wait_for_shutdown(timeout)


def register_cleanup(callback: Callable):
    handler = get_shutdown_handler()
    handler.register_cleanup(callback)
