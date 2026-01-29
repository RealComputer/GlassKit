import logging


def _disable_uvicorn_propagation() -> None:
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(logger_name)
        if uvicorn_logger.handlers:
            uvicorn_logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    uvicorn_logger = logging.getLogger("uvicorn")
    if uvicorn_logger.handlers:
        _disable_uvicorn_propagation()
        logger.handlers = list(uvicorn_logger.handlers)
        logger.setLevel(uvicorn_logger.level)
        logger.propagate = False
    return logger
