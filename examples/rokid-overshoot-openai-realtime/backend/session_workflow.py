from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from httpx import AsyncClient
from recipe_catalog import RecipeStep, normalize_inventory_name
from session_constants import (
    INVENTORY_SCAN_PROMPT,
    PHASE_COMPLETED,
    PHASE_CONNECTING,
    PHASE_ERROR,
    PHASE_GUIDING,
    PHASE_INVENTORY,
    PHASE_RECIPE_SELECTION,
    PHASE_WAITING,
)
from session_helpers import (
    completed_task_ids_for_session,
    detector_key_for_overshoot_prompt,
    extract_result_value,
    matches_overshoot_prompt,
    matches_condition,
    parse_arguments,
    parse_structured_result,
    response_text,
)
from session_types import ControlSession, SessionEvent, StepRuntimeState

logger = logging.getLogger("uvicorn.error")
DEBUG_SCAN_INVENTORY_ITEMS = ("orange juice",)


def _compact_json(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
    except TypeError:
        return repr(value)


class SessionWorkflowMixin:
    if TYPE_CHECKING:
        _recipes: Any
        _overshoot_http: AsyncClient

        async def _send_openai_user_text(
            self, session: ControlSession, text: str
        ) -> None: ...
        async def _send_openai_event(
            self, session: ControlSession, payload: dict[str, Any]
        ) -> None: ...
        async def _send_openai_tool_output(
            self,
            session: ControlSession,
            *,
            call_id: str,
            output: str,
            continue_response: bool,
        ) -> None: ...
        async def _speak_line(self, session: ControlSession, text: str) -> None: ...
        async def _send_control(
            self, session: ControlSession, payload: dict[str, Any]
        ) -> None: ...
        async def _stop_vision_runtime(self, session: ControlSession) -> None: ...
        async def _stop_realtime_runtime(self, session: ControlSession) -> None: ...

    async def _run_session_loop(self, session: ControlSession) -> None:
        while True:
            event = await session.queue.get()
            if event.kind == "session.destroy":
                await self._reset_runtime_state(session)
                return
            try:
                await self._handle_event(session, event)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "session=%s event=%s failed", session.session_id, event.kind
                )
                await self._fail_session(
                    session, "Something went wrong. Please restart."
                )

    async def _handle_event(self, session: ControlSession, event: SessionEvent) -> None:
        if event.kind == "session.start":
            await self._handle_start(session)
            return
        if event.kind == "session.stop":
            await self._reset_runtime_state(session)
            await self._publish_hud_state(session)
            return
        if event.kind == "debug.step":
            await self._handle_debug_step(session, event.payload)
            return
        if event.kind == "vision.ready":
            await self._maybe_begin_inventory_scan(session)
            return
        if event.kind == "realtime.ready":
            await self._maybe_begin_inventory_scan(session)
            return
        if event.kind == "overshoot.result":
            await self._handle_overshoot_result(session, event.payload)
            return
        if event.kind == "overshoot.closed":
            await self._handle_overshoot_closed(session, event.payload)
            return
        if event.kind == "realtime.closed":
            await self._handle_realtime_closed(session, event.payload)
            return
        if event.kind == "openai.response.created":
            self._handle_openai_response_created(session, event.payload)
            return
        if event.kind == "openai.response.done":
            await self._handle_openai_response_done(session, event.payload)
            return
        if event.kind == "openai.error":
            message = event.payload.get("message")
            code = ""
            if isinstance(message, dict):
                code = str(message.get("code") or "").strip()
            if code == "response_cancel_not_active":
                session.openai_response_active = False
                logger.info(
                    "session=%s ignoring benign openai cancel error=%s",
                    session.session_id,
                    message,
                )
                return
            logger.error("session=%s openai error=%s", session.session_id, message)
            if session.phase not in {PHASE_WAITING, PHASE_ERROR}:
                await self._fail_session(
                    session, "OpenAI sideband disconnected. Tap to restart."
                )

    async def _handle_start(self, session: ControlSession) -> None:
        if session.phase not in {PHASE_WAITING, PHASE_ERROR, PHASE_COMPLETED}:
            return
        session.phase = PHASE_CONNECTING
        session.inventory_signature = None
        session.inventory_hits = 0
        session.inventory_items.clear()
        session.recipe = None
        session.step_lookup.clear()
        session.step_index_by_id.clear()
        session.current_step_id = None
        session.step_state = StepRuntimeState()
        session.current_speech_text = None
        session.selecting_recipe = False
        await self._publish_hud_state(session)
        await self._maybe_begin_inventory_scan(session)

    async def _handle_debug_step(
        self,
        session: ControlSession,
        payload: dict[str, Any],
    ) -> None:
        direction = str(payload.get("direction") or "").strip().lower()
        if direction not in {"forward", "backward"}:
            return
        if session.phase == PHASE_INVENTORY:
            await self._apply_debug_inventory_scan(session)
            return
        if (
            session.phase not in {PHASE_GUIDING, PHASE_COMPLETED}
            or session.recipe is None
        ):
            return
        if session.current_step_id is None:
            return
        current_index = session.step_index_by_id.get(session.current_step_id)
        if current_index is None:
            return
        delta = 1 if direction == "forward" else -1
        next_index = max(0, min(len(session.recipe.steps) - 1, current_index + delta))
        if next_index == current_index:
            return
        session.phase = PHASE_GUIDING
        session.current_step_id = session.recipe.steps[next_index].id
        await self._enter_step(session, speak_on_enter=True)

    async def _apply_debug_inventory_scan(self, session: ControlSession) -> None:
        normalized = tuple(
            sorted(
                {
                    normalize_inventory_name(item)
                    for item in DEBUG_SCAN_INVENTORY_ITEMS
                    if normalize_inventory_name(item)
                }
            )
        )
        if not normalized:
            return
        session.inventory_signature = normalized
        session.inventory_hits = 2
        session.inventory_items = list(normalized)
        logger.info(
            "session=%s debug inventory scan inventory_items=%s",
            session.session_id,
            _compact_json(session.inventory_items),
        )
        session.phase = PHASE_RECIPE_SELECTION
        session.selecting_recipe = True
        await self._publish_hud_state(session)
        await self._request_recipe_selection(session)

    async def _maybe_begin_inventory_scan(self, session: ControlSession) -> None:
        if session.phase != PHASE_CONNECTING:
            return
        if not session.vision_ready or not session.realtime_ready:
            return
        session.phase = PHASE_INVENTORY
        session.inventory_signature = None
        session.inventory_hits = 0
        session.inventory_items.clear()
        session.selecting_recipe = False
        await self._publish_hud_state(session)
        await self._switch_prompt(session, "inventory_scan", INVENTORY_SCAN_PROMPT)

    async def _handle_overshoot_result(
        self,
        session: ControlSession,
        payload: dict[str, Any],
    ) -> None:
        generation = payload.get("generation")
        if generation != session.vision_generation:
            logger.info(
                "session=%s ignoring overshoot result due to stale generation result_generation=%s current_generation=%s",
                session.session_id,
                generation,
                session.vision_generation,
            )
            return
        if session.overshoot_stream_id is None:
            logger.info(
                "session=%s ignoring overshoot result because no active stream",
                session.session_id,
            )
            return
        if not payload.get("ok", False):
            logger.warning(
                "session=%s overshoot error=%s payload=%s",
                session.session_id,
                payload.get("error"),
                _compact_json(payload),
            )
            return

        expected_prompt = session.active_prompt_text or ""
        prompt = str(payload.get("prompt") or "")
        active_detector = (
            detector_key_for_overshoot_prompt(session, expected_prompt) or "unknown"
        )
        result_detector = (
            detector_key_for_overshoot_prompt(session, prompt) or "unknown"
        )
        if not matches_overshoot_prompt(expected_prompt, prompt):
            if active_detector == "unknown" or result_detector == "unknown":
                logger.info(
                    "session=%s ignoring overshoot result due to prompt mismatch active_detector=%s result_detector=%s active_prompt=%s result_prompt=%s",
                    session.session_id,
                    active_detector,
                    result_detector,
                    _compact_json(expected_prompt),
                    _compact_json(prompt),
                )
            else:
                logger.info(
                    "session=%s ignoring overshoot result due to prompt mismatch active_detector=%s result_detector=%s",
                    session.session_id,
                    active_detector,
                    result_detector,
                )
            return
        if prompt != expected_prompt:
            if result_detector == "unknown":
                logger.info(
                    "session=%s accepting overshoot result with augmented prompt detector=%s result_prompt=%s",
                    session.session_id,
                    active_detector,
                    _compact_json(prompt),
                )
            else:
                logger.info(
                    "session=%s accepting overshoot result with augmented prompt detector=%s",
                    session.session_id,
                    result_detector,
                )
        parsed = parse_structured_result(payload.get("result"))
        if parsed is None:
            logger.info(
                "session=%s ignoring overshoot result because result is not structured json raw_result=%s",
                session.session_id,
                _compact_json(payload.get("result")),
            )
            return
        logger.info(
            "session=%s overshoot structured_result phase=%s detector=%s result=%s",
            session.session_id,
            session.phase,
            session.active_detector_key,
            _compact_json(parsed),
        )

        if session.phase == PHASE_INVENTORY:
            await self._handle_inventory_result(session, parsed)
            return
        if session.phase == PHASE_GUIDING and session.recipe is not None:
            await self._evaluate_current_step(session, parsed)

    async def _handle_inventory_result(
        self,
        session: ControlSession,
        result: dict[str, Any],
    ) -> None:
        ingredients = result.get("ingredients")
        if not isinstance(ingredients, list):
            logger.info(
                "session=%s inventory scan missing ingredients list result=%s",
                session.session_id,
                _compact_json(result),
            )
            return

        normalized = tuple(
            sorted(
                {
                    normalize_inventory_name(item)
                    for item in ingredients
                    if isinstance(item, str) and normalize_inventory_name(item)
                }
            )
        )
        if not normalized:
            logger.info(
                "session=%s inventory scan empty after normalization raw_ingredients=%s",
                session.session_id,
                _compact_json(ingredients),
            )
            return

        if normalized == session.inventory_signature:
            session.inventory_hits += 1
        else:
            session.inventory_signature = normalized
            session.inventory_hits = 1
        logger.info(
            "session=%s inventory scan raw_ingredients=%s normalized=%s hits=%s stable=%s",
            session.session_id,
            _compact_json(ingredients),
            _compact_json(normalized),
            session.inventory_hits,
            session.inventory_hits >= 2,
        )

        if session.inventory_hits < 2:
            return

        session.inventory_items = list(normalized)
        logger.info(
            "session=%s inventory scan stabilized inventory_items=%s",
            session.session_id,
            _compact_json(session.inventory_items),
        )
        session.phase = PHASE_RECIPE_SELECTION
        session.selecting_recipe = True
        await self._publish_hud_state(session)
        await self._request_recipe_selection(session)

    async def _request_recipe_selection(self, session: ControlSession) -> None:
        if not session.inventory_items:
            recipe_id = self._recipes.best_match([])
            if recipe_id is not None:
                await self._activate_recipe(session, recipe_id, call_id=None)
            return
        if session.openai_ws is None:
            recipe_id = self._recipes.best_match(session.inventory_items)
            if recipe_id is not None:
                await self._activate_recipe(session, recipe_id, call_id=None)
            return

        ingredient_list = ", ".join(session.inventory_items)
        await self._send_openai_user_text(
            session,
            (
                f"Detected visible ingredients: {ingredient_list}. "
                "Choose the single best recipe filename for these ingredients. "
                "Call list_recipes first, then call activate_recipe. Do not speak."
            ),
        )
        await self._send_openai_event(session, {"type": "response.create"})

    def _handle_openai_response_created(
        self,
        session: ControlSession,
        payload: dict[str, Any],
    ) -> None:
        if payload.get("generation") != session.realtime_generation:
            return
        session.openai_response_active = True

    async def _handle_openai_response_done(
        self,
        session: ControlSession,
        payload: dict[str, Any],
    ) -> None:
        if payload.get("generation") != session.realtime_generation:
            return
        session.openai_response_active = False

        response = payload.get("response") or {}
        output_items = response.get("output") or []
        fn_call = next(
            (
                item
                for item in output_items
                if item.get("type") == "function_call"
                and item.get("status") == "completed"
            ),
            None,
        )

        if fn_call is None:
            if session.phase == PHASE_RECIPE_SELECTION and session.recipe is None:
                recipe_id = self._recipes.best_match(session.inventory_items)
                if recipe_id is not None:
                    await self._activate_recipe(session, recipe_id, call_id=None)
            return

        tool_name = str(fn_call.get("name") or "").strip()
        call_id = str(fn_call.get("call_id") or "").strip()
        args = parse_arguments(fn_call.get("arguments"))

        if tool_name == "list_recipes":
            output = json.dumps(self._recipes.list_entries())
            await self._send_openai_tool_output(
                session,
                call_id=call_id,
                output=output,
                continue_response=True,
            )
            return

        if tool_name == "activate_recipe":
            recipe_id = str(args.get("id") or "").strip()
            if not recipe_id:
                recipe_id = self._recipes.best_match(session.inventory_items) or ""
            await self._activate_recipe(session, recipe_id, call_id=call_id)
            return

        await self._send_openai_tool_output(
            session,
            call_id=call_id,
            output=json.dumps({"error": f"unknown tool {tool_name}"}),
            continue_response=False,
        )

    async def _activate_recipe(
        self,
        session: ControlSession,
        recipe_id: str,
        *,
        call_id: str | None,
    ) -> None:
        if not recipe_id:
            await self._fail_session(
                session, "No recipe matched the scene. Tap to restart."
            )
            return

        try:
            recipe = self._recipes.load(recipe_id)
        except ValueError as error:
            logger.warning(
                "session=%s invalid recipe_id=%s", session.session_id, recipe_id
            )
            if call_id:
                await self._send_openai_tool_output(
                    session,
                    call_id=call_id,
                    output=json.dumps({"error": str(error)}),
                    continue_response=False,
                )
            fallback_id = self._recipes.best_match(session.inventory_items)
            if fallback_id and fallback_id != recipe_id:
                await self._activate_recipe(session, fallback_id, call_id=None)
                return
            await self._fail_session(
                session, "Recipe selection failed. Tap to restart."
            )
            return

        if call_id:
            await self._send_openai_tool_output(
                session,
                call_id=call_id,
                output=json.dumps(
                    {"id": recipe.id, "display_name": recipe.display_name}
                ),
                continue_response=False,
            )

        session.recipe = recipe
        session.step_lookup = {step.id: step for step in recipe.steps}
        session.step_index_by_id = {
            step.id: index for index, step in enumerate(recipe.steps)
        }
        session.current_step_id = recipe.start_step_id
        session.phase = PHASE_GUIDING
        session.selecting_recipe = False
        await self._enter_step(session, speak_on_enter=True)

    async def _enter_step(
        self, session: ControlSession, *, speak_on_enter: bool
    ) -> None:
        if session.recipe is None or session.current_step_id is None:
            return
        step = session.step_lookup.get(session.current_step_id)
        if step is None:
            await self._fail_session(session, "Recipe step is missing. Tap to restart.")
            return
        detector = session.recipe.detectors.get(step.detector_key)
        if detector is None:
            await self._fail_session(
                session, "Recipe detector is missing. Tap to restart."
            )
            return

        session.step_state = StepRuntimeState()
        await self._publish_hud_state(session)
        await self._switch_prompt(session, step.detector_key, detector.prompt)
        if speak_on_enter and step.on_enter_speech:
            await self._speak_line(session, step.on_enter_speech)

    async def _switch_prompt(
        self,
        session: ControlSession,
        detector_key: str,
        prompt: str,
    ) -> None:
        if session.overshoot_stream_id is None:
            session.active_detector_key = detector_key
            session.active_prompt_text = prompt
            return
        if session.active_prompt_text == prompt:
            session.active_detector_key = detector_key
            return

        if session.active_prompt_text is not None:
            response = await self._overshoot_http.patch(
                f"/streams/{session.overshoot_stream_id}/config/prompt",
                json={"prompt": prompt},
            )
            if not response.is_success:
                raise RuntimeError(
                    "Failed to update Overshoot prompt "
                    f"(HTTP {response.status_code}): {response_text(response)}"
                )

        session.active_detector_key = detector_key
        session.active_prompt_text = prompt
        logger.info(
            "session=%s prompt switched detector=%s",
            session.session_id,
            detector_key,
        )

    async def _evaluate_current_step(
        self,
        session: ControlSession,
        result: dict[str, Any],
    ) -> None:
        if session.recipe is None or session.current_step_id is None:
            return
        step = session.step_lookup.get(session.current_step_id)
        if step is None:
            return
        detector = session.recipe.detectors.get(step.detector_key)
        if detector is None:
            return

        value = extract_result_value(result, step.value_path or detector.field)
        ignored_values = step.ignored_values_list()

        if step.evaluation_mode == "match_value":
            await self._evaluate_match_value(session, step, value, ignored_values)
            return
        if step.evaluation_mode == "numeric_threshold_with_progress_once":
            await self._evaluate_numeric_threshold(session, step, value, ignored_values)
            return
        if step.evaluation_mode == "count_rising_edges_true":
            await self._evaluate_rising_edges(session, step, value)
            return
        if step.evaluation_mode == "enum_progress_once_then_complete":
            await self._evaluate_enum_progress(session, step, value, ignored_values)
            return
        if step.evaluation_mode == "momentary_true_complete":
            await self._evaluate_momentary_true(session, step, value)

    async def _evaluate_match_value(
        self,
        session: ControlSession,
        step: RecipeStep,
        value: Any,
        ignored_values: list[Any],
    ) -> None:
        if value in ignored_values:
            session.step_state.last_observed_value = value
            return
        if value == step.expected_value:
            await self._advance_step(
                session, speech=step.success_speech, next_step_id=step.next_step_id
            )
            return
        if step.mismatch_speech:
            should_speak = not step.speak_on_observation_change_only
            if step.speak_on_observation_change_only:
                should_speak = value != session.step_state.last_spoken_observation
            if should_speak:
                session.step_state.last_spoken_observation = value
                await self._speak_line(session, step.mismatch_speech)
        session.step_state.last_observed_value = value

    async def _evaluate_numeric_threshold(
        self,
        session: ControlSession,
        step: RecipeStep,
        value: Any,
        ignored_values: list[Any],
    ) -> None:
        if value in ignored_values or not isinstance(value, (int, float)):
            return
        if step.complete_condition and matches_condition(
            step.complete_condition, value
        ):
            await self._advance_step(
                session, speech=step.complete_speech, next_step_id=step.next_step_id
            )
            return
        if (
            step.progress_condition
            and matches_condition(step.progress_condition, value)
            and "progress_once" not in session.step_state.progress_flags
        ):
            session.step_state.progress_flags.add("progress_once")
            if step.progress_once_speech:
                await self._speak_line(session, step.progress_once_speech)

    async def _evaluate_rising_edges(
        self,
        session: ControlSession,
        step: RecipeStep,
        value: Any,
    ) -> None:
        observed = bool(value)
        if observed and not session.step_state.previous_boolean_value:
            session.step_state.counter += 1
            milestone = next(
                (
                    item
                    for item in step.milestones
                    if item.count == session.step_state.counter
                ),
                None,
            )
            if milestone is not None:
                if milestone.next_step_id is not None:
                    await self._advance_step(
                        session,
                        speech=milestone.speech,
                        next_step_id=milestone.next_step_id,
                    )
                    session.step_state.previous_boolean_value = observed
                    return
                if milestone.speech:
                    await self._speak_line(session, milestone.speech)
            elif (
                step.target_count is not None
                and session.step_state.counter >= step.target_count
            ):
                await self._advance_step(
                    session, speech=step.complete_speech, next_step_id=step.next_step_id
                )
                session.step_state.previous_boolean_value = observed
                return
        session.step_state.previous_boolean_value = observed

    async def _evaluate_enum_progress(
        self,
        session: ControlSession,
        step: RecipeStep,
        value: Any,
        ignored_values: list[Any],
    ) -> None:
        if value in ignored_values:
            return
        if value == step.complete_value:
            await self._advance_step(
                session, speech=step.complete_speech, next_step_id=step.next_step_id
            )
            return
        if (
            value == step.progress_value
            and "progress_once" not in session.step_state.progress_flags
        ):
            session.step_state.progress_flags.add("progress_once")
            if step.progress_once_speech:
                await self._speak_line(session, step.progress_once_speech)

    async def _evaluate_momentary_true(
        self,
        session: ControlSession,
        step: RecipeStep,
        value: Any,
    ) -> None:
        if bool(value) is bool(step.complete_on):
            await self._advance_step(
                session, speech=step.complete_speech, next_step_id=step.next_step_id
            )

    async def _advance_step(
        self,
        session: ControlSession,
        *,
        speech: str | None,
        next_step_id: str | None,
    ) -> None:
        if next_step_id is None:
            session.phase = PHASE_COMPLETED
            session.current_step_id = None
            await self._publish_hud_state(session)
            if speech:
                await self._speak_line(session, speech)
            return

        session.phase = PHASE_GUIDING
        session.current_step_id = next_step_id
        await self._enter_step(session, speak_on_enter=speech is None)
        if speech:
            await self._speak_line(session, speech)

    async def _handle_overshoot_closed(
        self,
        session: ControlSession,
        payload: dict[str, Any],
    ) -> None:
        if payload.get("generation") != session.vision_generation:
            return
        if session.phase in {PHASE_WAITING, PHASE_ERROR}:
            return
        await self._fail_session(session, "Overshoot stream ended. Tap to restart.")

    async def _handle_realtime_closed(
        self,
        session: ControlSession,
        payload: dict[str, Any],
    ) -> None:
        if payload.get("generation") != session.realtime_generation:
            return
        if session.phase in {PHASE_WAITING, PHASE_ERROR}:
            return
        await self._fail_session(
            session, "Audio guidance disconnected. Tap to restart."
        )

    async def _fail_session(self, session: ControlSession, message: str) -> None:
        await self._reset_runtime_state(session)
        session.phase = PHASE_ERROR
        await self._send_control(
            session,
            {
                "type": "hud.error",
                "message": message,
            },
        )
        await self._publish_hud_state(session)

    async def _reset_runtime_state(self, session: ControlSession) -> None:
        await self._stop_vision_runtime(session)
        await self._stop_realtime_runtime(session)
        session.phase = PHASE_WAITING
        session.active_prompt_text = None
        session.active_detector_key = None
        session.inventory_signature = None
        session.inventory_hits = 0
        session.inventory_items.clear()
        session.recipe = None
        session.step_lookup.clear()
        session.step_index_by_id.clear()
        session.current_step_id = None
        session.step_state = StepRuntimeState()
        session.openai_response_active = False
        session.speech_epoch = 0
        session.current_speech_text = None
        session.selecting_recipe = False

    async def _publish_hud_state(self, session: ControlSession) -> None:
        recipe_name = session.recipe.display_name if session.recipe else None
        active_task_id = None
        tasks_payload: list[dict[str, Any]] = []
        completed_task_ids = completed_task_ids_for_session(session)

        if session.recipe is not None and session.current_step_id is not None:
            step = session.step_lookup.get(session.current_step_id)
            if step is not None:
                active_task_id = step.task_id

        if session.recipe is not None:
            for task in session.recipe.tasks:
                tasks_payload.append(
                    {
                        "id": task.id,
                        "text": task.text,
                        "completed": task.id in completed_task_ids,
                    }
                )

        screen = "start" if session.phase == PHASE_WAITING else "running"
        await self._send_control(
            session,
            {
                "type": "hud.state",
                "screen": screen,
                "phase": session.phase,
                "recipe_name": recipe_name,
                "tasks": tasks_payload,
                "active_task_id": active_task_id,
                "speech_epoch": session.speech_epoch,
            },
        )
