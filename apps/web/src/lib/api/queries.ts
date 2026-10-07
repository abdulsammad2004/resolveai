"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth/auth-provider";
import { getAccessToken, patchSessionWorkspace } from "@/lib/auth/session-store";
import { api } from "./client";
import { toApiError } from "./errors";
import type { components } from "./schema";

export type WorkspaceWithRole = components["schemas"]["WorkspaceWithRole"];
export type WorkspaceSettings = components["schemas"]["WorkspaceSettingsOut"];
export type WorkspaceSettingsUpdate = components["schemas"]["WorkspaceSettingsUpdate"];
export type Member = components["schemas"]["MemberOut"];

export interface DocumentItem {
  id: string;
  workspace_id: string;
  title: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  status: "uploaded" | "processing" | "ready" | "failed";
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

export interface DocumentPage {
  items: DocumentItem[];
  next_cursor: string | null;
}

// Every key starts with the active workspace id so cached data never crosses tenants.
export const queryKeys = {
  workspaces: (wid: string) => [wid, "workspaces"] as const,
  settings: (wid: string) => [wid, "workspace-settings"] as const,
  members: (wid: string) => [wid, "members"] as const,
  documents: (wid: string) => [wid, "documents"] as const,
};

function useWorkspaceId(): string {
  const { workspace } = useAuth();
  return workspace?.id ?? "none";
}

export function useWorkspaces() {
  const wid = useWorkspaceId();
  return useQuery({
    queryKey: queryKeys.workspaces(wid),
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/workspaces");
      if (!data) throw toApiError(error, response);
      return data;
    },
  });
}

export function useCreateWorkspace() {
  return useMutation({
    mutationFn: async (name: string) => {
      const { data, error, response } = await api.POST("/api/v1/workspaces", {
        body: { name },
      });
      if (!data) throw toApiError(error, response, "workspace");
      return data;
    },
  });
}

export function useWorkspaceSettings() {
  const wid = useWorkspaceId();
  return useQuery({
    queryKey: queryKeys.settings(wid),
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/workspace/settings");
      if (!data) throw toApiError(error, response, "settings");
      return data;
    },
  });
}

export function useUpdateWorkspaceSettings() {
  const wid = useWorkspaceId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: WorkspaceSettingsUpdate) => {
      const { data, error, response } = await api.PATCH("/api/v1/workspace/settings", {
        body,
      });
      if (!data) throw toApiError(error, response, "settings");
      return data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.settings(wid), data);
      queryClient.invalidateQueries({ queryKey: queryKeys.workspaces(wid) });
      patchSessionWorkspace({ id: data.id, name: data.name, slug: data.slug });
    },
  });
}

export function useMembers() {
  const wid = useWorkspaceId();
  return useQuery({
    queryKey: queryKeys.members(wid),
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/members");
      if (!data) throw toApiError(error, response);
      return data;
    },
  });
}

export function useDocuments() {
  const wid = useWorkspaceId();
  return useQuery({
    queryKey: queryKeys.documents(wid),
    queryFn: async (): Promise<DocumentPage> => {
      const token = getAccessToken();
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      try {
        const res = await fetch("/api/v1/documents", {
          method: "GET",
          headers,
          credentials: "include",
        });
        if (!res.ok) {
          if (res.status === 404) {
            return { items: [], next_cursor: null };
          }
          return { items: [], next_cursor: null };
        }
        const data = (await res.json()) as DocumentPage;
        return data;
      } catch {
        return { items: [], next_cursor: null };
      }
    },
  });
}
