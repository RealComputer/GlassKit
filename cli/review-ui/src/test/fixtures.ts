import type {
  CaseFileDocument,
  ReviewSample,
  ReviewTarget,
  EvalDirectoryDocument,
} from "../api/types.ts";

export function sample(id: string, timestamp_s: number, expect_json = "false"): ReviewSample {
  return {
    id,
    timestamp_s,
    has_expectation: true,
    expect_type: expect_json === "true" || expect_json === "false" ? "boolean" : "number",
    expect_json,
    field: null,
    compare: { mode: null, tolerance: null },
    comment: null,
    ignore: null,
    origin: { block_index: 0, kind: "at", every_s: null },
  };
}

export function target(
  id: string,
  samples: ReviewSample[] = [sample(`${id}-sample`, 1)],
): ReviewTarget {
  return {
    id,
    label: id.replaceAll("_", " "),
    details_yaml: `label: ${id}\n`,
    sample_defaults: {
      field: null,
      compare: { mode: null, tolerance: null },
    },
    samples,
    display_groups: samples.map((item, index) => ({
      id: `group-${index}`,
      kind: "at",
      sample_ids: [item.id],
      start_s: null,
      end_s: null,
      every_s: null,
      timestamps_s: [item.timestamp_s],
    })),
  };
}

export function caseFile(
  targets: ReviewTarget[] = [target("target_a"), target("target_b")],
): CaseFileDocument {
  return {
    id: "case-001.yaml",
    name: "case-001",
    revision: "revision-1",
    status: "ready",
    editing_enabled: true,
    load_error: null,
    description: "A fixture case",
    case_file_source: "video: fixture.mp4\n",
    video: {
      url: "/api/case-files/case-001.yaml/video",
      frame_url: null,
      display_path: "fixture.mp4",
      content_type: "video/mp4",
      duration_s: 10,
      width: 64,
      height: 64,
      frame_count: 10,
    },
    targets,
    validation_issues: [],
  };
}

export function evalDirectory(): EvalDirectoryDocument {
  return {
    eval_dir: "/tmp/eval",
    write_token: "secret",
    eval_config_source: "sampling:\n  every_s: 0.5\n",
    cases: [
      {
        id: "case-001.yaml",
        name: "case-001",
        file_name: "case-001.yaml",
        description: "A fixture case",
        target_count: 2,
        sample_count: 2,
        status: "ready",
        error: null,
      },
      {
        id: "case-002.yaml",
        name: "case-002",
        file_name: "case-002.yaml",
        description: "Another fixture case",
        target_count: 1,
        sample_count: 1,
        status: "ready",
        error: null,
      },
    ],
  };
}
