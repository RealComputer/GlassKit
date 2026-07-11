import type { CaseFileDocument, ReviewSample, EvalDirectoryDocument } from "../api/types.ts";

export const SAMPLE_DURATION_TOLERANCE_S = 0.05;

export type SavePhase = "saved" | "unsaved" | "saving" | "repairs" | "invalid" | "failed";

export interface CaseFileWorkspace {
  document: CaseFileDocument;
  acceptedCaseFile: CaseFileDocument;
  versions: Record<string, number>;
  dirtyTargetIds: string[];
  formErrors: Record<string, string>;
  savePhase: SavePhase;
  saveError: string | null;
  saveDetails: { path?: string | null; message: string }[];
  saveDelayMs: number;
}

export interface VideoState {
  currentTime: number;
  duration: number | null;
  mediaGeneration: number;
  paused: boolean;
  playbackRate: number;
  seekRequest: { generation: number; time: number };
  previewStatus: "idle" | "seeking" | "ready" | "unavailable";
  shownFrameTime: number | null;
  previewMessage: string | null;
}

export interface AppState {
  evalDirectory: EvalDirectoryDocument | null;
  evalDirectoryLoading: boolean;
  evalDirectoryError: string | null;
  selectedCaseId: string | null;
  selectedTargetId: string | null;
  selectedSampleId: string | null;
  lastTargetByCase: Record<string, string>;
  caseFileWorkspaces: Record<string, CaseFileWorkspace>;
  loadingCaseFiles: Record<string, boolean>;
  caseFileLoadErrors: Record<string, string>;
  caseFilter: string;
  targetFilter: string;
  zoom: 1 | 2 | 4 | 8;
  selectedLaneOnly: boolean;
  sourceDrawer: "case_file" | "eval_config_file" | null;
  helpOpen: boolean;
  toast: string | null;
  video: VideoState;
}

export const initialState: AppState = {
  evalDirectory: null,
  evalDirectoryLoading: true,
  evalDirectoryError: null,
  selectedCaseId: null,
  selectedTargetId: null,
  selectedSampleId: null,
  lastTargetByCase: {},
  caseFileWorkspaces: {},
  loadingCaseFiles: {},
  caseFileLoadErrors: {},
  caseFilter: "",
  targetFilter: "",
  zoom: 1,
  selectedLaneOnly: false,
  sourceDrawer: null,
  helpOpen: false,
  toast: null,
  video: {
    currentTime: 0,
    duration: null,
    mediaGeneration: 0,
    paused: true,
    playbackRate: 1,
    seekRequest: { generation: 0, time: 0 },
    previewStatus: "idle",
    shownFrameTime: null,
    previewMessage: null,
  },
};

export type AppAction =
  | {
      type: "EVAL_DIRECTORY_LOADED";
      evalDirectory: EvalDirectoryDocument;
      initialCaseId: string | null;
    }
  | { type: "EVAL_DIRECTORY_FAILED"; message: string }
  | { type: "CASE_FILE_LOADING"; caseId: string }
  | { type: "CASE_FILE_LOAD_FAILED"; caseId: string; message: string }
  | {
      type: "CASE_FILE_LOADED";
      document: CaseFileDocument;
      preferredTargetId?: string | null;
    }
  | { type: "CANCEL_TARGET_DRAFT"; caseId: string; targetId: string }
  | { type: "SELECT_CASE"; caseId: string }
  | { type: "SELECT_TARGET"; targetId: string }
  | {
      type: "SELECT_SAMPLE";
      targetId: string;
      sampleId: string;
      timestamp: number;
    }
  | {
      type: "REPLACE_TARGET_SAMPLES";
      caseId: string;
      targetId: string;
      samples: ReviewSample[];
      immediate: boolean;
    }
  | { type: "SET_FORM_ERROR"; key: string; message: string | null }
  | { type: "CLEAR_FORM_ERRORS"; caseId: string; keys: string[] }
  | {
      type: "SAVE_START";
      caseId: string;
    }
  | {
      type: "SAVE_REPAIRS_REQUIRED";
      caseId: string;
    }
  | {
      type: "SAVE_SUCCESS";
      caseId: string;
      document: CaseFileDocument;
      submittedVersions: Record<string, number>;
    }
  | {
      type: "SAVE_FAILED";
      caseId: string;
      message: string;
      details: { path?: string | null; message: string }[];
    }
  | { type: "DISCARD_AND_LOAD"; document: CaseFileDocument }
  | { type: "SET_CASE_FILTER"; value: string }
  | { type: "SET_TARGET_FILTER"; value: string }
  | { type: "SET_ZOOM"; value: 1 | 2 | 4 | 8 }
  | { type: "SET_SELECTED_LANE_ONLY"; value: boolean }
  | { type: "SET_SOURCE_DRAWER"; value: "case_file" | "eval_config_file" | null }
  | { type: "SET_HELP_OPEN"; value: boolean }
  | { type: "SET_TOAST"; value: string | null }
  | { type: "REQUEST_SEEK"; time: number }
  | { type: "VIDEO_PATCH"; patch: Partial<Omit<VideoState, "seekRequest">> };

