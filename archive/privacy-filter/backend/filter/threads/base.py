import threading
import time
from abc import ABC, abstractmethod
from typing import Optional
from misc.types import ThreadState
from misc.state import ThreadStateManager
from misc.logging import ThreadLogger
from misc.shutdown import is_shutting_down
from misc.metrics import get_metrics_collector


class BaseThread(ABC, threading.Thread):
    def __init__(
        self,
        name: str,
        state_manager: ThreadStateManager,
        heartbeat_interval: float = 1.0,
    ):
        super().__init__(name=name, daemon=False)
        self.state_manager = state_manager
        self.logger = ThreadLogger(name)
        self.heartbeat_interval = heartbeat_interval
        self._last_heartbeat = 0.0
        self._stop_event = threading.Event()
        self.metrics = get_metrics_collector()

    def run(self):
        self.state_manager.register_thread(self.name)
        self.state_manager.update_state(self.name, ThreadState.RUNNING)
        self.logger.info(f"Thread {self.name} started")

        try:
            self.setup()

            while not self.should_stop():
                self._heartbeat()

                try:
                    if not self.process_iteration():
                        time.sleep(0.001)
                except Exception as e:
                    self.logger.error(f"Error in process iteration: {e}")
                    if self.should_stop():
                        break
                    time.sleep(0.1)

        except Exception as e:
            self.logger.error(f"Fatal error in thread: {e}")
            self.state_manager.update_state(self.name, ThreadState.ERROR)
        finally:
            self.cleanup()
            self.state_manager.update_state(self.name, ThreadState.STOPPED)
            self.state_manager.unregister_thread(self.name)
            self.logger.info(f"Thread {self.name} stopped")

    def _heartbeat(self):
        current_time = time.time()
        if current_time - self._last_heartbeat >= self.heartbeat_interval:
            self.state_manager.heartbeat(self.name)
            self._last_heartbeat = current_time

    def should_stop(self) -> bool:
        return self._stop_event.is_set() or is_shutting_down()

    def stop(self):
        self.logger.info(f"Stop requested for thread {self.name}")
        self.state_manager.update_state(self.name, ThreadState.STOPPING)
        self._stop_event.set()

    def wait_stop(self, timeout: Optional[float] = None) -> bool:
        return self._stop_event.wait(timeout)

    @abstractmethod
    def setup(self):
        pass

    @abstractmethod
    def process_iteration(self) -> bool:
        pass

    @abstractmethod
    def cleanup(self):
        pass
