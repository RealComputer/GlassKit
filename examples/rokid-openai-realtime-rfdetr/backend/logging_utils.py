import logging


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    uvicorn_logger = logging.getLogger("uvicorn")
    if uvicorn_logger.handlers:
        logger.handlers = list(uvicorn_logger.handlers)
        logger.setLevel(uvicorn_logger.level)
        logger.propagate = False
    return logger
