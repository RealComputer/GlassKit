# Technical Design Specification

## 1. Purpose

This document defines the implementation architecture for **Mocktail Coach**, a demo-focused smart glasses application for Rokid Glasses that guides a user through making a layered mocktail in real time.

## 2. Product context

The experience is:

* The user launches the app.
* The HUD first shows a simple start screen.
* The user taps once to begin.
* After that, the user does not need to speak or manual control on the glasses app.
* The app watches the live camera feed and proactively guides the user with:
  * HUD task display
  * spoken instructions
  * live correction if the user makes a mistake
* The app continues until the mocktail is complete.

External services:

* **Overshoot** handles live visual inference from the Rokid camera feed.
* **OpenAI Realtime** handles:
  * recipe-selection reasoning at startup
  * spoken guidance throughout the workflow

OpenAI Realtime must receive **text only from the server**. It must not access the camera or mic. All vision responsibility belongs to Overshoot.

Connection structure:

* **Rokid <-> Server**: WebSocket for app control and HUD state
* **Rokid -> Overshoot**: WebRTC for live camera video
* **Rokid <-> OpenAI Realtime**: WebRTC for audio output and transcript delivery
* **Server <-> Overshoot**: WebSocket, keepalive
* **Server <-> OpenAI Realtime**: WebSocket sideband for tool handling and speech control

## 3. Design goals

The implementation should follow these principles:

* **Server-authoritative workflow**
  The FastAPI backend is the source of truth for session state, step progression, corrections, and prompt switching.
* **Deterministic control loop**
  Overshoot detects what is happening. The server decides what it means. OpenAI Realtime does not control the visual workflow loop.
* **Thin client**
  The Rokid app should render HUD, handle gestures, maintain the existing media connections, and display the current transcript. It should not own workflow logic.
* **Data-driven behavior**
  Anything that can be expressed in JSON should live in recipe JSON, including:
  * task list text
  * spoken lines
  * detector prompt text
  * detector output schemas
  * step thresholds
  * transition mapping
* **Immediate response**
  General debounce is not needed. Overshoot already evaluates short video clips rather than single frames. The only deliberate multi-result check is the initial inventory scan, which requires two identical consecutive ingredient lists.
* **Latest speech wins**
  If a new spoken line becomes more relevant, it should always replace the previous line immediately.

## 4. High-level architecture
### Responsibilities

**Rokid client**

* Show the initial start screen
* Render the running HUD
* Send `tap`, `swipe forward`, and `swipe backward`
* Maintain the existing WebRTC connection to Overshoot for video streaming
* Maintain the existing WebRTC connection to OpenAI Realtime for audio output and transcript events
* Render only the current/latest transcript text

**FastAPI server**

* Own the full session state
* Control the workflow state machine
* Update Overshoot prompts
* Consume Overshoot results
* Drive OpenAI Realtime over sideband
* Load recipe JSON
* Publish HUD state to the client
* Log detailed events and errors

**Overshoot**

* Detect the current visual state from the live stream
* Return structured outputs for the active detector prompt

**OpenAI Realtime**

* Choose a recipe at startup from server-provided recipe filenames
* Speak exact prewritten lines from recipe JSON
* Deliver transcript deltas directly to the Rokid client over the Realtime data channel

## 5. Runtime flow

### 5.1 App launch

The app opens on a minimal HUD screen:

* App name: **Mocktail Coach**
* Text: `Look at the ingredients and tap to start`

No recipe or transcript is shown yet.

### 5.2 User taps start

The Rokid client sends:

```json
{ "type": "session.start" }
```

The server creates an in-memory session and moves to `CONNECTING`.

### 5.3 External sessions become active

The existing sample code (this curent dir for overshoot impl, and ../rokid-openai-realtime-rfdetr/ for openai realtime api impl) for media connections should be reused and updated. The server needs to orchestrate around it.

At this point:

