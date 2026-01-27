"""Utilities for handling consent capture file naming conventions.

This module provides centralized handling of consent file naming to ensure
consistency across all components that interact with consent_captures/ files.

File naming convention: YYYYMMDDHHMMSS_name.jpg
- First 14 characters: timestamp in YYYYMMDDHHMMSS format
- Character 15: underscore separator
- Remaining characters before .jpg: person's name (lowercase, alphanumeric + underscores)
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
CONSENT_DIR = BASE_DIR / "filter" / "consent_captures"
TIMESTAMP_LENGTH = 14
FILE_EXTENSION = ".jpg"
MIN_FILENAME_LENGTH = 19  # 14 (timestamp) + 1 (_) + 1 (min name) + 4 (.jpg)


def ensure_consent_dir_exists() -> Path:
    """Ensure the consent captures directory exists."""
    CONSENT_DIR.mkdir(parents=True, exist_ok=True)
    return CONSENT_DIR


def sanitize_name(name: Optional[str]) -> str:
    """Sanitize a name for use in filename.

    Args:
        name: The name to sanitize (can be None)

    Returns:
        Sanitized name suitable for filename (lowercase, alphanumeric + underscores)
    """
    if not name:
        return "unknown"

    # Convert to lowercase and replace spaces with underscores
    safe_name = "".join(c if c.isalnum() or c == "_" else "_" for c in name.lower())
    # Remove leading/trailing underscores and collapse multiple underscores
    safe_name = "_".join(part for part in safe_name.split("_") if part)

    return safe_name or "unknown"


def create_consent_filename(
    name: Optional[str], timestamp: Optional[datetime] = None
) -> str:
    """Create a consent capture filename following the standard convention.

    Args:
        name: The person's name (will be sanitized)
        timestamp: Optional timestamp (defaults to current time)

    Returns:
        Filename in format: YYYYMMDDHHMMSS_name.jpg
    """
    if timestamp is None:
        timestamp = datetime.now()

    timestamp_str = timestamp.strftime("%Y%m%d%H%M%S")
    safe_name = sanitize_name(name)

    return f"{timestamp_str}_{safe_name}{FILE_EXTENSION}"


def parse_consent_filename(filename: str) -> Optional[Tuple[str, str]]:
    """Parse a consent capture filename to extract timestamp and name.

    Args:
        filename: The filename to parse

    Returns:
        Tuple of (timestamp_str, name) if valid, None if invalid format
    """
    # Check basic requirements
    if len(filename) < MIN_FILENAME_LENGTH:
        logger.debug(f"Filename too short: {filename}")
        return None

    if not filename.endswith(FILE_EXTENSION):
        logger.debug(f"Invalid extension: {filename}")
        return None

    # Check for underscore separator at correct position
    if filename[TIMESTAMP_LENGTH] != "_":
        logger.debug(f"Missing underscore at position {TIMESTAMP_LENGTH}: {filename}")
        return None

    # Extract components
    timestamp_str = filename[:TIMESTAMP_LENGTH]
    name_with_ext = filename[TIMESTAMP_LENGTH + 1 :]  # Skip the underscore
    name = name_with_ext[: -len(FILE_EXTENSION)].lower()

    # Validate timestamp format (all digits)
    if not timestamp_str.isdigit():
        logger.debug(f"Invalid timestamp format: {timestamp_str}")
        return None

    # Validate name is not empty
    if not name:
        logger.debug(f"Empty name in filename: {filename}")
        return None

    return timestamp_str, name


def get_consent_filepath(
    name: Optional[str], timestamp: Optional[datetime] = None
) -> Path:
    """Get the full filepath for a consent capture.

    Args:
        name: The person's name
        timestamp: Optional timestamp (defaults to current time)

    Returns:
        Full path to the consent capture file
    """
    ensure_consent_dir_exists()
    filename = create_consent_filename(name, timestamp)
    return CONSENT_DIR / filename


def find_consent_files_for_name(name: str) -> list[Path]:
    """Find all consent files for a given name.

    Args:
        name: The person's name to search for

    Returns:
        List of Path objects for matching consent files
    """
    ensure_consent_dir_exists()
    safe_name = sanitize_name(name)

    # Use glob pattern to find all files with this name
    pattern = f"*_{safe_name}{FILE_EXTENSION}"
    return list(CONSENT_DIR.glob(pattern))


def list_all_consent_files() -> list[Path]:
    """List all valid consent files in the consent directory.

    Returns:
        List of Path objects for all consent files
    """
    ensure_consent_dir_exists()
    return list(CONSENT_DIR.glob(f"*{FILE_EXTENSION}"))


def extract_name_from_path(file_path: Path) -> Optional[str]:
    """Extract the person's name from a consent file path.

    Args:
        file_path: Path to the consent file

    Returns:
        The person's name if valid, None otherwise
    """
    result = parse_consent_filename(file_path.name)
    if result:
        _, name = result
        return name
    return None


def extract_timestamp_from_path(file_path: Path) -> Optional[datetime]:
    """Extract the timestamp from a consent file path.

    Args:
        file_path: Path to the consent file

    Returns:
        The timestamp as datetime if valid, None otherwise
    """
    result = parse_consent_filename(file_path.name)
    if result:
        timestamp_str, _ = result
        try:
            return datetime.strptime(timestamp_str, "%Y%m%d%H%M%S")
        except ValueError:
            logger.debug(f"Failed to parse timestamp: {timestamp_str}")
            return None
    return None
