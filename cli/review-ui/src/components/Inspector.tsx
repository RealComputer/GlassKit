import { Minus, Plus, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type RefObject } from "react";
import type { CompareMode, ExpectType, ReviewSample } from "../api/types.ts";
import { useApp } from "../state/AppContext.tsx";
import { SAMPLE_DURATION_TOLERANCE_S } from "../state/reducer.ts";
import { formatSeconds } from "../utils/format.ts";

const JSON_NUMBER = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/;
const allModes: { value: CompareMode; label: string }[] = [
  { value: "exact", label: "Exact" },
  { value: "numeric", label: "Numeric" },
  { value: "json_subset", label: "JSON subset" },
  { value: "set_equals", label: "Set equals" },
  { value: "set_contains_any", label: "Set contains any" },
  { value: "set_contains_all", label: "Set contains all" },
];

function allowedModes(type: ExpectType): CompareMode[] {
  if (type === "number") return ["exact", "numeric"];
  if (type === "array") {
    return ["exact", "json_subset", "set_equals", "set_contains_any", "set_contains_all"];
  }
  if (type === "object") return ["exact", "json_subset"];
  return ["exact"];
}

function defaultJson(type: ExpectType): string {
  return {
    null: "null",
    boolean: "false",
    number: "0",
    string: '""',
    array: "[]",
    object: "{}",
  }[type];
}

function editorText(sample: ReviewSample): string {
  if (!sample.has_expectation) return "";
  if (sample.expect_type !== "string") return sample.expect_json;
  try {
    return JSON.parse(sample.expect_json) as string;
  } catch {
    return sample.expect_json;
  }
}

function validateStructured(text: string, type: "array" | "object"): string | null {
  try {
    const parsed = JSON.parse(text) as unknown;
    const valid =
      type === "array"
        ? Array.isArray(parsed)
        : typeof parsed === "object" && parsed !== null && !Array.isArray(parsed);
    return valid ? null : `Enter a JSON ${type}.`;
  } catch (error) {
    return error instanceof SyntaxError ? error.message : "Enter valid JSON.";
  }
}