* Rokid and server already have a control WebSocket
* Rokid establishes the Overshoot WebRTC stream for live video
* Server receives Overshoot results over WebSocket
* Rokid establishes OpenAI Realtime WebRTC
* Server joins the same OpenAI Realtime session over sideband WebSocket

### 5.4 Inventory scan

The server sets the active Overshoot prompt to the recipe inventory detector.

Rules:

* Normalize the `ingredients` array by sorting and deduplicating
* Accept inventory only when **two consecutive normalized results are identical**
* This is the only place where consecutive agreement is required

Once inventory stabilizes, the server moves to `RECIPE_SELECTION`.

### 5.5 Recipe selection

The server sends a text message to OpenAI Realtime describing the detected ingredients.

OpenAI Realtime can call:

* `list_recipes`
* `activate_recipe`

`list_recipes` returns recipe entries derived from the filenames in the recipe directory. Because there are very few recipes, filename keywords are enough for selection. The recipe filename should contain terms like `orange-juice` and `blue-drink`.

`activate_recipe` loads the selected JSON into the session as the active recipe.

The server then sends HUD state to the client with:

* recipe name
* task list
* active task highlight on the first task

### 5.6 Guided workflow

After recipe activation, the server enters `GUIDING`.

The workflow loop is:

1. Enter step
2. Update HUD active task
3. If the step has `on_enter_speech`, speak it
4. Switch Overshoot to the detector prompt for that step
5. Accept only results whose echoed prompt matches the current detector prompt
6. Evaluate the result using the step's evaluation mode
7. Either:
   * advance
   * correct
   * give one progress line
   * stay in place
8. Repeat until the final step completes

Because each Overshoot result includes the active prompt text, the server can discard stale results after prompt changes. ([Overshoot Docs][2])

### 5.7 Completion

After the lime step completes:

* mark all tasks complete
* speak the final line
* keep the final HUD visible

## 6. Session and orchestration model

## 6.1 Authoritative session object

Each live session should maintain:

* `session_id`
* `phase`
  `WAITING_FOR_START | CONNECTING | INVENTORY_SCAN | RECIPE_SELECTION | GUIDING | COMPLETED | ERROR`
* `recipe_id`
* `current_step_id`
* `current_task_id`
* `active_detector_key`
* `active_prompt_text`
* `speech_epoch`
* `overshoot_stream_ref`
* `openai_session_ref`
* `step_state`
* `hud_state`

`step_state` should be generic and reusable:

* `last_observed_value`
* `last_spoken_observation`
* `progress_flags`
* `counter`
* `previous_boolean_value`

## 6.2 Single per-session event loop

All inbound events for one session should be serialized through a single orchestrator loop.

Event sources:

* Rokid control WebSocket
* Overshoot results WebSocket
* OpenAI Realtime sideband WebSocket
* internal timers or async completions if needed

This prevents race conditions between:

* step changes
* prompt changes
* speech cancellation
* debug step navigation

## 6.3 Speech policy

The rule is simple:

* **newest speech always wins**

When the server decides to speak a new line:

1. cancel any in-progress OpenAI Realtime speech
2. increment `speech_epoch`
3. send the new exact text to OpenAI Realtime
4. publish updated HUD state with the new `speech_epoch`

The client uses `speech_epoch` to clear the transcript area before rendering the newest transcript delta stream.

## 6.4 Duplicate speech suppression

There is no detector debounce, but there **is** duplicate speech suppression.

Rule:

* Do not replay the same spoken line for the same unchanged detector output inside the same step.

Example:

* If the user keeps holding the red bottle for several consecutive clips, say the correction once.
* If the observed value changes away and later returns to red, the correction may be spoken again.

This preserves real-time feel while preventing audio spam.

## 6.5 Ice counting rule

Ice is the only step that needs special counting behavior.

The detector returns boolean `true` only when ice is visibly falling into the glass at that moment. One real scoop can still produce multiple consecutive `true` results across adjacent clips.

Implementation rule:

