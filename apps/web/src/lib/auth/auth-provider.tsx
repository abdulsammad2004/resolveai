"use client";

import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { api, refreshSession } from "@/lib/api/client";
import { toApiError } from "@/lib/api/errors";
import {
  clearSession,
  getSession,
  setSessionFromAuth,
  subscribe,
  type Role,
  type Session,
  type User,
  type Workspace,
} from "./session-store";

export type AuthStatus = "loading" | "authenticated" | "unauthenticated";

export type SignupInput = {
  full_name: string;
  email: string;
  password: string;
  workspace_name: string;
};

type AuthContextValue = {
  status: AuthStatus;
  user: User | null;
  workspace: Workspace | null;
  role: Role | null;
  login: (email: string, password: string) => Promise<void>;
  signup: (input: SignupInput) => Promise<void>;
  logout: () => Promise<void>;
  switchWorkspace: (workspaceId: string) => Promise<void>;
};

const AuthContext = React.createContext<AuthContextValue | null>(null);

const getServerSession = () => null;

const WIDGET_PATH_PREFIX = "/widget/";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const session: Session | null = React.useSyncExternalStore(
    subscribe,
    getSession,
    getServerSession,
  );
  const [restored, setRestored] = React.useState(false);

  // Restore the session from the httpOnly refresh cookie, then confirm it with /auth/me.
  // Not inside the chat widget (an iframe on customers' sites, with its own widget token).
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      const isWidget = window.location.pathname.startsWith(WIDGET_PATH_PREFIX);
      const refreshed = isWidget ? null : await refreshSession();
      if (refreshed) {
        try {
          const { data } = await api.GET("/api/v1/auth/me");
          if (data) {
            setSessionFromAuth({ ...data, access_token: refreshed.accessToken });
          } else {
            clearSession();
          }
        } catch {
          clearSession();
        }
      }
      if (!cancelled) setRestored(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Cached server state belongs to one workspace; drop it whenever the tenant changes.
  const resetTenantCache = React.useCallback(() => {
    queryClient.removeQueries();
  }, [queryClient]);

  const login = React.useCallback(
    async (email: string, password: string) => {
      const { data, error, response } = await api.POST("/api/v1/auth/login", {
        body: { email, password },
      });
      if (!data) throw toApiError(error, response, "login");
      resetTenantCache();
      setSessionFromAuth(data);
    },
    [resetTenantCache],
  );

  const signup = React.useCallback(
    async (input: SignupInput) => {
      const { data, error, response } = await api.POST("/api/v1/auth/signup", {
        body: input,
      });
      if (!data) throw toApiError(error, response, "signup");
      resetTenantCache();
      setSessionFromAuth(data);
    },
    [resetTenantCache],
  );

  const logout = React.useCallback(async () => {
    try {
      await api.POST("/api/v1/auth/logout");
    } finally {
      clearSession({ byUser: true });
      resetTenantCache();
    }
  }, [resetTenantCache]);

  const switchWorkspace = React.useCallback(
    async (workspaceId: string) => {
      const { data, error, response } = await api.POST(
        "/api/v1/workspaces/{workspace_id}/switch",
        { params: { path: { workspace_id: workspaceId } } },
      );
      if (!data) throw toApiError(error, response, "workspace");
      resetTenantCache();
      setSessionFromAuth(data);
    },
    [resetTenantCache],
  );

  const status: AuthStatus = !restored
    ? "loading"
    : session
      ? "authenticated"
      : "unauthenticated";

  const value = React.useMemo<AuthContextValue>(
    () => ({
      status,
      user: session?.user ?? null,
      workspace: session?.workspace ?? null,
      role: session?.role ?? null,
      login,
      signup,
      logout,
      switchWorkspace,
    }),
    [status, session, login, signup, logout, switchWorkspace],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = React.useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/** Only same-site paths are honoured as ?next= targets (no open redirects). */
export function safeNextPath(raw: string | null | undefined, fallback = "/dashboard"): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) {
    return fallback;
  }
  return raw;
}
