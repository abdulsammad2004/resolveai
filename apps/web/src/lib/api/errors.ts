/*
 * Every API error has the shape {"error": {"code", "message", "request_id"}}.
 * These helpers turn it into copy written in the interface's voice.
 */

export type ApiErrorBody = {
  error?: { code?: string; message?: string; request_id?: string };
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly apiMessage?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type ErrorContext = "login" | "signup" | "workspace" | "settings" | "generic";

function friendlyMessage(
  status: number,
  apiMessage: string | undefined,
  context: ErrorContext,
): string {
  if (status === 409 && context === "signup") {
    return "That email is already registered. Log in instead.";
  }
  if (status === 401 && context === "login") {
    return "That email and password don't match. Check them and try again.";
  }
  if (status === 403 && context === "settings") {
    return "Only owners and admins can change workspace settings.";
  }
  if (status === 403) {
    return "You don't have access to that in this workspace.";
  }
  if (status === 404 && context === "workspace") {
    return "That workspace isn't available to you any more. Pick another one.";
  }
  if (status === 429) {
    return "Too many attempts. Wait a minute, then try again.";
  }
  if (status === 422 && apiMessage) {
    // Validation messages look like "body.allowed_origins: each origin must ...".
    const detail = apiMessage.replace(/^[\w.]+:\s*/, "").replace(/^Value error,\s*/i, "");
    return `${detail.charAt(0).toUpperCase()}${detail.slice(1)}.`.replace(/\.\.$/, ".");
  }
  if (status >= 500) {
    return "Something went wrong on our side. Try again in a moment.";
  }
  return apiMessage ?? "Something went wrong. Try again.";
}

export function toApiError(
  body: unknown,
  response: Response | undefined,
  context: ErrorContext = "generic",
): ApiError {
  const status = response?.status ?? 0;
  const err = (body as ApiErrorBody | undefined)?.error;
  return new ApiError(friendlyMessage(status, err?.message, context), status, err?.code, err?.message);
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof TypeError) {
    return "We can't reach ResolveAI right now. Check your connection and try again.";
  }
  return "Something went wrong. Try again.";
}
