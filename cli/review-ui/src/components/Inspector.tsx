import { Minus, Plus, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState, type RefObject } from 'react'
import type {
  CompareMode,
  ExpectType,
  ReviewPoint,
} from '../api/types.ts'
import { useApp } from '../state/AppContext.tsx'
import { formatSeconds } from '../utils/format.ts'

const JSON_NUMBER = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/
const allModes: { value: CompareMode; label: string }[] = [
  { value: 'exact', label: 'Exact' },
  { value: 'numeric', label: 'Numeric' },
  { value: 'json_subset', label: 'JSON subset' },
  { value: 'set_equals', label: 'Set equals' },
  { value: 'set_contains_any', label: 'Set contains any' },
  { value: 'set_contains_all', label: 'Set contains all' },
]

function allowedModes(type: ExpectType): CompareMode[] {
  if (type === 'number') return ['exact', 'numeric']
  if (type === 'array') {
    return [
      'exact',
      'json_subset',
      'set_equals',
      'set_contains_any',
      'set_contains_all',
    ]
  }
  if (type === 'object') return ['exact', 'json_subset']
  return ['exact']
}

function defaultJson(type: ExpectType): string {
  return {
    null: 'null',
    boolean: 'false',
    number: '0',
    string: '""',
    array: '[]',
    object: '{}',
  }[type]
}

function editorText(point: ReviewPoint): string {
  if (point.expect_type !== 'string') return point.expect_json
  try {
    return JSON.parse(point.expect_json) as string
  } catch {
    return point.expect_json
  }
}

function validateStructured(text: string, type: 'array' | 'object'): string | null {
  try {
    const parsed = JSON.parse(text) as unknown
    const valid =
      type === 'array'
        ? Array.isArray(parsed)
        : typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
    return valid ? null : `Enter a JSON ${type}.`
  } catch (error) {
    return error instanceof SyntaxError ? error.message : 'Enter valid JSON.'
  }
}

