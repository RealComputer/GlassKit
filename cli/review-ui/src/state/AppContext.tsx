import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  type Dispatch,
  type ReactNode,
} from 'react'
import {
  fetchCase,
  fetchSuite,
  replaceTargetSamples,
  ReviewApiError,
} from '../api/client.ts'
import type { ReviewPoint } from '../api/types.ts'
import {
  appReducer,
  hasUnsavedWork,
  initialState,
  isRepairComplete,
  type AppAction,
  type AppState,
} from './reducer.ts'
import { canDeleteFromTarget, createPointAt } from './editing.ts'

interface AppContextValue {
  state: AppState
  dispatch: Dispatch<AppAction>
  selectCase: (caseId: string) => Promise<void>
  selectTarget: (targetId: string) => Promise<void>
  selectPoint: (targetId: string, pointId: string) => Promise<void>
  updatePoint: (
    targetId: string,
    pointId: string,
    update: Partial<ReviewPoint>,
    immediate?: boolean,
  ) => void
  addPoint: () => ReviewPoint | null
  deletePoint: (targetId: string, pointId: string) => void
  canDeletePoint: (targetId: string, pointId: string) => boolean
  setFormError: (key: string, message: string | null) => void
  seek: (time: number, sampleTime?: number | null) => void
  flushCurrentCase: () => Promise<boolean>
  retrySave: () => void
  reloadFromDisk: () => Promise<void>
}

const AppContext = createContext<AppContextValue | null>(null)

function initialQuery() {
  const params = new URLSearchParams(window.location.search)
  const rawTime = params.get('time')
  const parsedTime = rawTime === null ? null : Number(rawTime)
  return {
    caseSelector: params.get('case'),
    targetId: params.get('target'),
    time:
      parsedTime !== null && Number.isFinite(parsedTime) && parsedTime >= 0
        ? parsedTime
        : null,
  }
}

