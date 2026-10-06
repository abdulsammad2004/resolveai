import createClient, { type Middleware } from "openapi-fetch";

import {
  clearSession,
  getAccessToken,
  setSessionFromAuth,
  type Session,
} from "@/lib/auth/session-store";
import type { paths } from "./schema";

/*
 * The single API client. Same origin: Next.js proxies /api/* to FastAPI
 * (next.config.ts), so the refresh cookie scoped to /api/v1/auth just works.
 */
export const api = createClient<paths>({ baseUrl: "", credentials: "include" });

const AUTH_PATH_PREFIX = "/api/v1/auth/";

let refreshInFlight: Promise<Session | null> | null = null;

/*
 * Exchange the refresh cookie for a new access token. Concurrent callers share
 * one request: the API rotates refresh tokens and treats reuse of a rotated
 * token as theft, so two parallel refreshes would revoke the whole session.
 */
export function refreshSession(): Promise<Session | null> {
  refreshInFlight ??= (async () => {
    try {
      const { data } = await api.POST("/api/v1/auth/refresh");
      return data ? setSessionFromAuth(data) : null;
    } catch {
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

// Request bodies are consumed by fetch, so keep a clone per request for one retry.
const pendingRetries = new Map<string, Request>();

const authMiddleware: Middleware = {
  onRequest({ request, schemaPath, id }) {
    const token = getAccessToken();
    if (token && !request.headers.has("Authorization")) {
      request.headers.set("Authorization", `Bearer ${token}`);
    }
    if (!schemaPath.startsWith(AUTH_PATH_PREFIX)) {
      pendingRetries.set(id, request.clone());
    }
    return request;
  },

  async onResponse({ response, schemaPath, id }) {
    const original = pendingRetries.get(id);
    pendingRetries.delete(id);

    if (response.status !== 401 || schemaPath.startsWith(AUTH_PATH_PREFIX) || !original) {
      return response;
    }

    const refreshed = await refreshSession();
    if (!refreshed) {
      // Clearing the session makes the (app) guard redirect to /login?next=<path>.
      clearSession();
      return response;
    }

    const retry = new Request(original, { headers: new Headers(original.headers) });
    retry.headers.set("Authorization", `Bearer ${refreshed.accessToken}`);
    return fetch(retry);
  },

  onError({ id }) {
    pendingRetries.delete(id);
  },
};

api.use(authMiddleware);
