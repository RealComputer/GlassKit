import logging
import sys
from typing import Optional
from threading import Lock
from misc.config import LOG_LEVEL, LOG_FORMAT


_logger_lock = Lock()
_configured = False


def setup_logging(
    level: Optional[str] = None, format_str: Optional[str] = None
) -> logging.Logger:
    global _configured
    with _logger_lock:
        if not _configured:
            level = level or LOG_LEVEL
            format_str = format_str or LOG_FORMAT

            logging.basicConfig(
                level=getattr(logging, level.upper()),
                format=format_str,
                stream=sys.stdout,
                force=True,
            )

            logging.getLogger("av").setLevel(logging.WARNING)
            logging.getLogger("urllib3").setLevel(logging.WARNING)

            _configured = True

    return logging.getLogger()


def get_logger(name: str) -> logging.Logger:
    if not _configured:
        setup_logging()
    return logging.getLogger(name)


class ThreadLogger:
    def __init__(self, thread_name: str):
        self.logger = get_logger(f"thread.{thread_name}")

    def debug(self, msg: str, *args, **kwargs):
        self.logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        self.logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self.logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        self.logger.error(msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs):
        self.logger.critical(msg, *args, **kwargs)