* Count a scoop only on a **false -> true** transition
* After a counted scoop, require at least one `false` result before another `true` can count
* No fixed wait is required

This keeps the interaction immediate while preventing double counting from one scoop.

## 6.6 Overshoot keepalive

The Overshoot stream lease must be renewed during the session. This should run as a simple background keepalive task owned by the session. ([Overshoot Docs][2])

## 7. UI behavior

## 7.1 Initial screen

Show only:

* `Mocktail Coach`
* `Look at the ingredients and tap to start`

## 7.2 Running screen

Show, in this order:

1. app name
2. recipe name
3. concise task list with current task highlighted
4. current/latest speech transcript only

Old transcript text should disappear. Only the most recent utterance should be visible.

The transcript text comes directly from OpenAI Realtime transcript delta events over the Rokid <-> OpenAI WebRTC data channel.

## 7.3 Debug gestures

The Rokid client should support:

* `tap` -> start
* `swipe forward` -> move to next internal step
* `swipe backward` -> move to previous internal step

Debug step movement should:

* update `current_step_id`
* update task highlight
* reset step-local state
* switch the active Overshoot detector prompt
* emit step entry speech if that step defines one

## 8. Server <-> client control messages

The server WebSocket exists for app control and HUD state only.

### Client -> Server

Start session:

```json
{ "type": "session.start" }
```

Debug next step:

```json
{ "type": "debug.step", "direction": "forward" }
```

Debug previous step:

```json
{ "type": "debug.step", "direction": "backward" }
```

### Server -> Client

HUD state:

```json
{
  "type": "hud.state",
  "screen": "running",
  "recipe_name": "Orange Blue Mocktail",
  "tasks": [
    { "id": "orange_juice", "text": "Add orange juice to halfway" },
    { "id": "ice", "text": "Add a few scoops of ice" },
    { "id": "gatorade", "text": "Fill with Gatorade" },
    { "id": "lime", "text": "Top with a lime wheel" }
  ],
  "active_task_id": "orange_juice",
  "speech_epoch": 3,
  "phase": "GUIDING"
}
```

Generic error:

```json
{
  "type": "hud.error",
  "message": "Something went wrong. Please restart."
}
```

## 9. OpenAI Realtime usage

OpenAI Realtime has exactly two roles in this app.

### 9.1 Startup recipe selection

The server sends text describing the detected ingredients. The model may call:

* `list_recipes`
* `activate_recipe`

The conversation can remain in the normal ongoing conversation thread.

### 9.2 Spoken guidance

Every spoken line should come from recipe JSON.

The server sends an exact-text instruction such as:

* "Speak exactly this line"
* followed by the target text

The model should not paraphrase, reason about vision, or invent new workflow decisions.

The server should **not** send every Overshoot result into OpenAI. During the guided workflow, OpenAI is used only when speech must be produced.

## 10. Recipe loading and tool contract

Recipes should live in a server directory such as:

```text
backend/recipes/
```

Recommended filename for the current recipe:

```text
orange-blue-mocktail.json
```

### `list_recipes`

Implementation:

* enumerate JSON files in the recipe directory
* return filename stem

Example return payload:

```json
[
  {
    "id": "orange-blue-mocktail"
  }
]
```

### `activate_recipe`

Implementation:

* load the JSON by `id`
* store it in session memory
* initialize:
  * task list
  * `current_step_id = start_step_id`
  * empty step-local state

## 11. Workflow definition model

The workflow engine should support these generic step evaluation modes:

* `match_value`
  Used for bottle color detection.
* `numeric_threshold_with_progress_once`
  Used for orange juice fill level.
* `count_rising_edges_true`
  Used for ice scoops.
* `enum_progress_once_then_complete`
  Used for Gatorade pouring.
* `momentary_true_complete`
  Used for lime placement.

### Internal steps for the current recipe

Internal steps:

1. `pick_orange_bottle`
2. `pour_orange_juice`
3. `add_ice`
4. `pick_blue_bottle`
5. `pour_gatorade`
6. `add_lime`