export function Inspector() {
  const { state, dispatch, updateSample, deleteSample, canDeleteSample, setFormError } = useApp();
  const workspace = state.selectedCaseId ? state.caseFileWorkspaces[state.selectedCaseId] : null;
  const target = workspace?.document.targets.find((item) => item.id === state.selectedTargetId);
  const sample = target?.samples.find((item) => item.id === state.selectedSampleId);
  const sampleRef = useRef(sample);
  sampleRef.current = sample;
  const workspaceRef = useRef(workspace);
  workspaceRef.current = workspace;
  const selectionKey = target && sample ? `${target.id}:${sample.id}` : null;
  const [timestamp, setTimestamp] = useState("");
  const [expectText, setExpectText] = useState("");
  const [field, setField] = useState("");
  const [tolerance, setTolerance] = useState("");
  const [comment, setComment] = useState("");
  const [ignoreSelected, setIgnoreSelected] = useState(false);
  const [ignore, setIgnore] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const expectationRef = useRef<HTMLTextAreaElement | HTMLInputElement | HTMLButtonElement>(null);
  const ignoreRef = useRef<HTMLTextAreaElement>(null);
  const autoFocusInProgressRef = useRef(false);

  useEffect(() => {
    const selected = sampleRef.current;
    if (!selected) return;
    setTimestamp(String(selected.timestamp_s));
    setExpectText(editorText(selected));
    setField(selected.field ?? "");
    setTolerance(selected.compare.tolerance === null ? "" : String(selected.compare.tolerance));
    setComment(selected.comment ?? "");
    setIgnoreSelected(selected.ignore !== null);
    setIgnore(selected.ignore ?? "");
    setErrors({});
  }, [selectionKey]);

  useEffect(() => {
    const selected = sampleRef.current;
    const currentWorkspace = workspaceRef.current;
    if (!selected || !selectionKey || !currentWorkspace) return;
    const hasError = (name: string) =>
      Boolean(currentWorkspace.formErrors[`${selectionKey}:${name}`]);
    if (!hasError("timestamp")) setTimestamp(String(selected.timestamp_s));
    if (!hasError("expect")) setExpectText(editorText(selected));
    setField(selected.field ?? "");
    if (!hasError("tolerance")) {
      setTolerance(selected.compare.tolerance === null ? "" : String(selected.compare.tolerance));
    }
    setComment(selected.comment ?? "");
    if (!hasError("ignore")) {
      setIgnoreSelected(selected.ignore !== null);
      setIgnore(selected.ignore ?? "");
    }
    if (!["timestamp", "expect", "tolerance", "ignore"].some(hasError)) setErrors({});
  }, [selectionKey, workspace?.acceptedCaseFile]);

  useEffect(() => {
    if (sample?.origin !== null) return;
    const frame = requestAnimationFrame(() => {
      const editor = expectationRef.current;
      if (!editor) return;
      autoFocusInProgressRef.current = true;
      try {
        editor.focus();
      } finally {
        autoFocusInProgressRef.current = false;
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [sample?.id, sample?.origin]);

  const errorKey = (name: string) => `${target?.id}:${sample?.id}:${name}`;
  const setError = (name: string, message: string | null) => {
    setErrors((current) => {
      const next = { ...current };
      if (message) next[name] = message;
      else delete next[name];
      return next;
    });
    setFormError(errorKey(name), message);
  };

  const duration = workspace?.document.video?.duration_s ?? null;
  const validateTimestamp = (value: string): number | null => {
    const parsed = Number(value);
    let error: string | null = null;
    if (!value.trim() || !Number.isFinite(parsed)) error = "Enter a finite time.";
    else if (parsed < 0) error = "Time cannot be negative.";
    else if (duration !== null && parsed > duration + SAMPLE_DURATION_TOLERANCE_S) {
      error = `Time must not exceed ${duration.toFixed(3)} seconds.`;
    } else if (
      target?.samples.some(
        (item) => item.id !== sample?.id && Math.abs(item.timestamp_s - parsed) <= 1e-9,
      )
    ) {
      error = "Another sample already uses this time.";
    }
    setError("timestamp", error);
    return error ? null : parsed;
  };

  const changeTimestamp = (value: string, immediate = false) => {
    setTimestamp(value);
    const parsed = validateTimestamp(value);
    if (parsed !== null && sample && target) {
      updateSample(target.id, sample.id, { timestamp_s: parsed }, immediate);
    }
  };

  const changeExpect = (value: string, immediate = false) => {
    if (!sample || !target) return;
    setExpectText(value);
    let error: string | null = null;
    let expectJson = value;
    if (sample.expect_type === "number") {
      if (!JSON_NUMBER.test(value)) error = "Enter a valid JSON number.";
      else if ((value.includes(".") || /[eE]/.test(value)) && !Number.isFinite(Number(value))) {
        error = "Enter a finite JSON number.";
      }
    } else if (sample.expect_type === "string") {
      expectJson = JSON.stringify(value);
    } else if (sample.expect_type === "array" || sample.expect_type === "object") {
      error = validateStructured(value, sample.expect_type);
    }
    setError("expect", error);
    if (!error) {
      updateSample(target.id, sample.id, { expect_json: expectJson }, immediate);
    }
  };

  const changeType = (type: ExpectType) => {
    if (!sample || !target) return;
    const allowed = allowedModes(type);
    const modeCompatible = sample.compare.mode === null || allowed.includes(sample.compare.mode);
    const compare = {
      mode: modeCompatible ? sample.compare.mode : null,
      tolerance:
        type === "number" && (modeCompatible ? sample.compare.mode : null) !== "exact"
          ? sample.compare.tolerance
          : null,
    };
    const expect_json = defaultJson(type);
    setExpectText(type === "string" ? "" : expect_json);
    setTolerance(compare.tolerance === null ? "" : String(compare.tolerance));
    setError("expect", null);
    setError("tolerance", null);
    updateSample(
      target.id,
      sample.id,
      { has_expectation: true, expect_type: type, expect_json, compare },
      true,
    );
    if (!modeCompatible || sample.compare.tolerance !== compare.tolerance) {
      dispatch({
        type: "SET_TOAST",
        value: "Comparison settings were reset for the new expectation type.",
      });
    }
    requestAnimationFrame(() => expectationRef.current?.focus());
  };

  const comparisonOptions = (() => {
    if (!sample) return [];
    const allowed = allowedModes(sample.expect_type);
    const options = allModes.filter((item) => allowed.includes(item.value));
    if (sample.compare.mode && !options.some((item) => item.value === sample.compare.mode)) {
      options.unshift({
        value: sample.compare.mode,
        label: `Current: ${sample.compare.mode}`,
      });
    }
    return options;
  })();

  const editingDisabled = !workspace?.document.editing_enabled;
  const pauseForEditing = () => {
    if (autoFocusInProgressRef.current) return;
    const video = globalThis.document.querySelector("video");
    if (video && !video.paused) video.pause();
  };
  const followControl = (
    <label className="toggle-control follow-playhead-control" htmlFor="follow-playhead">
      <input
        id="follow-playhead"
        type="checkbox"
        checked={state.followPlayhead}
        onChange={(event) => dispatch({ type: "SET_FOLLOW_PLAYHEAD", value: event.target.checked })}
      />
      Follow playhead
    </label>
  );

  if (!sample || !target || !workspace) {
    return (
      <aside className="inspector">
        <div className="inspector-heading">
          <div className="inspector-title">
            <h2>Inspector</h2>
          </div>
          {followControl}
        </div>
        <div className="empty-state">Select a sample to inspect its expectation.</div>
      </aside>
    );
  }

  const numericTolerance =
    sample.expect_type === "number" &&
    (sample.compare.mode === null || sample.compare.mode === "numeric");

  return (
    <aside className="inspector" aria-label="Sample inspector">
      <div className="inspector-heading">
        <div className="inspector-title">
          <h2>Inspector</h2>
          <span className="mono muted">{formatSeconds(sample.timestamp_s)}</span>
        </div>
        <div className="inspector-heading-actions">
          {followControl}
          <span className="type-chip">{sample.has_expectation ? sample.expect_type : "draft"}</span>
        </div>
      </div>
      <fieldset disabled={editingDisabled} onFocusCapture={pauseForEditing}>
        <div className="field-group">
          <label htmlFor="sample-time">Timestamp</label>
          <div className="timestamp-editor">
            <input
              id="sample-time"
              className="mono"
              type="number"
              min="0"
              max={duration === null ? undefined : duration + SAMPLE_DURATION_TOLERANCE_S}
              step="0.001"
              value={timestamp}
              aria-invalid={Boolean(errors.timestamp)}
              onChange={(event) => changeTimestamp(event.target.value)}
              onBlur={(event) => changeTimestamp(event.target.value, true)}
            />
            {([-1, -0.1, 0.1, 1] as const).map((delta) => (
              <button
                key={delta}
                type="button"
                className="nudge-button mono"
                onClick={() =>
                  changeTimestamp(
                    String(
                      Math.min(
                        duration ?? Number.POSITIVE_INFINITY,
                        Math.max(0, sample.timestamp_s + delta),
                      ),
                    ),
                    true,
                  )
                }
                aria-label={`${delta > 0 ? "Add" : "Subtract"} ${Math.abs(delta)} seconds`}
              >
                {delta < 0 ? <Minus size={12} /> : <Plus size={12} />}
                {Math.abs(delta).toFixed(1)}
              </button>
            ))}
          </div>
          {errors.timestamp && <p className="field-error">{errors.timestamp}</p>}
        </div>

        <div className="field-group">
          <label htmlFor="expect-type">Expectation type</label>
          <select
            id="expect-type"
            value={sample.has_expectation ? sample.expect_type : ""}
            onChange={(event) => changeType(event.target.value as ExpectType)}
          >
            {!sample.has_expectation && (
              <option value="" disabled>
                Draft (missing)
              </option>
            )}
            <option value="null">Null</option>
            <option value="boolean">Boolean</option>
            <option value="number">Number</option>
            <option value="string">String</option>
            <option value="array">Array</option>
            <option value="object">Object</option>
          </select>
        </div>

        <div className="field-group">
          {sample.expect_type === "null" || sample.expect_type === "boolean" ? (
            <span className="field-label" id="expect-value-label">
              Expected value
            </span>
          ) : (
            <label htmlFor="expect-value">Expected value</label>
          )}
          {!sample.has_expectation ? (
            <div className="draft-expectation">Choose a type to set this draft expectation.</div>
          ) : sample.expect_type === "null" ? (
            <div className="null-value mono" aria-labelledby="expect-value-label">
              null
            </div>
          ) : sample.expect_type === "boolean" ? (
            <div
              className="segmented boolean-control"
              role="group"
              aria-labelledby="expect-value-label"
            >
              <button
                type="button"
                ref={expectationRef as RefObject<HTMLButtonElement>}
                className={sample.expect_json === "true" ? "selected" : ""}
                aria-pressed={sample.expect_json === "true"}
                onClick={() =>
                  updateSample(
                    target.id,
                    sample.id,
                    { has_expectation: true, expect_json: "true" },
                    true,
                  )
                }
              >
                True
              </button>
              <button
                type="button"
                className={sample.expect_json === "false" ? "selected" : ""}
                aria-pressed={sample.expect_json === "false"}
                onClick={() =>
                  updateSample(
                    target.id,
                    sample.id,
                    { has_expectation: true, expect_json: "false" },
                    true,
                  )
                }
              >
                False
              </button>
            </div>
          ) : sample.expect_type === "string" ? (
            <textarea
              id="expect-value"
              ref={expectationRef as RefObject<HTMLTextAreaElement>}
              rows={3}
              value={expectText}
              onChange={(event) => changeExpect(event.target.value)}
              onBlur={(event) => changeExpect(event.target.value, true)}
            />
          ) : sample.expect_type === "array" || sample.expect_type === "object" ? (
            <textarea
              id="expect-value"
              ref={expectationRef as RefObject<HTMLTextAreaElement>}
              className="mono json-editor"
              rows={7}
              value={expectText}
              spellCheck={false}
              aria-invalid={Boolean(errors.expect)}
              onChange={(event) => changeExpect(event.target.value)}
              onBlur={(event) => changeExpect(event.target.value, true)}
            />
          ) : (
            <input
              id="expect-value"
              ref={expectationRef as RefObject<HTMLInputElement>}
              className="mono"
              type="text"
              inputMode="decimal"
              value={expectText}
              aria-invalid={Boolean(errors.expect)}
              onChange={(event) => changeExpect(event.target.value)}
              onBlur={(event) => changeExpect(event.target.value, true)}
            />
          )}
          {errors.expect && <p className="field-error">{errors.expect}</p>}
        </div>

        <div className="field-group">
          <label htmlFor="field-path">
            Field <span className="optional">optional</span>
          </label>
          <input
            id="field-path"
            className="mono"
            type="text"
            value={field}
            onChange={(event) => {
              const value = event.target.value;
              setField(value);
              updateSample(target.id, sample.id, {
                field: value.trim() ? value : null,
              });
            }}
            onBlur={() => {
              const value = field.trim();
              setField(value);
              updateSample(target.id, sample.id, { field: value || null }, true);
            }}
          />
        </div>

        <div className="field-row">
          <div className="field-group">
            <label htmlFor="compare-mode">Comparison</label>
            <select
              id="compare-mode"
              value={sample.compare.mode ?? ""}
              onChange={(event) => {
                const mode = (event.target.value || null) as CompareMode | null;
                const nextTolerance =
                  sample.expect_type === "number" && (mode === null || mode === "numeric")
                    ? sample.compare.tolerance
                    : null;
                if (nextTolerance === null) setTolerance("");
                updateSample(
                  target.id,
                  sample.id,
                  { compare: { mode, tolerance: nextTolerance } },
                  true,
                );
              }}
            >
              <option value="">Auto</option>
              {comparisonOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field-group">
            <label htmlFor="tolerance">Tolerance</label>
            <input
              id="tolerance"
              className="mono"
              type="number"
              min="0"
              step="any"
              disabled={!numericTolerance || editingDisabled}
              value={tolerance}
              aria-invalid={Boolean(errors.tolerance)}
              onChange={(event) => {
                const value = event.target.value;
                setTolerance(value);
                const parsed = Number(value);
                const error =
                  value && (!Number.isFinite(parsed) || parsed < 0)
                    ? "Use a nonnegative finite number."
                    : null;
                setError("tolerance", error);
                if (!error) {
                  updateSample(target.id, sample.id, {
                    compare: {
                      ...sample.compare,
                      tolerance: value ? parsed : null,
                    },
                  });
                }
              }}
              onBlur={(event) => {
                const value = event.target.value;
                const parsed = Number(value);
                if (!value || (Number.isFinite(parsed) && parsed >= 0)) {
                  updateSample(
                    target.id,
                    sample.id,
                    {
                      compare: {
                        ...sample.compare,
                        tolerance: value ? parsed : null,
                      },
                    },
                    true,
                  );
                }
              }}
            />
            {errors.tolerance && <p className="field-error">{errors.tolerance}</p>}
          </div>
        </div>

        <div className="field-group">
          <label className="ignore-toggle" htmlFor="sample-ignored">
            <input
              id="sample-ignored"
              type="checkbox"
              checked={ignoreSelected}
              onChange={(event) => {
                if (event.target.checked) {
                  setIgnoreSelected(true);
                  setError("ignore", "Enter a reason for ignoring this sample.");
                  requestAnimationFrame(() => ignoreRef.current?.focus());
                  return;
                }
                setIgnoreSelected(false);
                setIgnore("");
                setError("ignore", null);
                updateSample(target.id, sample.id, { ignore: null }, true);
              }}
            />
            Ignore this sample
          </label>
          {ignoreSelected && (
            <div className="ignore-reason">
              <label htmlFor="sample-ignore">Ignore reason</label>
              <textarea
                ref={ignoreRef}
                id="sample-ignore"
                rows={2}
                value={ignore}
                required
                aria-invalid={Boolean(errors.ignore)}
                aria-describedby="sample-ignore-help"
                onChange={(event) => {
                  const value = event.target.value;
                  const reason = value.trim();
                  setIgnore(value);
                  setError("ignore", reason ? null : "Enter a reason for ignoring this sample.");
                  if (reason) {
                    updateSample(target.id, sample.id, { ignore: reason });
                  }
                }}
                onBlur={() => {
                  const reason = ignore.trim();
                  setIgnore(reason);
                  setError("ignore", reason ? null : "Enter a reason for ignoring this sample.");
                  if (reason) {
                    updateSample(target.id, sample.id, { ignore: reason }, true);
                  }
                }}
              />
              {errors.ignore && <p className="field-error">{errors.ignore}</p>}
              <p id="sample-ignore-help" className="field-help">
                Ignored samples are skipped during eval runs and excluded from quality gates.
              </p>
            </div>
          )}
        </div>

        <div className="field-group">
          <label htmlFor="sample-comment">
            Comment <span className="optional">optional</span>
          </label>
          <textarea
            id="sample-comment"
            rows={3}
            value={comment}
            onChange={(event) => {
              const value = event.target.value;
              setComment(value);
              updateSample(target.id, sample.id, {
                comment: value.trim() ? value : null,
              });
            }}
            onBlur={() => {
              const value = comment.trim();
              setComment(value);
              updateSample(target.id, sample.id, { comment: value || null }, true);
            }}
          />
        </div>

        {(workspace.saveError || workspace.saveDetails.length > 0) && (
          <div className="backend-errors" role="alert">
            {workspace.saveError && <p>{workspace.saveError}</p>}
            {workspace.saveDetails.map((detail, index) => (
              <p key={`${detail.path ?? "error"}-${index}`}>
                {detail.path && <code>{detail.path}</code>} {detail.message}
              </p>
            ))}
          </div>
        )}

        <button
          type="button"
          className="button danger-button delete-button"
          disabled={!canDeleteSample(target.id, sample.id) || editingDisabled}
          onClick={() => deleteSample(target.id, sample.id)}
          title={
            canDeleteSample(target.id, sample.id)
              ? "Delete this sample"
              : "A valid target must keep at least one sample"
          }
        >
          <Trash2 size={16} /> Delete sample
        </button>
      </fieldset>
      {editingDisabled && (
        <div className="inline-warning">
          Editing is disabled until this case and its video can be loaded.
        </div>
      )}
    </aside>
  );
}
