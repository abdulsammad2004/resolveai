"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth/auth-provider";
import { clearSession, getAccessToken, patchSessionWorkspace } from "@/lib/auth/session-store";
import { api, refreshSession } from "./client";
import { ApiError, toApiError } from "./errors";
import type { components } from "./schema";

export type WorkspaceWithRole = components["schemas"]["WorkspaceWithRole"];
export type WorkspaceSettings = components["schemas"]["WorkspaceSettingsOut"];
export type WorkspaceSettingsUpdate = components["schemas"]["WorkspaceSettingsUpdate"];
export type Member = components["schemas"]["MemberOut"];

export type DocumentItem = components["schemas"]["DocumentOut"];
export type DocumentStatus = components["schemas"]["DocumentStatus"];
export type SearchResult = components["schemas"]["SearchResult"];
export type SearchResponse = components["schemas"]["SearchResponse"];

export type ConversationSummary = components["schemas"]["ConversationSummary"];
export type ConversationDetail = components["schemas"]["ConversationDetail"];
export type ConversationPage = components["schemas"]["ConversationPage"];
export type ConversationStatus = ConversationSummary["status"];

const DOCUMENTS_PAGE_SIZE = 100;
const DOCUMENTS_MAX_PAGES = 50;

// Every key starts with the active workspace id so cached data never crosses tenants.
export const queryKeys = {
  workspaces: (wid: string) => [wid, "workspaces"] as const,
  settings: (wid: string) => [wid, "workspace-settings"] as const,
  members: (wid: string) => [wid, "members"] as const,
  documents: (wid: string) => [wid, "documents"] as const,
  conversations: (wid: string) => [wid, "conversations"] as const,
  conversationList: (wid: string, status: ConversationStatus | "all") =>
    [wid, "conversations", "list", status] as const,
  conversation: (wid: string, id: string) => [wid, "conversations", "detail", id] as const,
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

const DOCUMENTS_POLL_MS = 2000;

function isSettling(status: DocumentStatus): boolean {
  return status === "uploaded" || status === "processing";
}

/**
 * Every document in the workspace, following next_cursor until the last page.
 * Shared by the knowledge page and the dashboard (same key, one fetch). Polls every 2s
 * only while a document is still uploaded or processing.
 */
export function useDocuments() {
  const wid = useWorkspaceId();
  return useQuery({
    queryKey: queryKeys.documents(wid),
    queryFn: async (): Promise<DocumentItem[]> => {
      const items: DocumentItem[] = [];
      let cursor: string | undefined;
      for (let page = 0; page < DOCUMENTS_MAX_PAGES; page++) {
        const { data, error, response } = await api.GET("/api/v1/documents", {
          params: { query: { limit: DOCUMENTS_PAGE_SIZE, cursor } },
        });
        if (!data) throw toApiError(error, response);
        items.push(...data.items);
        if (!data.next_cursor) break;
        cursor = data.next_cursor;
      }
      return items;
    },
    refetchInterval: (query) =>
      query.state.data?.some((d) => isSettling(d.status)) ? DOCUMENTS_POLL_MS : false,
  });
}

/** Replace or insert one document in the cached list (newest first). */
function upsertDocument(list: DocumentItem[] | undefined, doc: DocumentItem): DocumentItem[] {
  if (!list) return [doc];
  return list.some((d) => d.id === doc.id)
    ? list.map((d) => (d.id === doc.id ? doc : d))
    : [doc, ...list];
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

/*
 * Multipart upload over XHR so the UI can show real progress (fetch has no upload
 * progress events). Mirrors the API client's auth: one refresh-and-retry on 401.
 */
function sendUpload(
  file: File,
  token: string | null,
  onProgress: (fraction: number) => void,
): Promise<{ status: number; body: unknown }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/v1/documents");
    xhr.withCredentials = true;
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => resolve({ status: xhr.status, body: parseJson(xhr.responseText) });
    // Network failure: surfaced by errorMessage() as "can't reach ResolveAI".
    xhr.onerror = () => reject(new TypeError("Network request failed"));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export function useUploadDocument() {
  const wid = useWorkspaceId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      file,
      onProgress,
    }: {
      file: File;
      onProgress: (fraction: number) => void;
    }): Promise<DocumentItem> => {
      let result = await sendUpload(file, getAccessToken(), onProgress);
      if (result.status === 401) {
        const refreshed = await refreshSession();
        if (!refreshed) {
          clearSession();
          throw new ApiError("Your session has ended. Log in again.", 401);
        }
        onProgress(0);
        result = await sendUpload(file, refreshed.accessToken, onProgress);
      }
      if (result.status !== 202) {
        throw toApiError(result.body, { status: result.status } as Response);
      }
      return result.body as DocumentItem;
    },
    onSuccess: (doc) => {
      queryClient.setQueryData<DocumentItem[]>(queryKeys.documents(wid), (list) =>
        upsertDocument(list, doc),
      );
    },
  });
}

