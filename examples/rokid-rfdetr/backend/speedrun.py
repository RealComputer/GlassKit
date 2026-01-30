from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from logging_utils import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Split:
    label: str
    complete_on_class: str


@dataclass(frozen=True)
class Group:
    name: str
    splits: list[Split]


@dataclass(frozen=True)
class SpeedrunConfig:
    name: str
    groups: list[Group]

    @property
    def total_splits(self) -> int:
        return sum(len(group.splits) for group in self.groups)

    def flattened(self) -> list[Split]:
        items: list[Split] = []
        for group in self.groups:
            items.extend(group.splits)
        return items

    def client_payload(self) -> dict[str, Any]:
        return {
            "type": "config",
            "name": self.name,
            "groups": [
                {
                    "name": group.name,
                    "splits": [{"label": split.label} for split in group.splits],
                }
                for group in self.groups
            ],
        }


class SpeedrunController:
    def __init__(self, config: SpeedrunConfig) -> None:
        self._config = config
        self._flat_splits = config.flattened()
        self._total_splits = len(self._flat_splits)
        self._run_state = "idle"
        self._active_index = 0
        self._consecutive_hits = 0
        self._lock = asyncio.Lock()

    @property
    def config(self) -> SpeedrunConfig:
        return self._config

    def state_payload(self) -> dict[str, Any]:
        return {
            "type": "state",
            "run_state": self._run_state,
            "active_split_index": self._active_index,
            "completed_count": self._active_index,
        }

    async def on_detection(self, detected_classes: set[str]) -> dict[str, Any] | None:
        async with self._lock:
            if self._run_state != "running":
                self._consecutive_hits = 0
                return None
            if self._active_index >= self._total_splits:
                return None

            target = self._flat_splits[self._active_index].complete_on_class
            if target in detected_classes:
                self._consecutive_hits += 1
            else:
                self._consecutive_hits = 0

            if self._consecutive_hits < 2:
                return None

            return self._complete_current_split()

    async def on_client_message(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        msg_type = str(payload.get("type") or "").strip()
        if not msg_type:
            return []

        async with self._lock:
            if msg_type == "run.start":
                return self._handle_run_start()
            if msg_type == "debug.step":
                direction = str(payload.get("direction") or "").lower().strip()
                return self._handle_debug_step(direction)

        return []

    def _handle_run_start(self) -> list[dict[str, Any]]:
        if self._run_state != "idle":
            return []
        self._run_state = "running"
        self._active_index = 0
        self._consecutive_hits = 0
        if self._total_splits == 0:
            self._run_state = "finished"
        return [self.state_payload()]

    def _handle_debug_step(self, direction: str) -> list[dict[str, Any]]:
        if self._run_state == "idle":
            return []

        if direction == "next":
            if self._active_index >= self._total_splits:
                return []
            payload = self._complete_current_split()
            return [payload] if payload else []

        if direction == "prev":
            if self._active_index <= 0:
                return []
            self._active_index -= 1
            if self._run_state == "finished":
                self._run_state = "running"
            self._consecutive_hits = 0
            return [self.state_payload()]

        return []

    def _complete_current_split(self) -> dict[str, Any] | None:
        if self._active_index >= self._total_splits:
            return None

        completed_index = self._active_index
        self._active_index += 1
        self._consecutive_hits = 0

        if self._active_index >= self._total_splits:
            self._run_state = "finished"

        return {
            "type": "split_completed",
            "split_index": completed_index,
            "active_split_index": self._active_index,
            "completed_count": self._active_index,
            "run_state": self._run_state,
        }


def load_speedrun_config(path: Path) -> SpeedrunConfig:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Speedrun config root must be an object")

    config_name = str(data.get("name") or "").strip() or "Speedrun"
    groups_data = data.get("groups")
    if not isinstance(groups_data, list):
        raise ValueError("Speedrun config groups must be an array")

    groups: list[Group] = []
    for group in groups_data:
        if not isinstance(group, dict):
            continue
        group_name = str(group.get("name") or "").strip()
        splits_data = group.get("splits")
        if not group_name or not isinstance(splits_data, list):
            continue
        splits: list[Split] = []
        for split in splits_data:
            if not isinstance(split, dict):
                continue
            label = str(split.get("label") or "").strip()
            complete_on = str(split.get("complete_on_class") or "").strip()
            if not label or not complete_on:
                continue
            splits.append(Split(label=label, complete_on_class=complete_on))
        if splits:
            groups.append(Group(name=group_name, splits=splits))

    if not groups:
        raise ValueError("Speedrun config has no valid groups")

    logger.info(
        "Loaded speedrun '%s' with %s groups and %s splits",
        config_name,
        len(groups),
        sum(len(g.splits) for g in groups),
    )
    return SpeedrunConfig(name=config_name, groups=groups)