function workspaceFor(document: CaseFileDocument): CaseFileWorkspace {
  return {
    document,
    acceptedCaseFile: document,
    versions: Object.fromEntries(document.targets.map((target) => [target.id, 0])),
    dirtyTargetIds: [],
    formErrors: {},
    savePhase: "saved",
    saveError: null,
    saveDetails: [],
    saveDelayMs: 400,
  };
}

function firstTargetId(document: CaseFileDocument): string | null {
  return document.targets[0]?.id ?? null;
}

function firstSampleId(document: CaseFileDocument, targetId: string | null): string | null {
  return document.targets.find((target) => target.id === targetId)?.samples[0]?.id ?? null;
}

function videoAtSample(video: VideoState, sample: ReviewSample | undefined): VideoState {
  if (!sample) return video;
  return {
    ...video,
    currentTime: sample.timestamp_s,
    seekRequest: {
      generation: video.seekRequest.generation + 1,
      time: sample.timestamp_s,
    },
    previewStatus: "seeking",
    shownFrameTime: null,
    previewMessage: null,
  };
}

function phaseAfterFormErrors(
  workspace: CaseFileWorkspace,
  formErrors: Record<string, string>,
): SavePhase {
  if (Object.keys(formErrors).length > 0) return "invalid";
  if (workspace.saveError) return "failed";
  return workspace.dirtyTargetIds.length > 0 ? "unsaved" : "saved";
}

