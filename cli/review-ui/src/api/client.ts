import type {
  ApiErrorEnvelope,
  CaseFileDocument,
  ReplaceTargetsRequest,
  EvalDirectoryDocument,
} from "./types.ts";

export class ReviewApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: { path?: string | null; message: string }[];

  constructor(
    status: number,
    code: string,
    message: string,
    details: { path?: string | null; message: string }[] = [],
  ) {
    super(message);
    this.name = "ReviewApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function responseError(response: Response): Promise<ReviewApiError> {
  const body = (await response.json().catch(() => null)) as ApiErrorEnvelope | null;
  const error = body && typeof body === "object" && "error" in body ? body.error : null;
  return new ReviewApiError(
    response.status,
    error?.code ?? "request_failed",
    error?.message ?? `Request failed with HTTP ${response.status}.`,
    error?.details ?? [],
  );
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw await responseError(response);
  }
  const body = (await response.json().catch(() => null)) as T | null;
  if (body === null) {
    throw new ReviewApiError(
      response.status,
      "invalid_response",
      "The review server returned an empty response.",
    );
  }
  return body as T;
}

export interface AuthoritativeFrame {
  image: Blob;
  requestedTime: number;
  mediaTime: number;
  frameIndex: number | null;
  sha256: string;
}

export interface FrameRequestVersion {
  clientId: string;
  generation: number;
}

function requiredFrameNumber(response: Response, name: string): number {
  const rawValue = response.headers.get(name);
  const value = Number(rawValue);
  if (rawValue === null || !rawValue.trim() || !Number.isFinite(value)) {
    throw new ReviewApiError(
      response.status,
      "invalid_response",
      `The exact-frame response omitted a valid ${name} header.`,
    );
  }
  return value;
}

export async function fetchAuthoritativeFrame(
  frameUrl: string,
  timestamp: number,
  signal?: AbortSignal,
  requestVersion?: FrameRequestVersion,
): Promise<AuthoritativeFrame> {
  if (!Number.isFinite(timestamp) || timestamp < 0) {
    throw new ReviewApiError(0, "invalid_frame_time", "Exact frame time must be nonnegative.");
  }
  const canonicalTime = timestamp.toFixed(9).replace(/\.?0+$/, "");
  const separator = frameUrl.includes("?") ? "&" : "?";
  const headers: Record<string, string> = { Accept: "image/png" };
  if (requestVersion) {
    headers["X-GlassKit-Frame-Client"] = requestVersion.clientId;
    headers["X-GlassKit-Frame-Generation"] = String(requestVersion.generation);
  }
  const response = await fetch(
    `${frameUrl}${separator}at=${encodeURIComponent(canonicalTime || "0")}`,
    {
      headers,
      signal,
    },
  );
  if (!response.ok) throw await responseError(response);
  if (response.headers.get("Content-Type")?.split(";", 1)[0] !== "image/png") {
    throw new ReviewApiError(
      response.status,
      "invalid_response",
      "The exact-frame response was not a PNG image.",
    );
  }
  const rawFrameIndex = response.headers.get("X-GlassKit-Frame-Index");
  const frameIndex = rawFrameIndex === null ? null : Number(rawFrameIndex);
  if (frameIndex !== null && (!Number.isInteger(frameIndex) || frameIndex < 0)) {
    throw new ReviewApiError(
      response.status,
      "invalid_response",
      "The exact-frame response contained an invalid frame index.",
    );
  }
  const sha256 = response.headers.get("X-GlassKit-Frame-SHA256");
  if (!sha256?.startsWith("sha256-")) {
    throw new ReviewApiError(
      response.status,
      "invalid_response",
      "The exact-frame response omitted its pixel digest.",
    );
  }
  return {
    image: await response.blob(),
    requestedTime: requiredFrameNumber(response, "X-GlassKit-Requested-Time"),
    mediaTime: requiredFrameNumber(response, "X-GlassKit-Media-Time"),
    frameIndex,
    sha256,
  };
}

export async function fetchEvalDirectory(signal?: AbortSignal): Promise<EvalDirectoryDocument> {
  return readJson(
    await fetch("/api/eval-directory", {
      headers: { Accept: "application/json" },
      signal,
    }),
  );
}

export async function fetchCaseFile(
  caseId: string,
  signal?: AbortSignal,
): Promise<CaseFileDocument> {
  return readJson(
    await fetch(`/api/case-files/${encodeURIComponent(caseId)}`, {
      headers: { Accept: "application/json" },
      signal,
    }),
  );
}

export async function replaceTargetSamples(
  caseId: string,
  writeToken: string,
  request: ReplaceTargetsRequest,
  signal?: AbortSignal,
): Promise<CaseFileDocument> {
  return readJson(
    await fetch(`/api/case-files/${encodeURIComponent(caseId)}/samples`, {
      method: "PUT",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-GlassKit-Write-Token": writeToken,
      },
      body: JSON.stringify(request),
      signal,
    }),
  );
}
