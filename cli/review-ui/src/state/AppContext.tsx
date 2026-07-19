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
} from "react";
import {
  fetchCaseFile,
  fetchEvalDirectory,
  replaceTargetSamples,
  ReviewApiError,
} from "../api/client.ts";
import type { ReviewSample } from "../api/types.ts";
import {
  appReducer,
  hasUnsavedWork,
  initialState,
  isRepairComplete,
  type AppAction,
  type AppState,
} from "./reducer.ts";
import { canDeleteFromTarget, createSampleAt } from "./editing.ts";

interface AppContextValue {
  state: AppState;
  dispatch: Dispatch<AppAction>;
  selectCase: (caseId: string) => Promise<void>;
  selectTarget: (targetId: string) => Promise<void>;
  selectSample: (targetId: string, sampleId: string) => Promise<void>;
  updateSample: (
    targetId: string,
    sampleId: string,
    update: Partial<ReviewSample>,
    immediate?: boolean,
  ) => void;
  addSample: () => ReviewSample | null;
  deleteSample: (targetId: string, sampleId: string) => void;
  canDeleteSample: (targetId: string, sampleId: string) => boolean;
  setFormError: (key: string, message: string | null) => void;
  seek: (time: number) => void;
  flushCurrentCase: () => Promise<boolean>;
  retrySave: () => void;
  reloadFromDisk: () => Promise<void>;
}

const AppContext = createContext<AppContextValue | null>(null);

function initialQuery() {
  const params = new URLSearchParams(window.location.search);
  const rawTime = params.get("time");
  const parsedTime = rawTime === null ? null : Number(rawTime);
  return {
    caseSelector: params.get("case"),
    targetId: params.get("target"),
    time: parsedTime !== null && Number.isFinite(parsedTime) && parsedTime >= 0 ? parsedTime : null,
  };
}

