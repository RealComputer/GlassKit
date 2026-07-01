from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _find_stats(stats: Iterable[Any], stats_type: str, kind: str | None) -> Any | None:
    matches = [
        stat
        for stat in stats
        if getattr(stat, "type", None) == stats_type
        and (kind is None or getattr(stat, "kind", None) == kind)
    ]
    if not matches:
        return None
    return max(matches, key=lambda stat: _stats_int(stat, "bytesSent"))


def _stats_int(stat: Any | None, field_name: str) -> int:
    if stat is None:
        return 0
    value = getattr(stat, field_name, 0)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _stats_float(stat: Any | None, field_name: str) -> float | None:
    if stat is None:
        return None
    value = getattr(stat, field_name, None)
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return None


def _stats_text(stat: Any | None, field_name: str) -> str:
    if stat is None:
        return "n/a"
    value = getattr(stat, field_name, None)
    if value is None:
        return "n/a"
    return str(value)


def _format_kbps(value_bps: float | None) -> str:
    if value_bps is None:
        return "n/a"
    return f"{value_bps / 1000:.0f}"


def _format_ms(value_seconds: float | None) -> str:
    if value_seconds is None:
        return "n/a"
    return f"{value_seconds * 1000:.0f}"


def _format_optional_int(value: int | None) -> str:
    if value is None:
        return "n/a"
    return str(value)


def _format_rtcp_loss_pct(fraction_lost: float | None) -> str:
    if fraction_lost is None:
        return "n/a"
    return f"{fraction_lost / 256 * 100:.1f}"
