export type ExpectType = "null" | "boolean" | "number" | "string" | "array" | "object";

export type CompareMode =
  | "exact"
  | "numeric"
  | "json_subset"
  | "set_equals"
  | "set_contains_any"
  | "set_contains_all";

export interface SampleOrigin {
  block_index: number;
  kind: "at" | "range";
  every_s: number | null;
}

export interface SampleComparison {
  mode: CompareMode | null;
  tolerance: number | null;
}

export interface ReviewSample {
  id: string;
  timestamp_s: number;
  expect_type: ExpectType;
  expect_json: string;
  field: string | null;
  compare: SampleComparison;
  comment: string | null;
  origin: SampleOrigin | null;
}

export interface DisplayGroup {
  id: string;
  kind: "at" | "range";
  sample_ids: string[];
  start_s: number | null;
  end_s: number | null;
  every_s: number | null;
  timestamps_s: number[];
}

export interface ReviewTarget {
  id: string;
  label: string | null;
  details_yaml: string;
  samples: ReviewSample[];
  display_groups: DisplayGroup[];
}

export interface ValidationIssue {
  code: string;
  message: string;
  path: string | null;
  severity: "error" | "warning";
  repairable: boolean;
}

export interface ErrorDetail {
  path?: string | null;
  message: string;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: ErrorDetail[];
}

export interface VideoMetadata {
  url: string | null;
  display_path: string;
  content_type: string | null;
  duration_s: number | null;
  width: number | null;
  height: number | null;
  frame_count: number | null;
}

export interface CaseFileDocument {
  id: string;
  name: string;
  revision: string;
  status: "ready" | "repairable" | "blocked";
  editing_enabled: boolean;
  load_error: ApiErrorBody | null;
  description: string | null;
  case_file_source: string;
  video: VideoMetadata | null;
  targets: ReviewTarget[];
  validation_issues: ValidationIssue[];
}

export interface CaseFileSummary {
  id: string;
  name: string;
  file_name: string;
  description: string | null;
  target_count: number | null;
  sample_count: number | null;
  status: "ready" | "blocked";
  error: ApiErrorBody | null;
}

export interface EvalDirectoryDocument {
  eval_dir: string;
  write_token: string;
  eval_config_source: string | null;
  cases: CaseFileSummary[];
}

export interface ReplaceTargetsRequest {
  targets: Record<string, { samples: ReviewSample[] }>;
}

export interface ApiErrorEnvelope {
  error: ApiErrorBody;
}