export function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case "EVAL_DIRECTORY_LOADED": {
      const selectedCaseId =
        action.initialCaseId &&
        action.evalDirectory.cases.some((item) => item.id === action.initialCaseId)
          ? action.initialCaseId
          : (action.evalDirectory.cases[0]?.id ?? null);
      return {
        ...state,
        evalDirectory: action.evalDirectory,
        evalDirectoryLoading: false,
        evalDirectoryError: null,
        selectedCaseId,
      };
    }
    case "EVAL_DIRECTORY_FAILED":
      return { ...state, evalDirectoryLoading: false, evalDirectoryError: action.message };
    case "CASE_FILE_LOADING": {
      const caseFileLoadErrors = { ...state.caseFileLoadErrors };
      delete caseFileLoadErrors[action.caseId];
      return {
        ...state,
        loadingCaseFiles: { ...state.loadingCaseFiles, [action.caseId]: true },
        caseFileLoadErrors,
      };
    }
    case "CASE_FILE_LOAD_FAILED":
      return {
        ...state,
        loadingCaseFiles: { ...state.loadingCaseFiles, [action.caseId]: false },
        caseFileLoadErrors: {
          ...state.caseFileLoadErrors,
          [action.caseId]: action.message,
        },
      };
    case "CASE_FILE_LOADED": {
      const caseFileLoadErrors = Object.fromEntries(
        Object.entries(state.caseFileLoadErrors).filter(
          ([caseId]) => caseId !== action.document.id,
        ),
      );
      const cachedState: AppState = {
        ...state,
        caseFileWorkspaces: {
          ...state.caseFileWorkspaces,
          [action.document.id]: workspaceFor(action.document),
        },
        loadingCaseFiles: { ...state.loadingCaseFiles, [action.document.id]: false },
        caseFileLoadErrors,
      };
      if (state.selectedCaseId !== action.document.id) return cachedState;
      const oldWorkspace = state.caseFileWorkspaces[action.document.id];
      const preferred = action.preferredTargetId;
      const targetId =
        preferred && action.document.targets.some((target) => target.id === preferred)
          ? preferred
          : oldWorkspace &&
              action.document.targets.some((target) => target.id === state.selectedTargetId)
            ? state.selectedTargetId
            : firstTargetId(action.document);
      const sample = action.document.targets
        .find((target) => target.id === targetId)
        ?.samples.at(0);
      return {
        ...cachedState,
        selectedTargetId: targetId,
        selectedSampleId: sample?.id ?? null,
        lastTargetByCase: targetId
          ? { ...state.lastTargetByCase, [action.document.id]: targetId }
          : state.lastTargetByCase,
        video: videoAtSample(
          {
            ...initialState.video,
            duration: action.document.video?.duration_s ?? null,
          },
          sample,
        ),
      };
    }
    case "SELECT_CASE": {
      const cached = state.caseFileWorkspaces[action.caseId]?.document;
      const remembered = state.lastTargetByCase[action.caseId];
      const targetId =
        cached && remembered && cached.targets.some((item) => item.id === remembered)
          ? remembered
          : cached
            ? firstTargetId(cached)
            : null;
      const sample = cached?.targets.find((target) => target.id === targetId)?.samples.at(0);
      const baseVideo = cached
        ? { ...initialState.video, duration: cached.video?.duration_s ?? null }
        : initialState.video;
      return {
        ...state,
        selectedCaseId: action.caseId,
        selectedTargetId: targetId,
        selectedSampleId: sample?.id ?? null,
        targetFilter: "",
        sourceDrawer: null,
        video: videoAtSample(baseVideo, sample),
      };
    }
    case "SELECT_TARGET": {
      const workspace = state.selectedCaseId
        ? state.caseFileWorkspaces[state.selectedCaseId]
        : null;
      const sample = workspace?.document.targets
        .find((target) => target.id === action.targetId)
        ?.samples.at(0);
      return {
        ...state,
        selectedTargetId: action.targetId,
        selectedSampleId: sample?.id ?? null,
        lastTargetByCase: state.selectedCaseId
          ? {
              ...state.lastTargetByCase,
              [state.selectedCaseId]: action.targetId,
            }
          : state.lastTargetByCase,
        video: videoAtSample(state.video, sample),
      };
    }
    case "SELECT_SAMPLE":
      return {
        ...state,
        selectedTargetId: action.targetId,
        selectedSampleId: action.sampleId,
        lastTargetByCase: state.selectedCaseId
          ? {
              ...state.lastTargetByCase,
              [state.selectedCaseId]: action.targetId,
            }
          : state.lastTargetByCase,
        video: {
          ...state.video,
          currentTime: action.timestamp,
          seekRequest: {
            generation: state.video.seekRequest.generation + 1,
            time: action.timestamp,
          },
          previewStatus: "seeking",
          shownFrameTime: null,
          previewMessage: null,
        },
      };
    case "REPLACE_TARGET_SAMPLES": {
      const workspace = state.caseFileWorkspaces[action.caseId];
      if (!workspace) return state;
      const targets = workspace.document.targets.map((target) =>
        target.id === action.targetId ? { ...target, samples: action.samples } : target,
      );
      const dirtyTargetIds = workspace.dirtyTargetIds.includes(action.targetId)
        ? workspace.dirtyTargetIds
        : [...workspace.dirtyTargetIds, action.targetId];
      return {
        ...state,
        caseFileWorkspaces: {
          ...state.caseFileWorkspaces,
          [action.caseId]: {
            ...workspace,
            document: { ...workspace.document, targets },
            versions: {
              ...workspace.versions,
              [action.targetId]: (workspace.versions[action.targetId] ?? 0) + 1,
            },
            dirtyTargetIds,
            savePhase:
              Object.keys(workspace.formErrors).length > 0
                ? "invalid"
                : workspace.saveError
                  ? "failed"
                  : "unsaved",
            saveError: workspace.saveError,
            saveDetails: workspace.saveDetails,
            saveDelayMs: action.immediate ? 0 : 400,
          },
        },
      };
    }
    case "CANCEL_TARGET_DRAFT": {
      const workspace = state.caseFileWorkspaces[action.caseId];
      if (!workspace) return state;
      const acceptedTarget = workspace.acceptedCaseFile.targets.find(
        (target) => target.id === action.targetId,
      );
      if (!acceptedTarget) return state;
      const dirtyTargetIds = workspace.dirtyTargetIds.filter(
        (targetId) => targetId !== action.targetId,
      );
      return {
        ...state,
        selectedSampleId: null,
        caseFileWorkspaces: {
          ...state.caseFileWorkspaces,
          [action.caseId]: {
            ...workspace,
            document: {
              ...workspace.document,
              targets: workspace.document.targets.map((target) =>
                target.id === action.targetId ? acceptedTarget : target,
              ),
            },
            dirtyTargetIds,
            savePhase: dirtyTargetIds.length ? "unsaved" : "saved",
            saveError: null,
            saveDetails: [],
          },
        },
      };
    }
    case "SET_FORM_ERROR": {
      if (!state.selectedCaseId) return state;
      const workspace = state.caseFileWorkspaces[state.selectedCaseId];
      if (!workspace) return state;
      const formErrors = { ...workspace.formErrors };
      if (action.message) formErrors[action.key] = action.message;
      else delete formErrors[action.key];
      return {
        ...state,
        caseFileWorkspaces: {
          ...state.caseFileWorkspaces,
          [state.selectedCaseId]: {
            ...workspace,
            formErrors,
            savePhase: phaseAfterFormErrors(workspace, formErrors),
          },
        },
      };
    }
    case "CLEAR_FORM_ERRORS": {
      const workspace = state.caseFileWorkspaces[action.caseId];
      if (!workspace || action.keys.length === 0) return state;
      const formErrors = { ...workspace.formErrors };
      for (const key of action.keys) delete formErrors[key];
      return {
        ...state,
        caseFileWorkspaces: {
          ...state.caseFileWorkspaces,
          [action.caseId]: {
            ...workspace,
            formErrors,
            savePhase: phaseAfterFormErrors(workspace, formErrors),
          },
        },
      };
    }
    case "SAVE_START": {
      const workspace = state.caseFileWorkspaces[action.caseId];
      if (!workspace) return state;
      return {
        ...state,
        caseFileWorkspaces: {
          ...state.caseFileWorkspaces,
          [action.caseId]: { ...workspace, savePhase: "saving" },
        },
      };
    }
    case "SAVE_REPAIRS_REQUIRED": {
      const workspace = state.caseFileWorkspaces[action.caseId];
      if (!workspace) return state;
      return {
        ...state,
        caseFileWorkspaces: {
          ...state.caseFileWorkspaces,
          [action.caseId]: { ...workspace, savePhase: "repairs" },
        },
      };
    }
    case "SAVE_SUCCESS": {
      const workspace = state.caseFileWorkspaces[action.caseId];
      if (!workspace) return state;
      const currentTargets = new Map(
        workspace.document.targets.map((target) => [target.id, target]),
      );
      const mergedTargets = action.document.targets.map((acceptedTarget) => {
        const submittedVersion = action.submittedVersions[acceptedTarget.id];
        if (
          submittedVersion !== undefined &&
          workspace.versions[acceptedTarget.id] !== submittedVersion
        ) {
          return currentTargets.get(acceptedTarget.id) ?? acceptedTarget;
        }
        if (
          submittedVersion === undefined &&
          workspace.dirtyTargetIds.includes(acceptedTarget.id)
        ) {
          return currentTargets.get(acceptedTarget.id) ?? acceptedTarget;
        }
        return acceptedTarget;
      });
      const dirtyTargetIds = workspace.dirtyTargetIds.filter(
        (targetId) =>
          action.submittedVersions[targetId] === undefined ||
          workspace.versions[targetId] !== action.submittedVersions[targetId],
      );
      return {
        ...state,
        evalDirectory: state.evalDirectory
          ? {
              ...state.evalDirectory,
              cases: state.evalDirectory.cases.map((summary) =>
                summary.id === action.caseId
                  ? {
                      ...summary,
                      sample_count: action.document.targets.reduce(
                        (sum, target) => sum + target.samples.length,
                        0,
                      ),
                      target_count: action.document.targets.length,
                      status: action.document.status === "blocked" ? "blocked" : "ready",
                    }
                  : summary,
              ),
            }
          : null,
        caseFileWorkspaces: {
          ...state.caseFileWorkspaces,
          [action.caseId]: {
            ...workspace,
            document: { ...action.document, targets: mergedTargets },
            acceptedCaseFile: action.document,
            dirtyTargetIds,
            savePhase:
              Object.keys(workspace.formErrors).length > 0
                ? "invalid"
                : dirtyTargetIds.length > 0
                  ? "unsaved"
                  : "saved",
            saveError: null,
            saveDetails: [],
            saveDelayMs: 0,
          },
        },
      };
    }
    case "SAVE_FAILED": {
      const workspace = state.caseFileWorkspaces[action.caseId];
      if (!workspace) return state;
      return {
        ...state,
        caseFileWorkspaces: {
          ...state.caseFileWorkspaces,
          [action.caseId]: {
            ...workspace,
            savePhase: "failed",
            saveError: action.message,
            saveDetails: action.details,
          },
        },
      };
    }
    case "DISCARD_AND_LOAD": {
      const cachedState: AppState = {
        ...state,
        caseFileWorkspaces: {
          ...state.caseFileWorkspaces,
          [action.document.id]: workspaceFor(action.document),
        },
        loadingCaseFiles: { ...state.loadingCaseFiles, [action.document.id]: false },
        caseFileLoadErrors: Object.fromEntries(
          Object.entries(state.caseFileLoadErrors).filter(
            ([caseId]) => caseId !== action.document.id,
          ),
        ),
      };
      if (state.selectedCaseId !== action.document.id) return cachedState;
      const targetId =
        state.selectedTargetId &&
        action.document.targets.some((target) => target.id === state.selectedTargetId)
          ? state.selectedTargetId
          : firstTargetId(action.document);
      const target = action.document.targets.find((item) => item.id === targetId);
      const selectedSampleId =
        state.selectedSampleId &&
        target?.samples.some((sample) => sample.id === state.selectedSampleId)
          ? state.selectedSampleId
          : firstSampleId(action.document, targetId);
      const selectedSample = target?.samples.find((sample) => sample.id === selectedSampleId);
      const video = videoAtSample(
        {
          ...initialState.video,
          duration: action.document.video?.duration_s ?? null,
          mediaGeneration: state.video.mediaGeneration + 1,
        },
        selectedSample,
      );
      return {
        ...cachedState,
        selectedTargetId: targetId,
        selectedSampleId,
        lastTargetByCase: targetId
          ? { ...state.lastTargetByCase, [action.document.id]: targetId }
          : state.lastTargetByCase,
        video,
      };
    }
    case "SET_CASE_FILTER":
      return { ...state, caseFilter: action.value };
    case "SET_TARGET_FILTER":
      return { ...state, targetFilter: action.value };
    case "SET_ZOOM":
      return { ...state, zoom: action.value };
    case "SET_SELECTED_LANE_ONLY":
      return { ...state, selectedLaneOnly: action.value };
    case "SET_SOURCE_DRAWER":
      return { ...state, sourceDrawer: action.value };
    case "SET_HELP_OPEN":
      return { ...state, helpOpen: action.value };
    case "SET_TOAST":
      return { ...state, toast: action.value };
    case "REQUEST_SEEK": {
      const currentTime = Math.min(
        state.video.duration ?? Math.max(0, action.time),
        Math.max(0, action.time),
      );
      return {
        ...state,
        video: {
          ...state.video,
          currentTime,
          seekRequest: {
            generation: state.video.seekRequest.generation + 1,
            time: currentTime,
          },
          previewStatus: "seeking",
          shownFrameTime: null,
          previewMessage: null,
        },
      };
    }
    case "VIDEO_PATCH":
      return { ...state, video: { ...state.video, ...action.patch } };
  }
}

export function isRepairComplete(workspace: CaseFileWorkspace): boolean {
  const { document } = workspace;
  if (!document.editing_enabled || document.video?.duration_s === null || !document.video)
    return false;
  const duration = document.video.duration_s;
  return document.targets.every((target) => {
    if (target.samples.length === 0) return false;
    const timestamps = [...target.samples]
      .map((sample) => sample.timestamp_s)
      .sort((left, right) => left - right);
    return timestamps.every(
      (value, index) =>
        Number.isFinite(value) &&
        value >= 0 &&
        value <= duration + SAMPLE_DURATION_TOLERANCE_S &&
        (index === 0 || value - timestamps[index - 1] > 1e-9),
    );
  });
}

export function hasUnsavedWork(workspace: CaseFileWorkspace): boolean {
  return (
    workspace.dirtyTargetIds.length > 0 ||
    Object.keys(workspace.formErrors).length > 0 ||
    workspace.savePhase === "saving" ||
    workspace.savePhase === "failed"
  );
}
