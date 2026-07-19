import { describe, expect, it } from "vitest";
import { caseFile, sample, target } from "../test/fixtures.ts";
import { appReducer, initialState, isRepairComplete } from "./reducer.ts";

function loadedState() {
  const doc = caseFile();
  return appReducer(
    { ...initialState, selectedCaseId: doc.id },
    { type: "CASE_FILE_LOADED", document: doc },
  );
}

describe("appReducer save ordering", () => {
  it("caches a late case response without stealing active selection or video state", () => {
    const active = {
      ...caseFile([target("active_target", [sample("active-sample", 4)])]),
      id: "active.yaml",
      name: "active",
    };
    const late = {
      ...caseFile([target("late_target", [sample("late-sample", 8)])]),
      id: "late.yaml",
      name: "late",
    };
    let state = appReducer(
      { ...initialState, selectedCaseId: active.id },
      { type: "CASE_FILE_LOADED", document: active },
    );
    state = appReducer(state, { type: "CASE_FILE_LOADED", document: late });
    expect(state.caseFileWorkspaces).toHaveProperty(late.id);
    expect(state.selectedCaseId).toBe(active.id);
    expect(state.selectedTargetId).toBe("active_target");
    expect(state.selectedSampleId).toBe("active-sample");
    expect(state.video.currentTime).toBe(4);
  });

  it("caches a late discard reload without stealing active selection or video state", () => {
    const active = {
      ...caseFile([target("active_target", [sample("active-sample", 4)])]),
      id: "active.yaml",
      name: "active",
    };
    const late = {
      ...caseFile([target("late_target", [sample("late-sample", 8)])]),
      id: "late.yaml",
      name: "late",
    };
    let state = appReducer(
      { ...initialState, selectedCaseId: active.id },
      { type: "CASE_FILE_LOADED", document: active },
    );
    const activeVideo = state.video;
    state = appReducer(
      {
        ...state,
        loadingCaseFiles: { ...state.loadingCaseFiles, [late.id]: true },
        caseFileLoadErrors: { ...state.caseFileLoadErrors, [late.id]: "Previous failure" },
      },
      { type: "DISCARD_AND_LOAD", document: late },
    );

    expect(state.caseFileWorkspaces[late.id].document).toBe(late);
    expect(state.loadingCaseFiles[late.id]).toBe(false);
    expect(state.caseFileLoadErrors).not.toHaveProperty(late.id);
    expect(state.selectedCaseId).toBe(active.id);
    expect(state.selectedTargetId).toBe("active_target");
    expect(state.selectedSampleId).toBe("active-sample");
    expect(state.video).toBe(activeVideo);
  });

  it("selects and seeks the first sample when a target receives focus", () => {
    let state = loadedState();
    const generation = state.video.seekRequest.generation;
    state = appReducer(state, { type: "SELECT_TARGET", targetId: "target_b" });
    expect(state.selectedSampleId).toBe("target_b-sample");
    expect(state.video.currentTime).toBe(1);
    expect(state.video.seekRequest).toEqual({
      generation: generation + 1,
      time: 1,
    });
  });

  it("selects a followed sample without changing playback", () => {
    const doc = caseFile([target("target_a", [sample("first", 1), sample("followed", 2, "true")])]);
    let state = appReducer(
      { ...initialState, selectedCaseId: doc.id },
      { type: "CASE_FILE_LOADED", document: doc },
    );
    state = appReducer(state, {
      type: "VIDEO_PATCH",
      patch: { currentTime: 2.1, paused: false },
    });
    const video = state.video;

    state = appReducer(state, {
      type: "SELECT_FOLLOWED_SAMPLE",
      targetId: "target_a",
      sampleId: "followed",
    });

    expect(state.selectedSampleId).toBe("followed");
    expect(state.selectedSampleFromPlayback).toBe(true);
    expect(state.video).toBe(video);

    state = appReducer(state, {
      type: "SELECT_SAMPLE",
      targetId: "target_a",
      sampleId: "followed",
      timestamp: 2,
    });
    expect(state.selectedSampleFromPlayback).toBe(false);
  });

  it("reloads retained selection at its sample and refreshes the media element", () => {
    const original = caseFile([target("target_a", [sample("first", 1), sample("retained", 7)])]);
    let state = appReducer(
      { ...initialState, selectedCaseId: original.id },
      { type: "CASE_FILE_LOADED", document: original },
    );
    state = appReducer(state, {
      type: "SELECT_SAMPLE",
      targetId: "target_a",
      sampleId: "retained",
      timestamp: 7,
    });
    const mediaGeneration = state.video.mediaGeneration;
    const reloaded = {
      ...original,
      revision: "reloaded",
      video: original.video ? { ...original.video, display_path: "replacement.mp4" } : null,
    };

    state = appReducer(state, { type: "DISCARD_AND_LOAD", document: reloaded });

    expect(state.selectedSampleId).toBe("retained");
    expect(state.video.currentTime).toBe(7);
    expect(state.video.seekRequest.time).toBe(7);
    expect(state.video.mediaGeneration).toBe(mediaGeneration + 1);
  });

  it("keeps a newer local edit when an older response arrives", () => {
    let state = loadedState();
    const caseId = "case-001.yaml";
    state = appReducer(state, {
      type: "REPLACE_TARGET_SAMPLES",
      caseId,
      targetId: "target_a",
      samples: [sample("target_a-sample", 2, "true")],
      immediate: true,
    });
    const submittedVersion = state.caseFileWorkspaces[caseId].versions.target_a;
    state = appReducer(state, { type: "SAVE_START", caseId });
    state = appReducer(state, {
      type: "REPLACE_TARGET_SAMPLES",
      caseId,
      targetId: "target_a",
      samples: [sample("target_a-sample", 3, "true")],
      immediate: false,
    });
    const serverDocument = caseFile([
      target("target_a", [sample("target_a-sample", 2, "true")]),
      target("target_b", [sample("target_b-sample", 4, "true")]),
    ]);
    state = appReducer(state, {
      type: "SAVE_SUCCESS",
      caseId,
      document: serverDocument,
      submittedVersions: { target_a: submittedVersion },
    });

    expect(state.caseFileWorkspaces[caseId].document.targets[0].samples[0].timestamp_s).toBe(3);
    expect(state.caseFileWorkspaces[caseId].dirtyTargetIds).toEqual(["target_a"]);
    expect(state.caseFileWorkspaces[caseId].savePhase).toBe("unsaved");
    expect(state.caseFileWorkspaces[caseId].acceptedCaseFile.revision).toBe("revision-1");
  });

  it("does not overwrite an unsent dirty target with a full-case response", () => {
    let state = loadedState();
    const caseId = "case-001.yaml";
    state = appReducer(state, {
      type: "REPLACE_TARGET_SAMPLES",
      caseId,
      targetId: "target_a",
      samples: [sample("target_a-sample", 2)],
      immediate: true,
    });
    const versionA = state.caseFileWorkspaces[caseId].versions.target_a;
    state = appReducer(state, {
      type: "REPLACE_TARGET_SAMPLES",
      caseId,
      targetId: "target_b",
      samples: [sample("target_b-sample", 8, "true")],
      immediate: true,
    });
    state = appReducer(state, {
      type: "SAVE_SUCCESS",
      caseId,
      document: caseFile([
        target("target_a", [sample("target_a-sample", 2)]),
        target("target_b", [sample("target_b-sample", 1)]),
      ]),
      submittedVersions: { target_a: versionA },
    });

    expect(state.caseFileWorkspaces[caseId].document.targets[1].samples[0].timestamp_s).toBe(8);
    expect(state.caseFileWorkspaces[caseId].dirtyTargetIds).toEqual(["target_b"]);
  });

  it("does not report Saved when an invalid field draft appeared in flight", () => {
    let state = loadedState();
    const caseId = "case-001.yaml";
    state = appReducer(state, {
      type: "REPLACE_TARGET_SAMPLES",
      caseId,
      targetId: "target_a",
      samples: [sample("target_a-sample", 2)],
      immediate: true,
    });
    const version = state.caseFileWorkspaces[caseId].versions.target_a;
    state = appReducer(state, {
      type: "SET_FORM_ERROR",
      key: "target_a:target_a-sample:expect",
      message: "Enter valid JSON.",
    });
    state = appReducer(state, {
      type: "SAVE_SUCCESS",
      caseId,
      document: caseFile([target("target_a", [sample("target_a-sample", 2)]), target("target_b")]),
      submittedVersions: { target_a: version },
    });
    expect(state.caseFileWorkspaces[caseId].savePhase).toBe("invalid");
    expect(state.caseFileWorkspaces[caseId].formErrors).toHaveProperty(
      "target_a:target_a-sample:expect",
    );
  });

  it("holds a repair draft until all targets have valid bounded samples", () => {
    const repairDocument = caseFile([
      target("empty", []),
      target("too_late", [sample("late", 11)]),
    ]);
    const state = appReducer(
      { ...initialState, selectedCaseId: repairDocument.id },
      { type: "CASE_FILE_LOADED", document: repairDocument },
    );
    expect(isRepairComplete(state.caseFileWorkspaces[repairDocument.id])).toBe(false);
  });

  it("accepts the eval validator tolerance just beyond nominal duration", () => {
    const nearEnd = caseFile([target("near_end", [sample("end", 10.01)])]);
    const state = appReducer(
      { ...initialState, selectedCaseId: nearEnd.id },
      { type: "CASE_FILE_LOADED", document: nearEnd },
    );
    expect(isRepairComplete(state.caseFileWorkspaces[nearEnd.id])).toBe(true);
  });

  it("cancels an unsaved first sample without leaving an empty PUT draft", () => {
    const empty = caseFile([target("empty", [])]);
    let state = appReducer(
      { ...initialState, selectedCaseId: empty.id },
      { type: "CASE_FILE_LOADED", document: empty },
    );
    state = appReducer(state, {
      type: "REPLACE_TARGET_SAMPLES",
      caseId: empty.id,
      targetId: "empty",
      samples: [sample("new", 1)],
      immediate: true,
    });
    state = appReducer(state, {
      type: "CANCEL_TARGET_DRAFT",
      caseId: empty.id,
      targetId: "empty",
    });
    expect(state.caseFileWorkspaces[empty.id].document.targets[0].samples).toEqual([]);
    expect(state.caseFileWorkspaces[empty.id].dirtyTargetIds).toEqual([]);
    expect(state.caseFileWorkspaces[empty.id].savePhase).toBe("saved");
  });

  it("updates and clamps the requested playhead even without playable media", () => {
    const state = appReducer(
      { ...initialState, video: { ...initialState.video, duration: 10, paused: false } },
      { type: "REQUEST_SEEK", time: 12 },
    );
    expect(state.video.currentTime).toBe(10);
    expect(state.video.seekRequest.time).toBe(10);
    expect(state.video.paused).toBe(true);
  });

  it("keeps a failed queue stopped while newer edits remain retryable", () => {
    let state = loadedState();
    const caseId = "case-001.yaml";
    state = appReducer(state, {
      type: "REPLACE_TARGET_SAMPLES",
      caseId,
      targetId: "target_a",
      samples: [sample("target_a-sample", 2)],
      immediate: true,
    });
    state = appReducer(state, {
      type: "SAVE_FAILED",
      caseId,
      message: "disk is read-only",
      details: [],
    });
    state = appReducer(state, {
      type: "REPLACE_TARGET_SAMPLES",
      caseId,
      targetId: "target_a",
      samples: [sample("target_a-sample", 3)],
      immediate: true,
    });
    expect(state.caseFileWorkspaces[caseId].savePhase).toBe("failed");
    expect(state.caseFileWorkspaces[caseId].saveError).toBe("disk is read-only");
    expect(state.caseFileWorkspaces[caseId].document.targets[0].samples[0].timestamp_s).toBe(3);
  });
});