export function Inspector() {
  const {
    state,
    dispatch,
    updatePoint,
    deletePoint,
    canDeletePoint,
    setFormError,
  } = useApp()
  const workspace = state.selectedCaseId
    ? state.documents[state.selectedCaseId]
    : null
  const target = workspace?.document.targets.find(
    (item) => item.id === state.selectedTargetId,
  )
  const point = target?.points.find((item) => item.id === state.selectedPointId)
  const [timestamp, setTimestamp] = useState('')
  const [expectText, setExpectText] = useState('')
  const [field, setField] = useState('')
  const [tolerance, setTolerance] = useState('')
  const [comment, setComment] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const expectationRef = useRef<
    HTMLTextAreaElement | HTMLInputElement | HTMLButtonElement
  >(null)

  useEffect(() => {
    if (!point) return
    setTimestamp(String(point.timestamp_s))
    setExpectText(editorText(point))
    setField(point.field ?? '')
    setTolerance(
      point.compare.tolerance === null ? '' : String(point.compare.tolerance),
    )
    setComment(point.comment ?? '')
    setErrors({})
  }, [point])

  useEffect(() => {
    if (point?.origin === null) {
      requestAnimationFrame(() => expectationRef.current?.focus())
    }
  }, [point?.id, point?.origin])

  const errorKey = (name: string) => `${target?.id}:${point?.id}:${name}`
  const setError = (name: string, message: string | null) => {
    setErrors((current) => {
      const next = { ...current }
      if (message) next[name] = message
      else delete next[name]
      return next
    })
    setFormError(errorKey(name), message)
  }

  const duration = workspace?.document.video?.duration_s ?? null
  const validateTimestamp = (value: string): number | null => {
    const parsed = Number(value)
    let error: string | null = null
    if (!value.trim() || !Number.isFinite(parsed)) error = 'Enter a finite time.'
    else if (parsed < 0) error = 'Time cannot be negative.'
    else if (duration !== null && parsed > duration + 1e-9) {
      error = `Time must not exceed ${duration.toFixed(3)} seconds.`
    } else if (
      target?.points.some(
        (item) => item.id !== point?.id && Math.abs(item.timestamp_s - parsed) <= 1e-9,
      )
    ) {
      error = 'Another point already uses this time.'
    }
    setError('timestamp', error)
    return error ? null : parsed
  }

  const changeTimestamp = (value: string, immediate = false) => {
    setTimestamp(value)
    const parsed = validateTimestamp(value)
    if (parsed !== null && point && target) {
      updatePoint(target.id, point.id, { timestamp_s: parsed }, immediate)
    }
  }

  const changeExpect = (value: string, immediate = false) => {
    if (!point || !target) return
    setExpectText(value)
    let error: string | null = null
    let expectJson = value
    if (point.expect_type === 'number') {
      if (!JSON_NUMBER.test(value)) error = 'Enter a valid JSON number.'
      else if (
        (value.includes('.') || /[eE]/.test(value)) &&
        !Number.isFinite(Number(value))
      ) {
        error = 'Enter a finite JSON number.'
      }
    } else if (point.expect_type === 'string') {
      expectJson = JSON.stringify(value)
    } else if (point.expect_type === 'array' || point.expect_type === 'object') {
      error = validateStructured(value, point.expect_type)
    }
    setError('expect', error)
    if (!error) {
      updatePoint(target.id, point.id, { expect_json: expectJson }, immediate)
    }
  }

  const changeType = (type: ExpectType) => {
    if (!point || !target) return
    const allowed = allowedModes(type)
    const modeCompatible =
      point.compare.mode === null || allowed.includes(point.compare.mode)
    const compare = {
      mode: modeCompatible ? point.compare.mode : null,
      tolerance:
        type === 'number' &&
        (modeCompatible ? point.compare.mode : null) !== 'exact'
          ? point.compare.tolerance
          : null,
    }
    const expect_json = defaultJson(type)
    setExpectText(type === 'string' ? '' : expect_json)
    setTolerance(compare.tolerance === null ? '' : String(compare.tolerance))
    setError('expect', null)
    setError('tolerance', null)
    updatePoint(
      target.id,
      point.id,
      { expect_type: type, expect_json, compare },
      true,
    )
    if (!modeCompatible || point.compare.tolerance !== compare.tolerance) {
      dispatch({
        type: 'SET_TOAST',
        value: 'Comparison settings were reset for the new expectation type.',
      })
    }
    requestAnimationFrame(() => expectationRef.current?.focus())
  }

  const comparisonOptions = (() => {
    if (!point) return []
    const allowed = allowedModes(point.expect_type)
    const options = allModes.filter((item) => allowed.includes(item.value))
    if (
      point.compare.mode &&
      !options.some((item) => item.value === point.compare.mode)
    ) {
      options.unshift({
        value: point.compare.mode,
        label: `Current: ${point.compare.mode}`,
      })
    }
    return options
  })()

  const group = target?.display_groups.find((item) =>
    point ? item.point_ids.includes(point.id) : false,
  )
  const editingDisabled = !workspace?.document.editing_enabled

  if (!point || !target || !workspace) {
    return (
      <aside className="inspector">
        <div className="inspector-heading">
          <h2>Inspector</h2>
        </div>
        <div className="empty-state">Select a sample to inspect its expectation.</div>
      </aside>
    )
  }

  const numericTolerance =
    point.expect_type === 'number' &&
    (point.compare.mode === null || point.compare.mode === 'numeric')

  return (
    <aside className="inspector" aria-label="Sample inspector">
      <div className="inspector-heading">
        <div>
          <h2>Inspector</h2>
          <span className="mono muted">{formatSeconds(point.timestamp_s)}</span>
        </div>
        <span className="type-chip">{point.expect_type}</span>
      </div>
      <fieldset disabled={editingDisabled}>
        <div className="field-group">
          <label htmlFor="sample-time">Timestamp</label>
          <div className="timestamp-editor">
            <input
              id="sample-time"
              className="mono"
              type="number"
              min="0"
              max={duration ?? undefined}
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
                        Math.max(0, point.timestamp_s + delta),
                      ),
                    ),
                    true,
                  )
                }
                aria-label={`${delta > 0 ? 'Add' : 'Subtract'} ${Math.abs(delta)} seconds`}
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
            value={point.expect_type}
            onChange={(event) => changeType(event.target.value as ExpectType)}
          >
            <option value="null">Null</option>
            <option value="boolean">Boolean</option>
            <option value="number">Number</option>
            <option value="string">String</option>
            <option value="array">Array</option>
            <option value="object">Object</option>
          </select>
        </div>

        <div className="field-group">
          <label htmlFor="expect-value">Expected value</label>
          {point.expect_type === 'null' ? (
            <div className="null-value mono">null</div>
          ) : point.expect_type === 'boolean' ? (
            <div className="segmented boolean-control" id="expect-value">
              <button
                type="button"
                ref={expectationRef as RefObject<HTMLButtonElement>}
                className={point.expect_json === 'true' ? 'selected' : ''}
                aria-pressed={point.expect_json === 'true'}
                onClick={() =>
                  updatePoint(target.id, point.id, { expect_json: 'true' }, true)
                }
              >
                True
              </button>
              <button
                type="button"
                className={point.expect_json === 'false' ? 'selected' : ''}
                aria-pressed={point.expect_json === 'false'}
                onClick={() =>
                  updatePoint(target.id, point.id, { expect_json: 'false' }, true)
                }
              >
                False
              </button>
            </div>
          ) : point.expect_type === 'string' ? (
            <textarea
              id="expect-value"
              ref={expectationRef as RefObject<HTMLTextAreaElement>}
              rows={3}
              value={expectText}
              onChange={(event) => changeExpect(event.target.value)}
              onBlur={(event) => changeExpect(event.target.value, true)}
            />
          ) : point.expect_type === 'array' || point.expect_type === 'object' ? (
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
          <label htmlFor="field-path">Field <span className="optional">optional</span></label>
          <input
            id="field-path"
            className="mono"
            type="text"
            value={field}
            placeholder="result.matches"
            onChange={(event) => {
              const value = event.target.value
              setField(value)
              updatePoint(target.id, point.id, {
                field: value.trim() ? value : null,
              })
            }}
            onBlur={() => {
              const value = field.trim()
              setField(value)
              updatePoint(target.id, point.id, { field: value || null }, true)
            }}
          />
        </div>

        <div className="field-row">
          <div className="field-group">
            <label htmlFor="compare-mode">Comparison</label>
            <select
              id="compare-mode"
              value={point.compare.mode ?? ''}
              onChange={(event) => {
                const mode = (event.target.value || null) as CompareMode | null
                const nextTolerance =
                  point.expect_type === 'number' &&
                  (mode === null || mode === 'numeric')
                    ? point.compare.tolerance
                    : null
                if (nextTolerance === null) setTolerance('')
                updatePoint(
                  target.id,
                  point.id,
                  { compare: { mode, tolerance: nextTolerance } },
                  true,
                )
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
                const value = event.target.value
                setTolerance(value)
                const parsed = Number(value)
                const error =
                  value && (!Number.isFinite(parsed) || parsed < 0)
                    ? 'Use a nonnegative finite number.'
                    : null
                setError('tolerance', error)
                if (!error) {
                  updatePoint(target.id, point.id, {
                    compare: {
                      ...point.compare,
                      tolerance: value ? parsed : null,
                    },
                  })
                }
              }}
              onBlur={(event) => {
                const value = event.target.value
                const parsed = Number(value)
                if (!value || (Number.isFinite(parsed) && parsed >= 0)) {
                  updatePoint(
                    target.id,
                    point.id,
                    {
                      compare: {
                        ...point.compare,
                        tolerance: value ? parsed : null,
                      },
                    },
                    true,
                  )
                }
              }}
            />
            {errors.tolerance && (
              <p className="field-error">{errors.tolerance}</p>
            )}
          </div>
        </div>

        <div className="field-group">
          <label htmlFor="sample-comment">Comment <span className="optional">optional</span></label>
          <textarea
            id="sample-comment"
            rows={3}
            value={comment}
            onChange={(event) => {
              const value = event.target.value
              setComment(value)
              updatePoint(target.id, point.id, {
                comment: value.trim() ? value : null,
              })
            }}
            onBlur={() => {
              const value = comment.trim()
              setComment(value)
              updatePoint(target.id, point.id, { comment: value || null }, true)
            }}
          />
        </div>

        {group && (
          <div className="derived-group">
            <span>Serialized group</span>
            <strong>{group.kind === 'range' ? 'Range' : 'At points'}</strong>
            <small>
              {group.point_ids.length} point{group.point_ids.length === 1 ? '' : 's'}
              {group.every_s !== null && ` · every ${group.every_s}s`}
            </small>
          </div>
        )}

        {workspace.saveDetails.length > 0 && (
          <div className="backend-errors" role="alert">
            {workspace.saveDetails.map((detail, index) => (
              <p key={`${detail.path ?? 'error'}-${index}`}>
                {detail.path && <code>{detail.path}</code>} {detail.message}
              </p>
            ))}
          </div>
        )}

        <button
          type="button"
          className="button danger-button delete-button"
          disabled={!canDeletePoint(target.id, point.id) || editingDisabled}
          onClick={() => deletePoint(target.id, point.id)}
          title={
            canDeletePoint(target.id, point.id)
              ? 'Delete this point'
              : 'A valid target must keep at least one point'
          }
        >
          <Trash2 size={16} /> Delete point
        </button>
      </fieldset>
      {editingDisabled && (
        <div className="inline-warning">
          Editing is disabled until this case and its video can be loaded.
        </div>
      )}
    </aside>
  )
}