function uuid(): string {
  return globalThis.crypto?.randomUUID?.() ??
    `point-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(appReducer, initialState)
  const stateRef = useRef(state)
  stateRef.current = state
  const queryRef = useRef(initialQuery())
  const initialSeekDone = useRef(false)
  const initialTargetUsed = useRef(false)
  const caseLoads = useRef(new Map<string, AbortController>())
  const saveTimers = useRef(new Map<string, number>())
  const inFlight = useRef(new Map<string, Promise<boolean>>())
  const saveGenerations = useRef(new Map<string, number>())
  const liveFormErrors = useRef(new Map<string, Set<string>>())

  useEffect(() => {
    const controller = new AbortController()
    fetchSuite(controller.signal)
      .then((suite) => {
        const selector = queryRef.current.caseSelector
        const matchingCase = selector
          ? suite.cases.find(
              (item) => item.id === selector || item.name === selector,
            )
          : null
        dispatch({
          type: 'SUITE_LOADED',
          suite,
          initialCaseId: matchingCase?.id ?? null,
        })
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          dispatch({
            type: 'SUITE_FAILED',
            message:
              error instanceof Error
                ? error.message
                : 'Could not load the eval suite.',
          })
        }
      })
    return () => controller.abort()
  }, [])

  const loadCase = useCallback(async (caseId: string, discard = false) => {
    caseLoads.current.get(caseId)?.abort()
    const controller = new AbortController()
    caseLoads.current.set(caseId, controller)
    dispatch({ type: 'CASE_LOADING', caseId })
    try {
      const document = await fetchCase(caseId, controller.signal)
      liveFormErrors.current.delete(caseId)
      if (discard) {
        dispatch({ type: 'DISCARD_AND_LOAD', document })
      } else {
        const preferredTargetId = initialTargetUsed.current
          ? null
          : queryRef.current.targetId
        initialTargetUsed.current = true
        dispatch({
          type: 'CASE_LOADED',
          document,
          preferredTargetId,
        })
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        dispatch({
          type: 'CASE_LOAD_FAILED',
          caseId,
          message:
            error instanceof Error ? error.message : 'Could not load the case.',
        })
      }
    } finally {
      if (caseLoads.current.get(caseId) === controller) {
        caseLoads.current.delete(caseId)
      }
    }
  }, [])

  useEffect(() => {
    const caseId = state.selectedCaseId
    if (caseId && !state.documents[caseId] && !state.loadingCases[caseId]) {
      void loadCase(caseId)
    }
  }, [loadCase, state.documents, state.loadingCases, state.selectedCaseId])

  useEffect(() => {
    if (
      !initialSeekDone.current &&
      state.selectedCaseId &&
      state.documents[state.selectedCaseId]
    ) {
      initialSeekDone.current = true
      if (queryRef.current.time !== null) {
        dispatch({ type: 'REQUEST_SEEK', time: queryRef.current.time })
      }
    }
  }, [state.documents, state.selectedCaseId])

  const performSave = useCallback(
    async (caseId: string, retryFailed = false): Promise<boolean> => {
      const running = inFlight.current.get(caseId)
      if (running) {
        const completed = await running
        await new Promise<void>((resolve) => window.setTimeout(resolve, 0))
        if (!completed) return false
        return performSave(caseId, retryFailed)
      }
      const snapshot = stateRef.current.documents[caseId]
      const suite = stateRef.current.suite
      if (!snapshot || !suite || snapshot.dirtyTargetIds.length === 0) {
        return true
      }
      if (
        Object.keys(snapshot.formErrors).length > 0 ||
        (liveFormErrors.current.get(caseId)?.size ?? 0) > 0
      ) return false
      if (snapshot.savePhase === 'failed' && !retryFailed) return false
      if (!isRepairComplete(snapshot)) {
        dispatch({ type: 'SAVE_REPAIRS_REQUIRED', caseId })
        return false
      }
      const submittedVersions = Object.fromEntries(
        snapshot.dirtyTargetIds.map((targetId) => [
          targetId,
          snapshot.versions[targetId] ?? 0,
        ]),
      )
      const targets = Object.fromEntries(
        snapshot.document.targets
          .filter((target) => snapshot.dirtyTargetIds.includes(target.id))
          .map((target) => [target.id, { points: target.points }]),
      )
      dispatch({ type: 'SAVE_START', caseId })
      const requestGeneration = saveGenerations.current.get(caseId) ?? 0
      const promise = replaceTargetSamples(caseId, suite.write_token, { targets })
        .then((document) => {
          if ((saveGenerations.current.get(caseId) ?? 0) !== requestGeneration) {
            return false
          }
          dispatch({
            type: 'SAVE_SUCCESS',
            caseId,
            document,
            submittedVersions,
          })
          return true
        })
        .catch((error: unknown) => {
          if ((saveGenerations.current.get(caseId) ?? 0) !== requestGeneration) {
            return false
          }
          dispatch({
            type: 'SAVE_FAILED',
            caseId,
            message:
              error instanceof Error ? error.message : 'Could not save changes.',
            details: error instanceof ReviewApiError ? error.details : [],
          })
          return false
        })
        .finally(() => {
          if (inFlight.current.get(caseId) === promise) {
            inFlight.current.delete(caseId)
          }
        })
      inFlight.current.set(caseId, promise)
      const completed = await promise
      await new Promise<void>((resolve) => window.setTimeout(resolve, 0))
      if (!completed) return false
      const latest = stateRef.current.documents[caseId]
      if (latest?.dirtyTargetIds.length) {
        return performSave(caseId, retryFailed)
      }
      return true
    },
    [],
  )

  useEffect(() => {
    const timers = saveTimers.current
    for (const [caseId, workspace] of Object.entries(state.documents)) {
      const oldTimer = timers.get(caseId)
      if (
        workspace.dirtyTargetIds.length === 0 ||
        workspace.savePhase === 'failed' ||
        workspace.savePhase === 'repairs' ||
        Object.keys(workspace.formErrors).length > 0 ||
        inFlight.current.has(caseId)
      ) {
        if (oldTimer !== undefined) window.clearTimeout(oldTimer)
        timers.delete(caseId)
        continue
      }
      if (oldTimer !== undefined) window.clearTimeout(oldTimer)
      const timer = window.setTimeout(() => {
        saveTimers.current.delete(caseId)
        void performSave(caseId)
      }, workspace.saveDelayMs)
      timers.set(caseId, timer)
    }
    return () => {
      for (const timer of timers.values()) window.clearTimeout(timer)
      timers.clear()
    }
  }, [performSave, state.documents])

  useEffect(() => {
    const hasDirty = Object.values(state.documents).some(hasUnsavedWork)
    if (!hasDirty) return
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [state.documents])

  useEffect(() => {
    if (!state.toast) return
    const timer = window.setTimeout(
      () => dispatch({ type: 'SET_TOAST', value: null }),
      3500,
    )
    return () => window.clearTimeout(timer)
  }, [state.toast])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (state.selectedCaseId) params.set('case', state.selectedCaseId)
    else params.delete('case')
    if (state.selectedTargetId) params.set('target', state.selectedTargetId)
    else params.delete('target')
    if (state.video.seekRequest.generation > 0) {
      params.set('time', String(state.video.seekRequest.time))
    }
    const query = params.toString()
    window.history.replaceState(
      null,
      '',
      `${window.location.pathname}${query ? `?${query}` : ''}`,
    )
  }, [
    state.selectedCaseId,
    state.selectedTargetId,
    state.video.seekRequest.generation,
    state.video.seekRequest.time,
  ])

  const flushCurrentCase = useCallback(async () => {
    const caseId = stateRef.current.selectedCaseId
    if (!caseId) return true
    const timer = saveTimers.current.get(caseId)
    if (timer !== undefined) window.clearTimeout(timer)
    saveTimers.current.delete(caseId)
    return performSave(caseId)
  }, [performSave])

  const selectCase = useCallback(
    async (caseId: string) => {
      if (caseId === stateRef.current.selectedCaseId) return
      const currentId = stateRef.current.selectedCaseId
      const current = currentId ? stateRef.current.documents[currentId] : null
      if (
        current &&
        (Object.keys(current.formErrors).length > 0 ||
          (liveFormErrors.current.get(currentId!)?.size ?? 0) > 0)
      ) return
      if (current?.dirtyTargetIds.length) {
        const saved = await flushCurrentCase()
        if (!saved) return
      }
      dispatch({ type: 'SELECT_CASE', caseId })
      void loadCase(caseId)
    },
    [flushCurrentCase, loadCase],
  )

  const selectTarget = useCallback(
    async (targetId: string) => {
      const caseId = stateRef.current.selectedCaseId
      const workspace = caseId ? stateRef.current.documents[caseId] : null
      if (
        !workspace ||
        Object.keys(workspace.formErrors).length > 0 ||
        (liveFormErrors.current.get(caseId!)?.size ?? 0) > 0
      ) return
      if (workspace.dirtyTargetIds.length && isRepairComplete(workspace)) {
        const saved = await performSave(caseId!)
        if (!saved) return
      }
      dispatch({ type: 'SELECT_TARGET', targetId })
    },
    [performSave],
  )

  const selectPoint = useCallback(
    async (targetId: string, pointId: string) => {
      const caseId = stateRef.current.selectedCaseId
      const workspace = caseId ? stateRef.current.documents[caseId] : null
      if (
        !workspace ||
        Object.keys(workspace.formErrors).length > 0 ||
        (liveFormErrors.current.get(caseId!)?.size ?? 0) > 0
      ) return
      if (workspace.dirtyTargetIds.length && isRepairComplete(workspace)) {
        const saved = await performSave(caseId!)
        if (!saved) return
      }
      const target = workspace.document.targets.find(
        (item) => item.id === targetId,
      )
      const point = target?.points.find((item) => item.id === pointId)
      if (!point) return
      dispatch({
        type: 'SELECT_POINT',
        targetId,
        pointId,
        timestamp: point.timestamp_s,
      })
    },
    [performSave],
  )

  const updatePoint = useCallback(
    (
      targetId: string,
      pointId: string,
      update: Partial<ReviewPoint>,
      immediate = false,
    ) => {
      const caseId = stateRef.current.selectedCaseId
      const workspace = caseId ? stateRef.current.documents[caseId] : null
      const target = workspace?.document.targets.find(
        (item) => item.id === targetId,
      )
      if (!caseId || !workspace || !target) return
      const points = target.points
        .map((point) => (point.id === pointId ? { ...point, ...update } : point))
        .sort((left, right) => left.timestamp_s - right.timestamp_s)
      dispatch({
        type: 'REPLACE_TARGET_POINTS',
        caseId,
        targetId,
        points,
        immediate,
      })
      if (update.timestamp_s !== undefined) {
        dispatch({
          type: 'REQUEST_SEEK',
          time: update.timestamp_s,
          sampleTime: update.timestamp_s,
        })
      }
    },
    [],
  )

  const addPoint = useCallback((): ReviewPoint | null => {
    const current = stateRef.current
    const caseId = current.selectedCaseId
    const targetId = current.selectedTargetId
    const workspace = caseId ? current.documents[caseId] : null
    const target = workspace?.document.targets.find(
      (item) => item.id === targetId,
    )
    if (
      !caseId ||
      !targetId ||
      !workspace ||
      !target ||
      !workspace.document.editing_enabled
    ) return null
    const created = createPointAt(target, current.video.currentTime, uuid())
    if (created.duplicate) {
      void selectPoint(targetId, created.point.id)
      return created.point
    }
    const point = created.point
    dispatch({
      type: 'REPLACE_TARGET_POINTS',
      caseId,
      targetId,
      points: [...target.points, point].sort(
        (left, right) => left.timestamp_s - right.timestamp_s,
      ),
      immediate: true,
    })
    dispatch({
      type: 'SELECT_POINT',
      targetId,
      pointId: point.id,
      timestamp: point.timestamp_s,
    })
    return point
  }, [selectPoint])

  const canDeletePoint = useCallback((targetId: string, pointId: string) => {
    const current = stateRef.current
    const caseId = current.selectedCaseId
    const workspace = caseId ? current.documents[caseId] : null
    const target = workspace?.document.targets.find(
      (item) => item.id === targetId,
    )
    const acceptedTarget = workspace?.acceptedDocument.targets.find(
      (item) => item.id === targetId,
    )
    return workspace && target
      ? canDeleteFromTarget(
          target,
          acceptedTarget,
          pointId,
          inFlight.current.has(caseId!),
        )
      : false
  }, [])

  const deletePoint = useCallback(
    (targetId: string, pointId: string) => {
      if (!canDeletePoint(targetId, pointId)) return
      const current = stateRef.current
      const caseId = current.selectedCaseId
      const workspace = caseId ? current.documents[caseId] : null
      const target = workspace?.document.targets.find(
        (item) => item.id === targetId,
      )
      if (!caseId || !workspace || !target) return
      const index = target.points.findIndex((point) => point.id === pointId)
      const points = target.points.filter((point) => point.id !== pointId)
      const acceptedTarget = workspace.acceptedDocument.targets.find(
        (item) => item.id === targetId,
      )
      if (points.length === 0 && acceptedTarget?.points.length === 0) {
        dispatch({ type: 'CANCEL_TARGET_DRAFT', caseId, targetId })
        return
      }
      dispatch({
        type: 'REPLACE_TARGET_POINTS',
        caseId,
        targetId,
        points,
        immediate: true,
      })
      const next = points[index] ?? points[index - 1]
      if (next) void selectPoint(targetId, next.id)
      else dispatch({ type: 'SELECT_TARGET', targetId })
    },
    [canDeletePoint, selectPoint],
  )

  const seek = useCallback((time: number, sampleTime?: number | null) => {
    dispatch({ type: 'REQUEST_SEEK', time, sampleTime })
  }, [])

  const setFormError = useCallback((key: string, message: string | null) => {
    const caseId = stateRef.current.selectedCaseId
    if (!caseId) return
    let errors = liveFormErrors.current.get(caseId)
    if (!errors) {
      errors = new Set()
      liveFormErrors.current.set(caseId, errors)
    }
    if (message) errors.add(key)
    else errors.delete(key)
    dispatch({ type: 'SET_FORM_ERROR', key, message })
  }, [])

  const retrySave = useCallback(() => {
    const caseId = stateRef.current.selectedCaseId
    if (caseId) void performSave(caseId, true)
  }, [performSave])

  const reloadFromDisk = useCallback(async () => {
    const caseId = stateRef.current.selectedCaseId
    if (!caseId) return
    saveGenerations.current.set(
      caseId,
      (saveGenerations.current.get(caseId) ?? 0) + 1,
    )
    const timer = saveTimers.current.get(caseId)
    if (timer !== undefined) window.clearTimeout(timer)
    saveTimers.current.delete(caseId)
    const running = inFlight.current.get(caseId)
    if (running) {
      await running.catch(() => false)
      await new Promise<void>((resolve) => window.setTimeout(resolve, 0))
    }
    await loadCase(caseId, true)
  }, [loadCase])

  const value = useMemo<AppContextValue>(
    () => ({
      state,
      dispatch,
      selectCase,
      selectTarget,
      selectPoint,
      updatePoint,
      addPoint,
      deletePoint,
      canDeletePoint,
      setFormError,
      seek,
      flushCurrentCase,
      retrySave,
      reloadFromDisk,
    }),
    [
      state,
      selectCase,
      selectTarget,
      selectPoint,
      updatePoint,
      addPoint,
      deletePoint,
      canDeletePoint,
      setFormError,
      seek,
      flushCurrentCase,
      retrySave,
      reloadFromDisk,
    ],
  )

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

// The context hook intentionally lives beside its provider to keep the public
// state boundary in one module.
// oxlint-disable-next-line react/only-export-components
export function useApp(): AppContextValue {
  const value = useContext(AppContext)
  if (!value) throw new Error('useApp must be used inside AppProvider.')
  return value
}