HUD task list is intentionally coarser:

1. `orange_juice`
2. `ice`
3. `gatorade`
4. `lime`

This means:

* both `pick_orange_bottle` and `pour_orange_juice` highlight `orange_juice`
* both `pick_blue_bottle` and `pour_gatorade` highlight `gatorade`

## 12. Complete recipe JSON

Suggested file:

```text
backend/recipes/orange-blue-mocktail.json
```

```json
{
  "id": "orange-blue-mocktail",
  "display_name": "Orange Blue Mocktail",
  "start_step_id": "pick_orange_bottle",
  "tasks": [
    {
      "id": "orange_juice",
      "text": "Add orange juice to halfway"
    },
    {
      "id": "ice",
      "text": "Add a few scoops of ice"
    },
    {
      "id": "gatorade",
      "text": "Fill with Gatorade"
    },
    {
      "id": "lime",
      "text": "Top with a lime wheel"
    }
  ],
  "inventory_scan": {
    "detector_key": "inventory_scan",
    "stabilization": {
      "type": "two_identical_consecutive_results",
      "normalization": "sort_unique_ingredients"
    }
  },
  "detectors": {
    "inventory_scan": {
      "prompt": "Return the visible ingredient list on the table as an array using only these values: \"orange juice\", \"blue drink\", \"lime\", \"ice\". Include an item only if it is clearly visible and available for use in the current scene. Do not infer hidden items or items outside the frame.",
      "output_schema": {
        "type": "object",
        "properties": {
          "ingredients": {
            "type": "array",
            "items": {
              "type": "string",
              "enum": [
                "orange juice",
                "blue drink",
                "lime",
                "ice"
              ]
            },
            "uniqueItems": true
          }
        },
        "required": [
          "ingredients"
        ],
        "additionalProperties": false
      }
    },
    "orange_fill_level": {
      "prompt": "Return the orange juice fill level of the glass on the table as 0 (empty) to 10 (completely full) only if juice is clearly being poured from a bottle into it now; otherwise, return \"unknown\".",
      "output_schema": {
        "type": "object",
        "properties": {
          "level": {
            "oneOf": [
              {
                "type": "integer",
                "minimum": 0,
                "maximum": 10,
                "description": "Estimated fill level of orange juice in the glass on the table, from 0 (empty) to 10 (completely full)."
              },
              {
                "type": "string",
                "enum": [
                  "unknown"
                ],
                "description": "Use when orange juice is not clearly being poured from a bottle into the glass at this moment, or when the fill level cannot be determined."
              }
            ]
          }
        },
        "required": [
          "level"
        ],
        "additionalProperties": false
      }
    },
    "ice_contact": {
      "prompt": "Return true only when ice from a spoon is visibly falling and touching the orange juice in the glass on the table at this moment; otherwise return false.",
      "output_schema": {
        "type": "boolean"
      }
    },
    "blue_pour_state": {
      "prompt": "Classify the current video clip into exactly one of these states:\n\n- \"no\": liquid from the blue bottle is not visibly touching or entering the inside of the glass on the table.\n- \"pouring\": liquid from the blue bottle has visibly left the bottle and is touching or entering the inside of the glass, but the glass is not nearly full.\n- \"pouring_nearly_full\": a blue bottle is clearly pouring into the glass right now, and the glass appears nearly full, close to the rim, about 90% full or more.\n\nRules:\n- Judge only the current moment.\n- Output \"pouring\" or \"pouring_nearly_full\" only when the liquid stream is visibly connected from the blue bottle to the inside of the glass.\n- The poured liquid may look light blue to transparent.\n- The drink in the glass may be colorful and not a single uniform color.",
      "output_schema": {
        "type": "string",
        "enum": [
          "no",
          "pouring",
          "pouring_nearly_full"
        ]
      }
    },
    "bottle_color": {
      "prompt": "Return the bottle color as orange, red, or blue only when the bottle is clearly being held by a hand in the air. If the hand is merely overlapping the bottle, passing in front of it, or if holding is not clearly visible, return unknown.",
      "output_schema": {
        "type": "string",
        "enum": [
          "orange",
          "red",
          "blue",
          "unknown"
        ]
      }
    },
    "lime_insert": {
      "prompt": "Return true only at the exact moment when a lime slice is being placed into the glass on the table; otherwise return false.",
      "output_schema": {
        "type": "boolean"
      }
    }
  },
  "steps": [
    {
      "id": "pick_orange_bottle",
      "task_id": "orange_juice",
      "evaluation_mode": "match_value",
      "detector_key": "bottle_color",
      "expected_value": "orange",
      "ignored_values": [
        "unknown"
      ],
      "speak_on_observation_change_only": true,
      "on_enter_speech": "Let's make a mocktail! Grab the orange bottle to get us started.",
      "mismatch_speech": "Almost. Grab the orange bottle.",
      "success_speech": "Nice. Pour the orange juice into the glass.",
      "next_step_id": "pour_orange_juice"
    },
    {
      "id": "pour_orange_juice",
      "task_id": "orange_juice",
      "evaluation_mode": "numeric_threshold_with_progress_once",
      "detector_key": "orange_fill_level",
      "value_path": "level",
      "ignore_values": [
        "unknown"
      ],
      "progress_condition": {
        "gte": 1,
        "lt": 5
      },
      "progress_once_speech": "Nice pour. Keep going until I tell you to stop.",
      "complete_condition": {
        "gte": 5
      },
      "complete_speech": "And stop there! Great start. Add two scoops of ice cubes to the glass.",
      "next_step_id": "add_ice"
    },
    {
      "id": "add_ice",
      "task_id": "ice",
      "evaluation_mode": "count_rising_edges_true",
      "detector_key": "ice_contact",
      "target_count": 2,
      "count_edge": "false_to_true",
      "rearm_condition": "false_seen",
      "milestones": [
        {
          "count": 1,
          "speech": "Nice. One scoop in, one more to go."
        },
        {
          "count": 2,
          "speech": "Perfect. That's enough ice. Now grab the blue bottle.",
          "next_step_id": "pick_blue_bottle"
        }
      ]
    },
    {
      "id": "pick_blue_bottle",
      "task_id": "gatorade",
      "evaluation_mode": "match_value",
      "detector_key": "bottle_color",
      "expected_value": "blue",
      "ignored_values": [
        "unknown"
      ],
      "speak_on_observation_change_only": true,
      "mismatch_speech": "Almost. Grab the blue bottle.",
      "success_speech": "Yes. Pour the Gatorade in slowly.",
      "next_step_id": "pour_gatorade"
    },
    {
      "id": "pour_gatorade",
      "task_id": "gatorade",
      "evaluation_mode": "enum_progress_once_then_complete",
      "detector_key": "blue_pour_state",
      "ignore_values": [
        "no"
      ],
      "progress_value": "pouring",
      "progress_once_speech": "Looking good. Just a little more.",
      "complete_value": "pouring_nearly_full",
      "complete_speech": "And stop there! That looks great. Top it with the lime wheel.",
      "next_step_id": "add_lime"
    },
    {
      "id": "add_lime",
      "task_id": "lime",
      "evaluation_mode": "momentary_true_complete",
      "detector_key": "lime_insert",
      "complete_on": true,
      "complete_speech": "Beautiful. Your mocktail is finished!",
      "next_step_id": null
    }
  ]
}
```

## 13. Suggested server module layout

Make a clean file structure, but you don't need to create too many small files.

# Ref.

[1]: https://developers.openai.com/api/docs/guides/realtime-server-controls/ "https://developers.openai.com/api/docs/guides/realtime-server-controls/"
[2]: https://docs.overshoot.ai/api-reference "https://docs.overshoot.ai/api-reference"
