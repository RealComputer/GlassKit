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

async function readJson<T>(response: Response): Promise<T> {
  const body = (await response.json().catch(() => null)) as T | ApiErrorEnvelope | null;
  if (!response.ok) {
    const error = body && typeof body === "object" && "error" in body ? body.error : null;
    throw new ReviewApiError(
      response.status,
      error?.code ?? "request_failed",
      error?.message ?? `Request failed with HTTP ${response.status}.`,
      error?.details ?? [],
    );
  }
  if (body === null) {
    throw new ReviewApiError(
      response.status,
      "invalid_response",
      "The review server returned an empty response.",
    );
  }
  return body as T;
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