export function useReindexDocument() {
  const wid = useWorkspaceId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const { data, error, response } = await api.POST(
        "/api/v1/documents/{document_id}/reindex",
        { params: { path: { document_id: id } } },
      );
      if (!data) throw toApiError(error, response);
      return data;
    },
    onSuccess: (doc) => {
      queryClient.setQueryData<DocumentItem[]>(queryKeys.documents(wid), (list) =>
        upsertDocument(list, doc),
      );
    },
  });
}

export function useDeleteDocument() {
  const wid = useWorkspaceId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const { error, response } = await api.DELETE("/api/v1/documents/{document_id}", {
        params: { path: { document_id: id } },
      });
      if (!response.ok) throw toApiError(error, response);
      return id;
    },
    onSuccess: (id) => {
      queryClient.setQueryData<DocumentItem[]>(queryKeys.documents(wid), (list) =>
        list?.filter((d) => d.id !== id),
      );
    },
  });
}

/** Semantic search over ready documents. A mutation: it runs when the user submits. */
export function useKnowledgeSearch() {
  return useMutation({
    mutationFn: async (query: string): Promise<SearchResponse> => {
      const { data, error, response } = await api.POST("/api/v1/knowledge/search", {
        body: { query },
      });
      if (!data) throw toApiError(error, response);
      return data;
    },
  });
}

const CONVERSATIONS_PAGE_SIZE = 25;
const CONVERSATIONS_POLL_MS = 10_000;

/** Inbox pages (newest activity first), polled so new widget chats show up on their own. */
export function useConversations(status: ConversationStatus | "all") {
  const wid = useWorkspaceId();
  return useInfiniteQuery({
    queryKey: queryKeys.conversationList(wid, status),
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }): Promise<ConversationPage> => {
      const { data, error, response } = await api.GET("/api/v1/conversations", {
        params: {
          query: {
            limit: CONVERSATIONS_PAGE_SIZE,
            cursor: pageParam,
            status: status === "all" ? undefined : status,
          },
        },
      });
      if (!data) throw toApiError(error, response);
      return data;
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    refetchInterval: CONVERSATIONS_POLL_MS,
  });
}

/** Counts per status (from a one-item page); used by the dashboard tile. */
export function useConversationCounts() {
  const wid = useWorkspaceId();
  return useQuery({
    queryKey: [...queryKeys.conversations(wid), "counts"] as const,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/conversations", {
        params: { query: { limit: 1 } },
      });
      if (!data) throw toApiError(error, response);
      return data.counts;
    },
    refetchInterval: CONVERSATIONS_POLL_MS,
  });
}

export function useConversation(id: string | null) {
  const wid = useWorkspaceId();
  return useQuery({
    queryKey: queryKeys.conversation(wid, id ?? "none"),
    enabled: id !== null,
    queryFn: async (): Promise<ConversationDetail> => {
      const { data, error, response } = await api.GET("/api/v1/conversations/{conversation_id}", {
        params: { path: { conversation_id: id ?? "" } },
      });
      if (!data) throw toApiError(error, response);
      return data;
    },
    refetchInterval: CONVERSATIONS_POLL_MS,
  });
}

export function useUpdateConversationStatus() {
  const wid = useWorkspaceId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, status }: { id: string; status: ConversationStatus }) => {
      const { data, error, response } = await api.PATCH("/api/v1/conversations/{conversation_id}", {
        params: { path: { conversation_id: id } },
        body: { status },
      });
      if (!data) throw toApiError(error, response);
      return data;
    },
    onSuccess: (detail) => {
      queryClient.setQueryData(queryKeys.conversation(wid, detail.id), detail);
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations(wid) });
    },
  });
}
