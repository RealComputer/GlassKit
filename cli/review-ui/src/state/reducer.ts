import type { CaseDocument, ReviewPoint, SuiteBootstrap } from "../api/types.ts";

export const SAMPLE_DURATION_TOLERANCE_S = 0.05;

export type SavePhase = "saved" | "unsaved" | "saving" | "repairs" | "invalid" | "failed";

export interface CaseWorkspace {
  document: CaseDocument;
  acceptedDocument: CaseDocument;
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
  seekRequest: { generation: number; time: number; sampleTime: number | null };
  previewStatus: "idle" | "seeking" | "ready" | "unavailable";
  shownFrameTime: number | null;
  previewMessage: string | null;
}

export interface AppState {
  suite: SuiteBootstrap | null;
  suiteLoading: boolean;
  suiteError: string | null;
  selectedCaseId: string | null;
  selectedTargetId: string | null;
  selectedPointId: string | null;
  lastTargetByCase: Record<string, string>;
  documents: Record<string, CaseWorkspace>;
  loadingCases: Record<string, boolean>;
  caseLoadErrors: Record<string, string>;
  caseFilter: string;
  targetFilter: string;
  zoom: 1 | 2 | 4 | 8;
  selectedLaneOnly: boolean;
  sourceDrawer: "case" | "config" | null;
  helpOpen: boolean;
  toast: string | null;
  video: VideoState;
}

export const initialState: AppState = {
  suite: null,
  suiteLoading: true,
  suiteError: null,
  selectedCaseId: null,
  selectedTargetId: null,
  selectedPointId: null,
  lastTargetByCase: {},
  documents: {},
  loadingCases: {},
  caseLoadErrors: {},
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
    seekRequest: { generation: 0, time: 0, sampleTime: null },
    previewStatus: "idle",
    shownFrameTime: null,
    previewMessage: null,
  },
};

export type AppAction =
  | { type: "SUITE_LOADED"; suite: SuiteBootstrap; initialCaseId: string | null }
  | { type: "SUITE_FAILED"; message: string }
  | { type: "CASE_LOADING"; caseId: string }
  | { type: "CASE_LOAD_FAILED"; caseId: string; message: string }
  | {
      type: "CASE_LOADED";
      document: CaseDocument;
      preferredTargetId?: string | null;
    }
  | { type: "CANCEL_TARGET_DRAFT"; caseId: string; targetId: string }
  | { type: "SELECT_CASE"; caseId: string }
  | { type: "SELECT_TARGET"; targetId: string }
  | {
      type: "SELECT_POINT";
      targetId: string;
      pointId: string;
      timestamp: number;
    }
  | {
      type: "REPLACE_TARGET_POINTS";
      caseId: string;
      targetId: string;
      points: ReviewPoint[];
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
      document: CaseDocument;
      submittedVersions: Record<string, number>;
    }
  | {
      type: "SAVE_FAILED";
      caseId: string;
      message: string;
      details: { path?: string | null; message: string }[];
    }
  | { type: "DISCARD_AND_LOAD"; document: CaseDocument }
  | { type: "SET_CASE_FILTER"; value: string }
  | { type: "SET_TARGET_FILTER"; value: string }
  | { type: "SET_ZOOM"; value: 1 | 2 | 4 | 8 }
  | { type: "SET_SELECTED_LANE_ONLY"; value: boolean }
  | { type: "SET_SOURCE_DRAWER"; value: "case" | "config" | null }
  | { type: "SET_HELP_OPEN"; value: boolean }
  | { type: "SET_TOAST"; value: string | null }
  | {
      type: "REQUEST_SEEK";
      time: number;
      sampleTime?: number | null;
    }
  | { type: "VIDEO_PATCH"; patch: Partial<Omit<VideoState, "seekRequest">> };

function workspaceFor(document: CaseDocument): CaseWorkspace {
  return {
    document,
    acceptedDocument: document,
    versions: Object.fromEntries(document.targets.map((target) => [target.id, 0])),
    dirtyTargetIds: [],
    formErrors: {},
    savePhase: "saved",
    saveError: null,
    saveDetails: [],
    saveDelayMs: 400,
  };
}

function firstTargetId(document: CaseDocument): string | null {
  return document.targets[0]?.id ?? null;
}

function firstPointId(document: CaseDocument, targetId: string | null): string | null {
  return document.targets.find((target) => target.id === targetId)?.points[0]?.id ?? null;
}

function videoAtPoint(video: VideoState, point: ReviewPoint | undefined): VideoState {
  if (!point) return video;
  return {
    ...video,
    currentTime: point.timestamp_s,
    seekRequest: {
      generation: video.seekRequest.generation + 1,
      time: point.timestamp_s,
      sampleTime: point.timestamp_s,
    },
    previewStatus: "seeking",
    shownFrameTime: null,
    previewMessage: null,
  };
}

