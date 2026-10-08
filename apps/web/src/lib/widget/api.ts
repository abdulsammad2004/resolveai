/*
 * Widget API calls. Deliberately separate from the dashboard client (lib/api/client.ts):
 * the widget authenticates with its own short-lived widget token, never a user session.
 */

import type { components } from "@/lib/api/schema";
import { readSse } from "./sse";

export type WidgetSession = components["schemas"]["WidgetSessionResponse"];
export type WidgetMessage = components["schemas"]["WidgetMessageOut"];
export type WidgetConversation = components["schemas"]["WidgetConversationOut"];
export type Citation = components["schemas"]["Citation"];
export type Rating = "up" | "down";

/** The SSE `final` event: the stored, authoritative assistant message. */
export type FinalAnswer = {
  id: string;
  content: string;
  citations: Citation[];
  grounded: boolean | null;
  route: NonNullable<WidgetMessage["route"]>;
};

export class WidgetError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "WidgetError";
  }
}

const FALLBACK_ERROR = "Something went wrong. Please try again.";

async function errorFrom(response: Response): Promise<WidgetError> {
  let message = FALLBACK_ERROR;
  try {
    const body = (await response.json()) as { error?: { message?: string } };
    if (body.error?.message) message = body.error.message;
  } catch {
    // Non-JSON error body: keep the generic copy.
  }
  return new WidgetError(message, response.status);
}

async function request<T>(path: string, init: RequestInit & { token?: string }): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (init.token) headers.set("Authorization", `Bearer ${init.token}`);
  const response = await fetch(path, { ...init, headers, credentials: "omit" });
  if (!response.ok) throw await errorFrom(response);
  return (await response.json()) as T;
}

export function createSession(body: {
  public_key: string;
  conversation_id?: string;
  anonymous_id?: string;
  host_origin?: string;
}): Promise<WidgetSession> {
  return request("/api/v1/widget/session", { method: "POST", body: JSON.stringify(body) });
}

export function fetchConversation(token: string): Promise<WidgetConversation> {
  return request("/api/v1/widget/conversation", { method: "GET", token });
}

export function sendFeedback(token: string, messageId: string, rating: Rating): Promise<unknown> {
  return request("/api/v1/widget/feedback", {
    method: "POST",
    token,
    body: JSON.stringify({ message_id: messageId, rating }),
  });
}

/**
 * POST a message and read the answer stream. `onToken` gets raw text as it arrives; the
 * resolved value is the `final` event, which replaces whatever was streamed.
 */
export async function sendMessage(
  token: string,
  content: string,
  onToken: (text: string) => void,
  signal?: AbortSignal,
): Promise<FinalAnswer> {
  const response = await fetch("/api/v1/widget/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ content }),
    credentials: "omit",
    signal,
  });
  if (!response.ok) throw await errorFrom(response);
  if (!response.body) throw new WidgetError(FALLBACK_ERROR, 0);

  for await (const { event, data } of readSse(response.body, signal)) {
    if (event === "token") {
      onToken((JSON.parse(data) as { text: string }).text);
    } else if (event === "final") {
      return JSON.parse(data) as FinalAnswer;
    } else if (event === "error") {
      const message = (JSON.parse(data) as { message?: string }).message;
      throw new WidgetError(message ?? FALLBACK_ERROR, 0);
    }
  }
  throw new WidgetError("The answer was cut off. Please try again.", 0);
}

/* Session persistence: sessionStorage, keyed by public key, so a refresh keeps the chat. */

export type StoredSession = {
  token: string;
  conversationId: string;
  anonymousId: string;
  workspaceName: string;
  expiresAt: number;
};

const storageKey = (publicKey: string) => `resolveai-widget:${publicKey}`;

export function loadStoredSession(publicKey: string): StoredSession | null {
  try {
    const raw = sessionStorage.getItem(storageKey(publicKey));
    return raw ? (JSON.parse(raw) as StoredSession) : null;
  } catch {
    return null;
  }
}

export function storeSession(publicKey: string, session: WidgetSession): StoredSession {
  const stored: StoredSession = {
    token: session.token,
    conversationId: session.conversation_id,
    anonymousId: session.anonymous_id,
    workspaceName: session.workspace_name,
    // Renew a minute early so a message never goes out with an expiring token.
    expiresAt: Date.now() + (session.expires_in - 60) * 1000,
  };
  try {
    sessionStorage.setItem(storageKey(publicKey), JSON.stringify(stored));
  } catch {
    // Storage blocked (privacy mode, partitioned iframe): the chat still works, just not
    // across reloads.
  }
  return stored;
}

/* postMessage protocol between the iframe and widget.js on the host page. */

export const WIDGET_MESSAGE_SOURCE = "resolveai-widget";
export const HOST_MESSAGE_SOURCE = "resolveai-host";

export type HostMessage = { source: typeof HOST_MESSAGE_SOURCE; type: "init" | "open" };
export type WidgetMessageToHost = {
  source: typeof WIDGET_MESSAGE_SOURCE;
  type: "ready" | "close";
};