function uuid(): string {
  return (
    globalThis.crypto?.randomUUID?.() ??
    `sample-${Date.now()}-${Math.random().toString(16).slice(2)}`
  );
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(appReducer, initialState);
  const stateRef = useRef(state);
  stateRef.current = state;
  const queryRef = useRef(initialQuery());
  const initialSeekDone = useRef(false);
  const initialTargetUsed = useRef(false);
  const caseFileLoads = useRef(new Map<string, AbortController>());
  const saveTimers = useRef(new Map<string, number>());
  const inFlight = useRef(new Map<string, Promise<boolean>>());
  const saveGenerations = useRef(new Map<string, number>());
  const liveFormErrors = useRef(new Map<string, Set<string>>());
  const providerMounted = useRef(false);
  const providerGeneration = useRef(0);

  useEffect(() => {
    const loads = caseFileLoads.current;
    const timers = saveTimers.current;
    const saves = inFlight.current;
    const generations = saveGenerations.current;
    providerMounted.current = true;
    providerGeneration.current += 1;
    return () => {
      providerMounted.current = false;
      providerGeneration.current += 1;
      for (const controller of loads.values()) controller.abort();
      loads.clear();
      for (const timer of timers.values()) window.clearTimeout(timer);
      timers.clear();
      for (const caseId of saves.keys()) {
        generations.set(caseId, (generations.get(caseId) ?? 0) + 1);
      }
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetchEvalDirectory(controller.signal)
      .then((evalDirectory) => {
        const selector = queryRef.current.caseSelector;
        const matchingCase = selector
          ? evalDirectory.cases.find((item) => item.id === selector || item.name === selector)
          : null;
        dispatch({
          type: "EVAL_DIRECTORY_LOADED",
          evalDirectory,
          initialCaseId: matchingCase?.id ?? null,
        });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          dispatch({
            type: "EVAL_DIRECTORY_FAILED",
            message: error instanceof Error ? error.message : "Could not load the eval directory.",
          });
        }
      });
    return () => controller.abort();
  }, []);

  const loadCaseFile = useCallback(async (caseId: string, discard = false) => {
    caseFileLoads.current.get(caseId)?.abort();
    const controller = new AbortController();
    caseFileLoads.current.set(caseId, controller);
    dispatch({ type: "CASE_FILE_LOADING", caseId });
    try {
      const document = await fetchCaseFile(caseId, controller.signal);
      liveFormErrors.current.delete(caseId);
      if (discard) {
        dispatch({ type: "DISCARD_AND_LOAD", document });
      } else {
        const preferredTargetId = initialTargetUsed.current ? null : queryRef.current.targetId;
        initialTargetUsed.current = true;
        dispatch({
          type: "CASE_FILE_LOADED",
          document,
          preferredTargetId,
        });
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        dispatch({
          type: "CASE_FILE_LOAD_FAILED",
          caseId,
          message: error instanceof Error ? error.message : "Could not load the case file.",
        });
      }
    } finally {
      if (caseFileLoads.current.get(caseId) === controller) {
        caseFileLoads.current.delete(caseId);
      }
    }
  }, []);

  useEffect(() => {
    const caseId = state.selectedCaseId;
    if (caseId && !state.caseFileWorkspaces[caseId] && !state.loadingCaseFiles[caseId]) {
      void loadCaseFile(caseId);
    }
  }, [loadCaseFile, state.caseFileWorkspaces, state.loadingCaseFiles, state.selectedCaseId]);

  useEffect(() => {
    if (
      !initialSeekDone.current &&
      state.selectedCaseId &&
      state.caseFileWorkspaces[state.selectedCaseId]
    ) {
      initialSeekDone.current = true;
      if (queryRef.current.time !== null) {
        dispatch({ type: "REQUEST_SEEK", time: queryRef.current.time });
      }
    }
  }, [state.caseFileWorkspaces, state.selectedCaseId]);

  const performSave = useCallback(async (caseId: string, retryFailed = false): Promise<boolean> => {
    const lifecycleGeneration = providerGeneration.current;
    const providerIsLive = () =>
      providerMounted.current && providerGeneration.current === lifecycleGeneration;
    if (!providerIsLive()) return false;
    const running = inFlight.current.get(caseId);
    if (running) {
      const completed = await running;
      if (!providerIsLive()) return false;
      await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
      if (!providerIsLive() || !completed) return false;
      return performSave(caseId, retryFailed);
    }
    const snapshot = stateRef.current.caseFileWorkspaces[caseId];
    const evalDirectory = stateRef.current.evalDirectory;
    if (!snapshot || !evalDirectory || snapshot.dirtyTargetIds.length === 0) {
      return true;
    }
    if (
      Object.keys(snapshot.formErrors).length > 0 ||
      (liveFormErrors.current.get(caseId)?.size ?? 0) > 0
    )
      return false;
    if (snapshot.savePhase === "failed" && !retryFailed) return false;
    if (!isRepairComplete(snapshot)) {
      dispatch({ type: "SAVE_REPAIRS_REQUIRED", caseId });
      return false;
    }
    const submittedVersions = Object.fromEntries(
      snapshot.dirtyTargetIds.map((targetId) => [targetId, snapshot.versions[targetId] ?? 0]),
    );
    const targets = Object.fromEntries(
      snapshot.document.targets
        .filter((target) => snapshot.dirtyTargetIds.includes(target.id))
        .map((target) => [target.id, { samples: target.samples }]),
    );
    dispatch({ type: "SAVE_START", caseId });
    const requestGeneration = saveGenerations.current.get(caseId) ?? 0;
    const promise = replaceTargetSamples(caseId, evalDirectory.write_token, { targets })
      .then((document) => {
        if (!providerIsLive() || (saveGenerations.current.get(caseId) ?? 0) !== requestGeneration) {
          return false;
        }
        dispatch({
          type: "SAVE_SUCCESS",
          caseId,
          document,
          submittedVersions,
        });
        return true;
      })
      .catch((error: unknown) => {
        if (!providerIsLive() || (saveGenerations.current.get(caseId) ?? 0) !== requestGeneration) {
          return false;
        }
        dispatch({
          type: "SAVE_FAILED",
          caseId,
          message: error instanceof Error ? error.message : "Could not save changes.",
          details: error instanceof ReviewApiError ? error.details : [],
        });
        return false;
      })
      .finally(() => {
        if (inFlight.current.get(caseId) === promise) {
          inFlight.current.delete(caseId);
        }
      });
    inFlight.current.set(caseId, promise);
    const completed = await promise;
    if (!providerIsLive()) return false;
    await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
    if (!providerIsLive() || !completed) return false;
    const latest = stateRef.current.caseFileWorkspaces[caseId];
    if (latest?.dirtyTargetIds.length) {
      return performSave(caseId, retryFailed);
    }
    return true;
  }, []);

  useEffect(() => {
    const timers = saveTimers.current;
    for (const [caseId, workspace] of Object.entries(state.caseFileWorkspaces)) {
      const oldTimer = timers.get(caseId);
      if (
        workspace.dirtyTargetIds.length === 0 ||
        workspace.savePhase === "failed" ||
        workspace.savePhase === "repairs" ||
        Object.keys(workspace.formErrors).length > 0 ||
        inFlight.current.has(caseId)
      ) {
        if (oldTimer !== undefined) window.clearTimeout(oldTimer);
        timers.delete(caseId);
        continue;
      }
      if (oldTimer !== undefined) window.clearTimeout(oldTimer);
      const timer = window.setTimeout(() => {
        saveTimers.current.delete(caseId);
        void performSave(caseId);
      }, workspace.saveDelayMs);
      timers.set(caseId, timer);
    }
    return () => {
      for (const timer of timers.values()) window.clearTimeout(timer);
      timers.clear();
    };
  }, [performSave, state.caseFileWorkspaces]);

  useEffect(() => {
    const hasDirty = Object.values(state.caseFileWorkspaces).some(hasUnsavedWork);
    if (!hasDirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [state.caseFileWorkspaces]);

  useEffect(() => {
    if (!state.toast) return;
    const timer = window.setTimeout(() => dispatch({ type: "SET_TOAST", value: null }), 3500);
    return () => window.clearTimeout(timer);
  }, [state.toast]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (state.selectedCaseId) params.set("case", state.selectedCaseId);
    else params.delete("case");
    if (state.selectedTargetId) params.set("target", state.selectedTargetId);
    else params.delete("target");
    if (state.video.seekRequest.generation > 0) {
      params.set("time", String(state.video.seekRequest.time));
    }
    const query = params.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
  }, [
    state.selectedCaseId,
    state.selectedTargetId,
    state.video.seekRequest.generation,
    state.video.seekRequest.time,
  ]);

  const flushCurrentCase = useCallback(async () => {
    const caseId = stateRef.current.selectedCaseId;
    if (!caseId) return true;
    const timer = saveTimers.current.get(caseId);
    if (timer !== undefined) window.clearTimeout(timer);
    saveTimers.current.delete(caseId);
    return performSave(caseId);
  }, [performSave]);

  const selectCase = useCallback(
    async (caseId: string) => {
      if (caseId === stateRef.current.selectedCaseId) return;
      const currentId = stateRef.current.selectedCaseId;
      const current = currentId ? stateRef.current.caseFileWorkspaces[currentId] : null;
      if (
        current &&
        (Object.keys(current.formErrors).length > 0 ||
          (liveFormErrors.current.get(currentId!)?.size ?? 0) > 0)
      )
        return;
      if (current?.dirtyTargetIds.length) {
        const saved = await flushCurrentCase();
        if (!saved) return;
      }
      dispatch({ type: "SELECT_CASE", caseId });
      void loadCaseFile(caseId);
    },
    [flushCurrentCase, loadCaseFile],
  );

  const selectTarget = useCallback(
    async (targetId: string) => {
      const caseId = stateRef.current.selectedCaseId;
      const workspace = caseId ? stateRef.current.caseFileWorkspaces[caseId] : null;
      if (
        !workspace ||
        Object.keys(workspace.formErrors).length > 0 ||
        (liveFormErrors.current.get(caseId!)?.size ?? 0) > 0
      )
        return;
      if (workspace.dirtyTargetIds.length && isRepairComplete(workspace)) {
        const saved = await performSave(caseId!);
        if (!saved) return;
      }
      dispatch({ type: "SELECT_TARGET", targetId });
    },
    [performSave],
  );

  const selectSample = useCallback(
    async (targetId: string, sampleId: string) => {
      const caseId = stateRef.current.selectedCaseId;
      const workspace = caseId ? stateRef.current.caseFileWorkspaces[caseId] : null;
      if (
        !workspace ||
        Object.keys(workspace.formErrors).length > 0 ||
        (liveFormErrors.current.get(caseId!)?.size ?? 0) > 0
      )
        return;
      if (workspace.dirtyTargetIds.length && isRepairComplete(workspace)) {
        const saved = await performSave(caseId!);
        if (!saved) return;
      }
      const target = workspace.document.targets.find((item) => item.id === targetId);
      const sample = target?.samples.find((item) => item.id === sampleId);
      if (!sample) return;
      dispatch({
        type: "SELECT_SAMPLE",
        targetId,
        sampleId,
        timestamp: sample.timestamp_s,
      });
    },
    [performSave],
  );

  const updateSample = useCallback(
    (targetId: string, sampleId: string, update: Partial<ReviewSample>, immediate = false) => {
      const caseId = stateRef.current.selectedCaseId;
      const workspace = caseId ? stateRef.current.caseFileWorkspaces[caseId] : null;
      const target = workspace?.document.targets.find((item) => item.id === targetId);
      if (!caseId || !workspace || !target) return;
      const currentSample = target.samples.find((sample) => sample.id === sampleId);
      if (!currentSample) return;
      const normalizedUpdate: Partial<ReviewSample> = { ...update };
      if ("field" in update) {
        normalizedUpdate.field = update.field?.trim() || null;
      }
      if ("comment" in update) {
        normalizedUpdate.comment = update.comment?.trim() || null;
      }
      if ("ignore" in update) {
        normalizedUpdate.ignore = update.ignore?.trim() || null;
      }
      const nextSample = { ...currentSample, ...normalizedUpdate };
      const unchanged =
        nextSample.timestamp_s === currentSample.timestamp_s &&
        nextSample.has_expectation === currentSample.has_expectation &&
        nextSample.expect_type === currentSample.expect_type &&
        nextSample.expect_json === currentSample.expect_json &&
        nextSample.field === currentSample.field &&
        nextSample.comment === currentSample.comment &&
        nextSample.ignore === currentSample.ignore &&
        nextSample.compare.mode === currentSample.compare.mode &&
        nextSample.compare.tolerance === currentSample.compare.tolerance;
      if (unchanged) return;
      const samples = target.samples
        .map((sample) => (sample.id === sampleId ? nextSample : sample))
        .sort((left, right) => left.timestamp_s - right.timestamp_s);
      dispatch({
        type: "REPLACE_TARGET_SAMPLES",
        caseId,
        targetId,
        samples,
        immediate,
      });
      if (normalizedUpdate.timestamp_s !== undefined) {
        dispatch({
          type: "REQUEST_SEEK",
          time: normalizedUpdate.timestamp_s,
        });
      }
    },
    [],
  );

  const addSample = useCallback((): ReviewSample | null => {
    const current = stateRef.current;
    const caseId = current.selectedCaseId;
    const targetId = current.selectedTargetId;
    const workspace = caseId ? current.caseFileWorkspaces[caseId] : null;
    const target = workspace?.document.targets.find((item) => item.id === targetId);
    if (
      !caseId ||
      !targetId ||
      !workspace ||
      !target ||
      !workspace.document.editing_enabled ||
      Object.keys(workspace.formErrors).length > 0 ||
      (liveFormErrors.current.get(caseId)?.size ?? 0) > 0
    )
      return null;
    const created = createSampleAt(target, current.video.currentTime, uuid());
    if (created.duplicate) {
      void selectSample(targetId, created.sample.id);
      return created.sample;
    }
    const sample = created.sample;
    dispatch({
      type: "REPLACE_TARGET_SAMPLES",
      caseId,
      targetId,
      samples: [...target.samples, sample].sort(
        (left, right) => left.timestamp_s - right.timestamp_s,
      ),
      immediate: true,
    });
    dispatch({
      type: "SELECT_SAMPLE",
      targetId,
      sampleId: sample.id,
      timestamp: sample.timestamp_s,
    });
    return sample;
  }, [selectSample]);

  const canDeleteSample = useCallback((targetId: string, sampleId: string) => {
    const current = stateRef.current;
    const caseId = current.selectedCaseId;
    const workspace = caseId ? current.caseFileWorkspaces[caseId] : null;
    const target = workspace?.document.targets.find((item) => item.id === targetId);
    const acceptedTarget = workspace?.acceptedCaseFile.targets.find((item) => item.id === targetId);
    return workspace && target
      ? canDeleteFromTarget(target, acceptedTarget, sampleId, inFlight.current.has(caseId!))
      : false;
  }, []);

  const deleteSample = useCallback(
    (targetId: string, sampleId: string) => {
      if (!canDeleteSample(targetId, sampleId)) return;
      const current = stateRef.current;
      const caseId = current.selectedCaseId;
      const workspace = caseId ? current.caseFileWorkspaces[caseId] : null;
      const target = workspace?.document.targets.find((item) => item.id === targetId);
      if (!caseId || !workspace || !target) return;
      const index = target.samples.findIndex((sample) => sample.id === sampleId);
      const samples = target.samples.filter((sample) => sample.id !== sampleId);
      const errorPrefix = `${targetId}:${sampleId}:`;
      const errorKeys = new Set(
        Object.keys(workspace.formErrors).filter((key) => key.startsWith(errorPrefix)),
      );
      const liveErrors = liveFormErrors.current.get(caseId);
      if (liveErrors) {
        for (const key of liveErrors) {
          if (key.startsWith(errorPrefix)) errorKeys.add(key);
        }
        for (const key of errorKeys) liveErrors.delete(key);
        if (liveErrors.size === 0) liveFormErrors.current.delete(caseId);
      }
      if (errorKeys.size > 0) {
        dispatch({
          type: "CLEAR_FORM_ERRORS",
          caseId,
          keys: [...errorKeys],
        });
      }
      const acceptedTarget = workspace.acceptedCaseFile.targets.find(
        (item) => item.id === targetId,
      );
      if (samples.length === 0 && acceptedTarget?.samples.length === 0) {
        dispatch({ type: "CANCEL_TARGET_DRAFT", caseId, targetId });
        return;
      }
      dispatch({
        type: "REPLACE_TARGET_SAMPLES",
        caseId,
        targetId,
        samples,
        immediate: true,
      });
      const next = samples[index] ?? samples[index - 1];
      if (next) {
        dispatch({
          type: "SELECT_SAMPLE",
          targetId,
          sampleId: next.id,
          timestamp: next.timestamp_s,
        });
      } else dispatch({ type: "SELECT_TARGET", targetId });
    },
    [canDeleteSample],
  );

  const seek = useCallback((time: number) => {
    dispatch({ type: "REQUEST_SEEK", time });
  }, []);

  const setFormError = useCallback((key: string, message: string | null) => {
    const caseId = stateRef.current.selectedCaseId;
    if (!caseId) return;
    let errors = liveFormErrors.current.get(caseId);
    if (!errors) {
      errors = new Set();
      liveFormErrors.current.set(caseId, errors);
    }
    if (message) errors.add(key);
    else errors.delete(key);
    dispatch({ type: "SET_FORM_ERROR", key, message });
  }, []);

  const retrySave = useCallback(() => {
    const caseId = stateRef.current.selectedCaseId;
    if (caseId) void performSave(caseId, true);
  }, [performSave]);

  const reloadFromDisk = useCallback(async () => {
    const caseId = stateRef.current.selectedCaseId;
    if (!caseId) return;
    saveGenerations.current.set(caseId, (saveGenerations.current.get(caseId) ?? 0) + 1);
    const timer = saveTimers.current.get(caseId);
    if (timer !== undefined) window.clearTimeout(timer);
    saveTimers.current.delete(caseId);
    const running = inFlight.current.get(caseId);
    if (running) {
      await running.catch(() => false);
      await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
    }
    await loadCaseFile(caseId, true);
  }, [loadCaseFile]);

  const value = useMemo<AppContextValue>(
    () => ({
      state,
      dispatch,
      selectCase,
      selectTarget,
      selectSample,
      updateSample,
      addSample,
      deleteSample,
      canDeleteSample,
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
      selectSample,
      updateSample,
      addSample,
      deleteSample,
      canDeleteSample,
      setFormError,
      seek,
      flushCurrentCase,
      retrySave,
      reloadFromDisk,
    ],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

// The context hook intentionally lives beside its provider to keep the public
// state boundary in one module.
// oxlint-disable-next-line react/only-export-components
export function useApp(): AppContextValue {
  const value = useContext(AppContext);
  if (!value) throw new Error("useApp must be used inside AppProvider.");
  return value;
}
