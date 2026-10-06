import type { components } from "@/lib/api/schema";

export type AuthResponse = components["schemas"]["AuthResponse"];
export type User = components["schemas"]["UserOut"];
export type Workspace = components["schemas"]["WorkspaceOut"];
export type Role = components["schemas"]["Role"];

export type Session = {
  accessToken: string;
  user: User;
  workspace: Workspace;
  role: Role;
};

/*
 * The session lives in module memory only: never localStorage or sessionStorage.
 * A page reload drops it; AuthProvider restores it from the httpOnly refresh cookie.
 * The API client and AuthProvider both read and write it here, so a token rotated
 * by a background 401 retry is immediately visible to the UI.
 */
let session: Session | null = null;
let signedOutByUser = false;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

export function getSession(): Session | null {
  return session;
}

export function getAccessToken(): string | null {
  return session?.accessToken ?? null;
}

export function setSessionFromAuth(
  auth: Pick<AuthResponse, "access_token" | "user" | "workspace" | "role">,
): Session {
  signedOutByUser = false;
  session = {
    accessToken: auth.access_token,
    user: auth.user,
    workspace: auth.workspace,
    role: auth.role,
  };
  emit();
  return session;
}

/** Keep the in-memory workspace in step after a rename (same workspace only). */
export function patchSessionWorkspace(workspace: Workspace) {
  if (!session || session.workspace.id !== workspace.id) return;
  session = { ...session, workspace };
  emit();
}

/** True after the user logged out themselves, so guards skip the ?next= return path. */
export function wasSignedOutByUser(): boolean {
  return signedOutByUser;
}

export function clearSession({ byUser = false }: { byUser?: boolean } = {}) {
  signedOutByUser = byUser;
  if (session === null) return;
  session = null;
  emit();
}

export function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