function phaseAfterFormErrors(
  workspace: CaseWorkspace,
  formErrors: Record<string, string>,
): SavePhase {
  if (Object.keys(formErrors).length > 0) return "invalid";
  if (workspace.saveError) return "failed";
  return workspace.dirtyTargetIds.length > 0 ? "unsaved" : "saved";
}

export function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case "SUITE_LOADED": {
      const selectedCaseId =
        action.initialCaseId && action.suite.cases.some((item) => item.id === action.initialCaseId)
          ? action.initialCaseId
          : (action.suite.cases[0]?.id ?? null);
      return {
        ...state,
        suite: action.suite,
        suiteLoading: false,
        suiteError: null,
        selectedCaseId,
      };
    }
    case "SUITE_FAILED":
      return { ...state, suiteLoading: false, suiteError: action.message };
    case "CASE_LOADING": {
      const caseLoadErrors = { ...state.caseLoadErrors };
      delete caseLoadErrors[action.caseId];
      return {
        ...state,
        loadingCases: { ...state.loadingCases, [action.caseId]: true },
        caseLoadErrors,
      };
    }
    case "CASE_LOAD_FAILED":
      return {
        ...state,
        loadingCases: { ...state.loadingCases, [action.caseId]: false },
        caseLoadErrors: {
          ...state.caseLoadErrors,
          [action.caseId]: action.message,
        },
      };
    case "CASE_LOADED": {
      const caseLoadErrors = Object.fromEntries(
        Object.entries(state.caseLoadErrors).filter(([caseId]) => caseId !== action.document.id),
      );
      const cachedState: AppState = {
        ...state,
        documents: {
          ...state.documents,
          [action.document.id]: workspaceFor(action.document),
        },
        loadingCases: { ...state.loadingCases, [action.document.id]: false },
        caseLoadErrors,
      };
      if (state.selectedCaseId !== action.document.id) return cachedState;
      const oldWorkspace = state.documents[action.document.id];
      const preferred = action.preferredTargetId;
      const targetId =
        preferred && action.document.targets.some((target) => target.id === preferred)
          ? preferred
          : oldWorkspace &&
              action.document.targets.some((target) => target.id === state.selectedTargetId)
            ? state.selectedTargetId
            : firstTargetId(action.document);
      const point = action.document.targets.find((target) => target.id === targetId)?.points.at(0);
      return {
        ...cachedState,
        selectedTargetId: targetId,
        selectedPointId: point?.id ?? null,
        lastTargetByCase: targetId
          ? { ...state.lastTargetByCase, [action.document.id]: targetId }
          : state.lastTargetByCase,
        video: videoAtPoint(
          {
            ...initialState.video,
            duration: action.document.video?.duration_s ?? null,
          },
          point,
        ),
      };
    }
    case "SELECT_CASE": {
      const cached = state.documents[action.caseId]?.document;
      const remembered = state.lastTargetByCase[action.caseId];
      const targetId =
        cached && remembered && cached.targets.some((item) => item.id === remembered)
          ? remembered
          : cached
            ? firstTargetId(cached)
            : null;
      const point = cached?.targets.find((target) => target.id === targetId)?.points.at(0);
      const baseVideo = cached
        ? { ...initialState.video, duration: cached.video?.duration_s ?? null }
        : initialState.video;
      return {
        ...state,
        selectedCaseId: action.caseId,
        selectedTargetId: targetId,
        selectedPointId: point?.id ?? null,
        targetFilter: "",
        sourceDrawer: null,
        video: videoAtPoint(baseVideo, point),
      };
    }
    case "SELECT_TARGET": {
      const workspace = state.selectedCaseId ? state.documents[state.selectedCaseId] : null;
      const point = workspace?.document.targets
        .find((target) => target.id === action.targetId)
        ?.points.at(0);
      return {
        ...state,
        selectedTargetId: action.targetId,
        selectedPointId: point?.id ?? null,
        lastTargetByCase: state.selectedCaseId
          ? {
              ...state.lastTargetByCase,
              [state.selectedCaseId]: action.targetId,
            }
          : state.lastTargetByCase,
        video: videoAtPoint(state.video, point),
      };
    }
    case "SELECT_POINT":
      return {
        ...state,
        selectedTargetId: action.targetId,
        selectedPointId: action.pointId,
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
            sampleTime: action.timestamp,
          },
          previewStatus: "seeking",
          shownFrameTime: null,
          previewMessage: null,
        },
      };
    case "REPLACE_TARGET_POINTS": {
      const workspace = state.documents[action.caseId];
      if (!workspace) return state;
      const targets = workspace.document.targets.map((target) =>
        target.id === action.targetId ? { ...target, points: action.points } : target,
      );
      const dirtyTargetIds = workspace.dirtyTargetIds.includes(action.targetId)
        ? workspace.dirtyTargetIds
        : [...workspace.dirtyTargetIds, action.targetId];
      return {
        ...state,
        documents: {
          ...state.documents,
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
      const workspace = state.documents[action.caseId];
      if (!workspace) return state;
      const acceptedTarget = workspace.acceptedDocument.targets.find(
        (target) => target.id === action.targetId,
      );
      if (!acceptedTarget) return state;
      const dirtyTargetIds = workspace.dirtyTargetIds.filter(
        (targetId) => targetId !== action.targetId,
      );
      return {
        ...state,
        selectedPointId: null,
        documents: {
          ...state.documents,
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
      const workspace = state.documents[state.selectedCaseId];
      if (!workspace) return state;
      const formErrors = { ...workspace.formErrors };
      if (action.message) formErrors[action.key] = action.message;
      else delete formErrors[action.key];
      return {
        ...state,
        documents: {
          ...state.documents,
          [state.selectedCaseId]: {
            ...workspace,
            formErrors,
            savePhase: phaseAfterFormErrors(workspace, formErrors),
          },
        },
      };
    }
    case "CLEAR_FORM_ERRORS": {
      const workspace = state.documents[action.caseId];
      if (!workspace || action.keys.length === 0) return state;
      const formErrors = { ...workspace.formErrors };
      for (const key of action.keys) delete formErrors[key];
      return {
        ...state,
        documents: {
          ...state.documents,
          [action.caseId]: {
            ...workspace,
            formErrors,
            savePhase: phaseAfterFormErrors(workspace, formErrors),
          },
        },
      };
    }
    case "SAVE_START": {
      const workspace = state.documents[action.caseId];
      if (!workspace) return state;
      return {
        ...state,
        documents: {
          ...state.documents,
          [action.caseId]: { ...workspace, savePhase: "saving" },
        },
      };
    }
    case "SAVE_REPAIRS_REQUIRED": {
      const workspace = state.documents[action.caseId];
      if (!workspace) return state;
      return {
        ...state,
        documents: {
          ...state.documents,
          [action.caseId]: { ...workspace, savePhase: "repairs" },
        },
      };
    }
    case "SAVE_SUCCESS": {
      const workspace = state.documents[action.caseId];
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
        suite: state.suite
          ? {
              ...state.suite,
              cases: state.suite.cases.map((summary) =>
                summary.id === action.caseId
                  ? {
                      ...summary,
                      point_count: action.document.targets.reduce(
                        (sum, target) => sum + target.points.length,
                        0,
                      ),
                      target_count: action.document.targets.length,
                      status: action.document.status === "blocked" ? "blocked" : "ready",
                    }
                  : summary,
              ),
            }
          : null,
        documents: {
          ...state.documents,
          [action.caseId]: {
            ...workspace,
            document: { ...action.document, targets: mergedTargets },
            acceptedDocument: action.document,
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
      const workspace = state.documents[action.caseId];
      if (!workspace) return state;
      return {
        ...state,
        documents: {
          ...state.documents,
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
        documents: {
          ...state.documents,
          [action.document.id]: workspaceFor(action.document),
        },
        loadingCases: { ...state.loadingCases, [action.document.id]: false },
        caseLoadErrors: Object.fromEntries(
          Object.entries(state.caseLoadErrors).filter(([caseId]) => caseId !== action.document.id),
        ),
      };
      if (state.selectedCaseId !== action.document.id) return cachedState;
      const targetId =
        state.selectedTargetId &&
        action.document.targets.some((target) => target.id === state.selectedTargetId)
          ? state.selectedTargetId
          : firstTargetId(action.document);
      const target = action.document.targets.find((item) => item.id === targetId);
      const selectedPointId =
        state.selectedPointId && target?.points.some((point) => point.id === state.selectedPointId)
          ? state.selectedPointId
          : firstPointId(action.document, targetId);
      const selectedPoint = target?.points.find((point) => point.id === selectedPointId);
      const video = videoAtPoint(
        {
          ...initialState.video,
          duration: action.document.video?.duration_s ?? null,
          mediaGeneration: state.video.mediaGeneration + 1,
        },
        selectedPoint,
      );
      return {
        ...cachedState,
        selectedTargetId: targetId,
        selectedPointId,
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
            sampleTime: action.sampleTime ?? null,
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

export function isRepairComplete(workspace: CaseWorkspace): boolean {
  const { document } = workspace;
  if (!document.editing_enabled || document.video?.duration_s === null || !document.video)
    return false;
  const duration = document.video.duration_s;
  return document.targets.every((target) => {
    if (target.points.length === 0) return false;
    const timestamps = [...target.points]
      .map((point) => point.timestamp_s)
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

export function hasUnsavedWork(workspace: CaseWorkspace): boolean {
  return (
    workspace.dirtyTargetIds.length > 0 ||
    Object.keys(workspace.formErrors).length > 0 ||
    workspace.savePhase === "saving" ||
    workspace.savePhase === "failed"
  );
}
