"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Client } from "openapi-fetch";

import { useAuth } from "@/lib/auth/auth-provider";
import { patchSessionWorkspace } from "@/lib/auth/session-store";
import { api } from "./client";
import { toApiError } from "./errors";
import type { components, paths } from "./schema";

export type WorkspaceWithRole = components["schemas"]["WorkspaceWithRole"];
export type WorkspaceSettings = components["schemas"]["WorkspaceSettingsOut"];
export type WorkspaceSettingsUpdate = components["schemas"]["WorkspaceSettingsUpdate"];
export type Member = components["schemas"]["MemberOut"];

// /documents is not in schema.d.ts yet (run `npm run gen:api` against a current API to add it).
// These mirror DocumentOut and DocumentPage in services/api/app/modules/knowledge/schemas.py.
export interface DocumentItem {
  id: string;
  title: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  content_hash: string;
  status: "uploaded" | "processing" | "ready" | "failed";
  error: string | null;
  chunk_count: number;
  uploaded_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentPage {
  items: DocumentItem[];
  next_cursor: string | null;
}

type DocumentPaths = {
  "/api/v1/documents": {
    parameters: { query?: never; header?: never; path?: never; cookie?: never };
    get: {
      parameters: {
        query?: { cursor?: string; limit?: number };
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        200: {
          headers: { [name: string]: unknown };
          content: { "application/json": DocumentPage };
        };
      };
    };
  };
};

// Same client instance (and auth middleware), typed with the missing path.
const documentsApi = api as unknown as Client<paths & DocumentPaths>;

const DOCUMENTS_PAGE_SIZE = 100;
const DOCUMENTS_MAX_PAGES = 50;

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

/** Every document in the workspace, following next_cursor until the last page. */
export function useDocuments() {
  const wid = useWorkspaceId();
  return useQuery({
    queryKey: queryKeys.documents(wid),
    queryFn: async (): Promise<DocumentItem[]> => {
      const items: DocumentItem[] = [];
      let cursor: string | undefined;
      for (let page = 0; page < DOCUMENTS_MAX_PAGES; page++) {
        const { data, error, response } = await documentsApi.GET("/api/v1/documents", {
          params: { query: { limit: DOCUMENTS_PAGE_SIZE, cursor } },
        });
        if (!data) throw toApiError(error, response);
        items.push(...data.items);
        if (!data.next_cursor) break;
        cursor = data.next_cursor;
      }
      return items;
    },
  });
}
