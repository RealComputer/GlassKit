#!/usr/bin/env python3
"""
Real-time privacy filter service with multi-threaded pipeline.

RTMP input -> Face blur + Audio transcoding -> RTSP output
"""

import sys
from misc.logging import setup_logging
from misc.pipeline import Pipeline


def main():
    logger = setup_logging()

    logger.info("Privacy Filter Service Starting")

    pipeline = Pipeline()

    try:
        pipeline.start()
        pipeline.wait()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("Service shutdown complete")

    sys.exit(0)


if __name__ == "__main__":
    main()
