from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from session_constants import EvaluationMode


def normalize_inventory_name(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_filename(value: str) -> str:
    return normalize_inventory_name(value.replace("-", " "))


class RecipeTask(BaseModel):
    id: str
    text: str


class RecipeDetector(BaseModel):
    prompt: str
    field: Literal["ingredients", "color", "state", "flag", "level"]


class RecipeCondition(BaseModel):
    eq: int | float | str | bool | None = None
    gt: int | float | None = None
    gte: int | float | None = None
    lt: int | float | None = None
    lte: int | float | None = None


class RecipeMilestone(BaseModel):
    count: int
    speech: str | None = None
    next_step_id: str | None = None


class RecipeStep(BaseModel):
    id: str
    task_id: str
    evaluation_mode: EvaluationMode
    detector_key: str
    expected_value: str | int | float | bool | None = None
    ignored_values: list[Any] = Field(default_factory=list)
    ignore_values: list[Any] = Field(default_factory=list)
    value_path: str | None = None
    progress_condition: RecipeCondition | None = None
    progress_once_speech: str | None = None
    complete_condition: RecipeCondition | None = None
    complete_speech: str | None = None
    next_step_id: str | None = None
    target_count: int | None = None
    milestones: list[RecipeMilestone] = Field(default_factory=list)
    count_edge: str | None = None
    rearm_condition: str | None = None
    speak_on_observation_change_only: bool = False
    on_enter_speech: str | None = None
    mismatch_speech: str | None = None
    success_speech: str | None = None
    progress_value: str | None = None
    complete_value: str | None = None
    complete_on: bool | None = None

    def ignored_values_list(self) -> list[Any]:
        return [*self.ignored_values, *self.ignore_values]


class Recipe(BaseModel):
    id: str
    display_name: str
    start_step_id: str
    tasks: list[RecipeTask]
    detectors: dict[str, RecipeDetector]
    steps: list[RecipeStep]


class RecipeCatalog:
    def __init__(self, root: Path) -> None:
        self._root = root

    def list_entries(self) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        if not self._root.exists():
            return entries
        for path in sorted(self._root.glob("*.json")):
            entries.append({"id": path.stem})
        return entries

    def load(self, recipe_id: str) -> Recipe:
        path = self._root / f"{recipe_id}.json"
        if not path.exists():
            raise ValueError(f"Unknown recipe id: {recipe_id}")
        try:
            return Recipe.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as error:
            raise ValueError(f"Invalid recipe {recipe_id}: {error}") from error

    def best_match(self, inventory_items: list[str]) -> str | None:
        entries = self.list_entries()
        if not entries:
            return None
        if not inventory_items:
            return entries[0]["id"]

        scored: list[tuple[int, str]] = []
        normalized_items = [normalize_inventory_name(item) for item in inventory_items]
        for entry in entries:
            recipe_id = entry["id"]
            haystack = normalize_filename(recipe_id)
            tokens = set(haystack.split())
            score = 0
            for item in normalized_items:
                if not item:
                    continue
                if item in haystack:
                    score += 4
                item_tokens = set(item.split())
                if item_tokens and item_tokens.issubset(tokens):
                    score += 2
                score += sum(1 for token in item_tokens if token in tokens)
            scored.append((score, recipe_id))
        scored.sort(key=lambda row: (-row[0], row[1]))
        return scored[0][1]
