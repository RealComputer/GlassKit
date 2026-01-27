import queue
import threading
from typing import Generic, TypeVar, Optional
from collections import deque
from misc.types import QueueStrategy
from misc.logging import get_logger


T = TypeVar("T")
logger = get_logger(__name__)


class BoundedQueue(Generic[T]):
    def __init__(
        self,
        maxsize: int,
        strategy: QueueStrategy = QueueStrategy.BLOCK,
        name: str = "unnamed",
    ):
        self.maxsize = maxsize
        self.strategy = strategy
        self.name = name
        self._queue: queue.Queue[T] = queue.Queue(maxsize=maxsize)
        self._dropped_count = 0
        self._lock = threading.Lock()

    def put(self, item: T, timeout: Optional[float] = None) -> bool:
        if self.strategy == QueueStrategy.BLOCK:
            try:
                self._queue.put(item, timeout=timeout)
                return True
            except queue.Full:
                logger.warning(f"Queue {self.name} is full, blocking failed")
                return False

        elif self.strategy == QueueStrategy.DROP_NEWEST:
            try:
                self._queue.put_nowait(item)
                return True
            except queue.Full:
                with self._lock:
                    self._dropped_count += 1
                if self._dropped_count % 1000 == 1:
                    logger.warning(
                        f"Queue {self.name} dropped {self._dropped_count} items (newest)"
                    )
                return False

        elif self.strategy == QueueStrategy.DROP_OLDEST:
            with self._lock:
                try:
                    self._queue.put_nowait(item)
                    return True
                except queue.Full:
                    try:
                        self._queue.get_nowait()
                        self._dropped_count += 1
                        self._queue.put_nowait(item)
                        if self._dropped_count == 1 or self._dropped_count % 1000 == 0:
                            logger.warning(
                                f"Queue {self.name} dropped {self._dropped_count} items (oldest)"
                            )
                        return True
                    except (queue.Empty, queue.Full):
                        return False

        return False

    def get(self, timeout: Optional[float] = None) -> Optional[T]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_nowait(self) -> Optional[T]:
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def qsize(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()

    def full(self) -> bool:
        return self._queue.full()

    def get_dropped_count(self) -> int:
        with self._lock:
            return self._dropped_count

    def clear(self):
        with self._lock:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break


class RingBuffer:
    def __init__(self, maxsize: int):
        self.maxsize = maxsize
        self._buffer = deque(maxlen=maxsize)
        self._lock = threading.Lock()

    def append(self, data: bytes):
        with self._lock:
            self._buffer.append(data)

    def extend(self, data: bytes):
        with self._lock:
            self._buffer.extend(data)

    def get_all(self) -> bytes:
        with self._lock:
            result = b"".join(self._buffer)
            self._buffer.clear()
            return result

    def get_bytes(self, n: int) -> Optional[bytes]:
        with self._lock:
            if len(self._buffer) < n:
                return None
            result = b""
            for _ in range(n):
                if self._buffer:
                    result += self._buffer.popleft()
            return result

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)

    def clear(self):
        with self._lock:
            self._buffer.clear()
