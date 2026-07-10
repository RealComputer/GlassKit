import { describe, expect, it } from 'vitest'
import { document, point, target } from '../test/fixtures.ts'
import { appReducer, initialState, isRepairComplete } from './reducer.ts'

function loadedState() {
  const doc = document()
  return appReducer(
    { ...initialState, selectedCaseId: doc.id },
    { type: 'CASE_LOADED', document: doc },
  )
}

describe('appReducer save ordering', () => {
  it('caches a late case response without stealing active selection or video state', () => {
    const active = {
      ...document([target('active_target', [point('active-point', 4)])]),
      id: 'active.yaml',
      name: 'active',
    }
    const late = {
      ...document([target('late_target', [point('late-point', 8)])]),
      id: 'late.yaml',
      name: 'late',
    }
    let state = appReducer(
      { ...initialState, selectedCaseId: active.id },
      { type: 'CASE_LOADED', document: active },
    )
    state = appReducer(state, { type: 'CASE_LOADED', document: late })
    expect(state.documents).toHaveProperty(late.id)
    expect(state.selectedCaseId).toBe(active.id)
    expect(state.selectedTargetId).toBe('active_target')
    expect(state.selectedPointId).toBe('active-point')
    expect(state.video.currentTime).toBe(4)
  })

  it('selects and seeks the first point when a target receives focus', () => {
    let state = loadedState()
    const generation = state.video.seekRequest.generation
    state = appReducer(state, { type: 'SELECT_TARGET', targetId: 'target_b' })
    expect(state.selectedPointId).toBe('target_b-point')
    expect(state.video.currentTime).toBe(1)
    expect(state.video.seekRequest).toEqual({
      generation: generation + 1,
      time: 1,
      sampleTime: 1,
    })
  })

  it('reloads retained selection at its point and refreshes the media element', () => {
    const original = document([
      target('target_a', [point('first', 1), point('retained', 7)]),
    ])
    let state = appReducer(
      { ...initialState, selectedCaseId: original.id },
      { type: 'CASE_LOADED', document: original },
    )
    state = appReducer(state, {
      type: 'SELECT_POINT',
      targetId: 'target_a',
      pointId: 'retained',
      timestamp: 7,
    })
    const mediaGeneration = state.video.mediaGeneration
    const reloaded = {
      ...original,
      revision: 'reloaded',
      video: original.video
        ? { ...original.video, display_path: 'replacement.mp4' }
        : null,
    }

    state = appReducer(state, { type: 'DISCARD_AND_LOAD', document: reloaded })

    expect(state.selectedPointId).toBe('retained')
    expect(state.video.currentTime).toBe(7)
    expect(state.video.seekRequest.time).toBe(7)
    expect(state.video.seekRequest.sampleTime).toBe(7)
    expect(state.video.mediaGeneration).toBe(mediaGeneration + 1)
  })

  it('keeps a newer local edit when an older response arrives', () => {
    let state = loadedState()
    const caseId = 'case-001.yaml'
    state = appReducer(state, {
      type: 'REPLACE_TARGET_POINTS',
      caseId,
      targetId: 'target_a',
      points: [point('target_a-point', 2, 'true')],
      immediate: true,
    })
    const submittedVersion = state.documents[caseId].versions.target_a
    state = appReducer(state, { type: 'SAVE_START', caseId })
    state = appReducer(state, {
      type: 'REPLACE_TARGET_POINTS',
      caseId,
      targetId: 'target_a',
      points: [point('target_a-point', 3, 'true')],
      immediate: false,
    })
    const serverDocument = document([
      target('target_a', [point('target_a-point', 2, 'true')]),
      target('target_b', [point('target_b-point', 4, 'true')]),
    ])
    state = appReducer(state, {
      type: 'SAVE_SUCCESS',
      caseId,
      document: serverDocument,
      submittedVersions: { target_a: submittedVersion },
    })

    expect(
      state.documents[caseId].document.targets[0].points[0].timestamp_s,
    ).toBe(3)
    expect(state.documents[caseId].dirtyTargetIds).toEqual(['target_a'])
    expect(state.documents[caseId].savePhase).toBe('unsaved')
    expect(state.documents[caseId].acceptedDocument.revision).toBe('revision-1')
  })

  it('does not overwrite an unsent dirty target with a full-case response', () => {
    let state = loadedState()
    const caseId = 'case-001.yaml'
    state = appReducer(state, {
      type: 'REPLACE_TARGET_POINTS',
      caseId,
      targetId: 'target_a',
      points: [point('target_a-point', 2)],
      immediate: true,
    })
    const versionA = state.documents[caseId].versions.target_a
    state = appReducer(state, {
      type: 'REPLACE_TARGET_POINTS',
      caseId,
      targetId: 'target_b',
      points: [point('target_b-point', 8, 'true')],
      immediate: true,
    })
    state = appReducer(state, {
      type: 'SAVE_SUCCESS',
      caseId,
      document: document([
        target('target_a', [point('target_a-point', 2)]),
        target('target_b', [point('target_b-point', 1)]),
      ]),
      submittedVersions: { target_a: versionA },
    })

    expect(
      state.documents[caseId].document.targets[1].points[0].timestamp_s,
    ).toBe(8)
    expect(state.documents[caseId].dirtyTargetIds).toEqual(['target_b'])
  })

  it('does not report Saved when an invalid field draft appeared in flight', () => {
    let state = loadedState()
    const caseId = 'case-001.yaml'
    state = appReducer(state, {
      type: 'REPLACE_TARGET_POINTS',
      caseId,
      targetId: 'target_a',
      points: [point('target_a-point', 2)],
      immediate: true,
    })
    const version = state.documents[caseId].versions.target_a
    state = appReducer(state, {
      type: 'SET_FORM_ERROR',
      key: 'target_a:target_a-point:expect',
      message: 'Enter valid JSON.',
    })
    state = appReducer(state, {
      type: 'SAVE_SUCCESS',
      caseId,
      document: document([
        target('target_a', [point('target_a-point', 2)]),
        target('target_b'),
      ]),
      submittedVersions: { target_a: version },
    })
    expect(state.documents[caseId].savePhase).toBe('invalid')
    expect(state.documents[caseId].formErrors).toHaveProperty(
      'target_a:target_a-point:expect',
    )
  })

  it('holds a repair draft until all targets have valid bounded points', () => {
    const repairDocument = document([target('empty', []), target('too_late', [point('late', 11)])])
    const state = appReducer(
      { ...initialState, selectedCaseId: repairDocument.id },
      { type: 'CASE_LOADED', document: repairDocument },
    )
    expect(isRepairComplete(state.documents[repairDocument.id])).toBe(false)
  })

  it('accepts the eval validator tolerance just beyond nominal duration', () => {
    const nearEnd = document([target('near_end', [point('end', 10.01)])])
    const state = appReducer(
      { ...initialState, selectedCaseId: nearEnd.id },
      { type: 'CASE_LOADED', document: nearEnd },
    )
    expect(isRepairComplete(state.documents[nearEnd.id])).toBe(true)
  })

  it('cancels an unsaved first point without leaving an empty PUT draft', () => {
    const empty = document([target('empty', [])])
    let state = appReducer(
      { ...initialState, selectedCaseId: empty.id },
      { type: 'CASE_LOADED', document: empty },
    )
    state = appReducer(state, {
      type: 'REPLACE_TARGET_POINTS',
      caseId: empty.id,
      targetId: 'empty',
      points: [point('new', 1)],
      immediate: true,
    })
    state = appReducer(state, {
      type: 'CANCEL_TARGET_DRAFT',
      caseId: empty.id,
      targetId: 'empty',
    })
    expect(state.documents[empty.id].document.targets[0].points).toEqual([])
    expect(state.documents[empty.id].dirtyTargetIds).toEqual([])
    expect(state.documents[empty.id].savePhase).toBe('saved')
  })

  it('updates and clamps the requested playhead even without playable media', () => {
    const state = appReducer(
      { ...initialState, video: { ...initialState.video, duration: 10 } },
      { type: 'REQUEST_SEEK', time: 12 },
    )
    expect(state.video.currentTime).toBe(10)
    expect(state.video.seekRequest.time).toBe(10)
  })

  it('keeps a failed queue stopped while newer edits remain retryable', () => {
    let state = loadedState()
    const caseId = 'case-001.yaml'
    state = appReducer(state, {
      type: 'REPLACE_TARGET_POINTS',
      caseId,
      targetId: 'target_a',
      points: [point('target_a-point', 2)],
      immediate: true,
    })
    state = appReducer(state, {
      type: 'SAVE_FAILED',
      caseId,
      message: 'disk is read-only',
      details: [],
    })
    state = appReducer(state, {
      type: 'REPLACE_TARGET_POINTS',
      caseId,
      targetId: 'target_a',
      points: [point('target_a-point', 3)],
      immediate: true,
    })
    expect(state.documents[caseId].savePhase).toBe('failed')
    expect(state.documents[caseId].saveError).toBe('disk is read-only')
    expect(state.documents[caseId].document.targets[0].points[0].timestamp_s).toBe(3)
  })
})
