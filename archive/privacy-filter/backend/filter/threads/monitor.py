import time
from typing import Dict, List, Optional
from threads.base import BaseThread
from misc.state import ThreadStateManager
from misc.types import ThreadState
from misc.config import THREAD_MONITOR_INTERVAL, THREAD_HEALTH_TIMEOUT
from misc.metrics import get_metrics_collector
from misc.queues import BoundedQueue


class HealthMonitorThread(BaseThread):
    def __init__(
        self,
        state_manager: ThreadStateManager,
        queues: Optional[Dict[str, BoundedQueue]] = None,
    ):
        super().__init__(
            name="HealthMonitor",
            state_manager=state_manager,
            heartbeat_interval=THREAD_MONITOR_INTERVAL,
        )
        self.queues = queues or {}
        self.unhealthy_threads: List[str] = []
        self.last_check_time = 0.0

    def setup(self):
        self.logger.info("Health monitor initialized")
        self.last_check_time = time.time()

    def process_iteration(self) -> bool:
        current_time = time.time()

        if current_time - self.last_check_time < THREAD_MONITOR_INTERVAL:
            return False

        self.last_check_time = current_time

        self._check_thread_health()
        self._update_queue_metrics()
        self._log_system_status()

        return True

    def _check_thread_health(self):
        all_states = self.state_manager.get_all_states()
        newly_unhealthy = []
        recovered = []

        for thread_name, state in all_states.items():
            if thread_name == self.name:
                continue

            is_healthy = self.state_manager.is_healthy(
                thread_name, THREAD_HEALTH_TIMEOUT
            )

            if not is_healthy and thread_name not in self.unhealthy_threads:
                newly_unhealthy.append(thread_name)
                self.unhealthy_threads.append(thread_name)
            elif is_healthy and thread_name in self.unhealthy_threads:
                recovered.append(thread_name)
                self.unhealthy_threads.remove(thread_name)

        for thread_name in newly_unhealthy:
            self.logger.warning(f"Thread {thread_name} is unhealthy")

        for thread_name in recovered:
            self.logger.info(f"Thread {thread_name} recovered")

        for thread_name, state in all_states.items():
            if state == ThreadState.ERROR:
                self.logger.critical(f"Thread {thread_name} is in ERROR state")

    def _update_queue_metrics(self):
        metrics = get_metrics_collector()

        for queue_name, queue in self.queues.items():
            depth = queue.qsize()
            metrics.update_queue_depth(queue_name, depth)

            if queue.full():
                self.logger.warning(
                    f"Queue {queue_name} is full ({depth}/{queue.maxsize})"
                )

            dropped = queue.get_dropped_count()
            if dropped > 0 and dropped % 10000 == 0:
                self.logger.info(
                    f"Queue {queue_name} has dropped {dropped} items total"
                )

    def _log_system_status(self):
        metrics = get_metrics_collector()

        if time.time() % 60 < THREAD_MONITOR_INTERVAL:
            metrics.log_summary()

            all_states = self.state_manager.get_all_states()
            active_threads = [
                f"{name}:{state.value}"
                for name, state in all_states.items()
                if state == ThreadState.RUNNING
            ]

            if active_threads:
                self.logger.info(f"Active threads: {', '.join(active_threads)}")

            if self.unhealthy_threads:
                self.logger.warning(
                    f"Unhealthy threads: {', '.join(self.unhealthy_threads)}"
                )

    def cleanup(self):
        self.logger.info("Health monitor shutting down")

        final_states = self.state_manager.get_all_states()
        for thread_name, state in final_states.items():
            if thread_name != self.name and state == ThreadState.RUNNING:
                self.logger.warning(
                    f"Thread {thread_name} still running during shutdown"
                )
