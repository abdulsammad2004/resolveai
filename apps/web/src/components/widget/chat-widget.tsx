"use client";

import { ArrowUp, Hourglass, RotateCcw, ThumbsDown, ThumbsUp, UsersRound, X } from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { CitedAnswer } from "@/components/widget/cited-answer";
import { cn, initials } from "@/lib/utils";
import {
  HOST_MESSAGE_SOURCE,
  WIDGET_MESSAGE_SOURCE,
  WidgetError,
  createSession,
  fetchConversation,
  loadStoredSession,
  sendFeedback,
  sendMessage,
  storeSession,
  type HostMessage,
  type Rating,
  type StoredSession,
  type WidgetMessage,
  type WidgetMessageToHost,
} from "@/lib/widget/api";

const MAX_CHARS = 2000;
const COUNTER_FROM = 1800;
const HANDSHAKE_TIMEOUT_MS = 1000;
const SUGGESTIONS = [
  "How do returns work?",
  "How long does shipping take?",
  "How do I track my order?",
  "Can I change my order?",
];

type Phase =
  | { kind: "loading" }
  | { kind: "ready" }
  | { kind: "blocked"; message: string }
  | { kind: "offline"; message: string };

type Failure = { content: string; message: string };

function postToHost(type: WidgetMessageToHost["type"], targetOrigin: string) {
  if (window.parent === window) return;
  const message: WidgetMessageToHost = { source: WIDGET_MESSAGE_SOURCE, type };
  window.parent.postMessage(message, targetOrigin);
}

function isHostMessage(data: unknown): data is HostMessage {
  return (
    typeof data === "object" &&
    data !== null &&
    (data as HostMessage).source === HOST_MESSAGE_SOURCE
  );
}

const noSubscribe = () => () => {};

/** True inside an iframe (embedded by widget.js or the settings preview). */
function useEmbedded(): boolean {
  return useSyncExternalStore(
    noSubscribe,
    () => window.parent !== window,
    () => false,
  );
}

function blockedMessage(error: unknown): string | null {
  if (!(error instanceof WidgetError)) return null;
  if (error.status === 404) return "This chat link isn't valid. Check the widget key.";
  if (error.status === 403) return "Chat isn't enabled on this website yet.";
  return null;
}

export function ChatWidget({ publicKey }: { publicKey: string }) {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const embedded = useEmbedded();
  const [workspaceName, setWorkspaceName] = useState("");
  const [messages, setMessages] = useState<WidgetMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState<string | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [rateLimited, setRateLimited] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");

  const session = useRef<StoredSession | null>(null);
  const hostOrigin = useRef<string | undefined>(undefined);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const localIds = useRef(0);
  const focusRequested = useRef(false);
  const busy = streaming !== null;

  /* Session ------------------------------------------------------------------------------ */

  const openSession = useCallback(async (): Promise<StoredSession> => {
    const previous = session.current ?? loadStoredSession(publicKey);
    const created = await createSession({
      public_key: publicKey,
      conversation_id: previous?.conversationId,
      anonymous_id: previous?.anonymousId,
      host_origin: hostOrigin.current,
    });
    session.current = storeSession(publicKey, created);
    setWorkspaceName(created.workspace_name);
    return session.current;
  }, [publicKey]);

  const validToken = useCallback(async (): Promise<string> => {
    const current = session.current;
    if (current && current.expiresAt > Date.now()) return current.token;
    return (await openSession()).token;
  }, [openSession]);

  const connect = useCallback(async () => {
    setPhase({ kind: "loading" });
    try {
      let current = loadStoredSession(publicKey);
      if (!current || current.expiresAt <= Date.now()) current = await openSession();
      session.current = current;
      setWorkspaceName(current.workspaceName);

      let conversation;
      try {
        conversation = await fetchConversation(current.token);
      } catch (error) {
        if (!(error instanceof WidgetError && error.status === 401)) throw error;
        conversation = await fetchConversation((await openSession()).token);
      }
      setMessages(conversation.messages);
      setPhase({ kind: "ready" });
    } catch (error) {
      const blocked = blockedMessage(error);
      setPhase(
        blocked
          ? { kind: "blocked", message: blocked }
          : { kind: "offline", message: "We couldn't connect to the chat. Check your connection." },
      );
    }
  }, [publicKey, openSession]);

  // Learn the embedding page's origin from widget.js, then connect. The browser fills in
  // event.origin, so the host page can't claim to be another site.
  useEffect(() => {
    const isEmbedded = window.parent !== window;
    let settled = false;
    const start = () => {
      if (settled) return;
      settled = true;
      void connect();
    };

    function onMessage(event: MessageEvent) {
      if (event.source !== window.parent || !isHostMessage(event.data)) return;
      if (event.data.type === "init") {
        hostOrigin.current = event.origin;
        start();
      } else if (event.data.type === "open") {
        focusRequested.current = true;
        inputRef.current?.focus();
      }
    }

    window.addEventListener("message", onMessage);
    let timer: number | undefined;
    if (isEmbedded) {
      postToHost("ready", "*"); // carries no data; the reply's origin is what matters
      timer = window.setTimeout(start, HANDSHAKE_TIMEOUT_MS);
    } else {
      start();
    }
    return () => {
      window.removeEventListener("message", onMessage);
      window.clearTimeout(timer);
    };
  }, [connect]);

  // Focus the input once it exists: on load when standalone, or after the host opened us.
  useEffect(() => {
    if (phase.kind === "ready" && (!embedded || focusRequested.current)) inputRef.current?.focus();
  }, [phase.kind, embedded]);

  // Escape closes the panel on the host page (focus returns to its launcher button).
  useEffect(() => {
    if (!embedded) return;
    function onKey(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") postToHost("close", hostOrigin.current ?? "*");
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [embedded]);

  /* Scrolling ---------------------------------------------------------------------------- */

  function onScroll() {
    const el = listRef.current;
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  }

  useEffect(() => {
    const el = listRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [messages, streaming, failure, rateLimited]);

  useEffect(() => {
    if (!rateLimited) return;
    const timer = window.setTimeout(() => setRateLimited(null), 30_000);
    return () => window.clearTimeout(timer);
  }, [rateLimited]);

  /* Sending ------------------------------------------------------------------------------ */

  async function send(content: string, retry = false) {
    const text = content.trim();
    if (!text || busy || phase.kind !== "ready") return;

    setFailure(null);
    setRateLimited(null);
    stickToBottom.current = true;
    localIds.current += 1;
    const localId = `local-${localIds.current}`;
    if (!retry) {
      setMessages((list) => [
        ...list,
        {
          id: localId,
          role: "customer",
          content: text,
          citations: [],
          grounded: null,
          created_at: new Date().toISOString(),
        },
      ]);
      setDraft("");
    }
    setStreaming("");
    setAnnouncement("The assistant is answering.");

    const attempt = async (token: string) =>
      sendMessage(token, text, (piece) => setStreaming((s) => (s ?? "") + piece));

    try {
      let answer;
      try {
        answer = await attempt(await validToken());
      } catch (error) {
        if (!(error instanceof WidgetError && error.status === 401)) throw error;
        setStreaming("");
        answer = await attempt((await openSession()).token);
      }
      setMessages((list) => [
        ...list,
        {
          id: answer.id,
          role: "assistant",
          content: answer.content,
          citations: answer.citations,
          grounded: answer.grounded,
          route: answer.route,
          created_at: new Date().toISOString(),
          rating: null,
        },
      ]);
      setAnnouncement(`Answer: ${answer.content.replace(/\[S\d+\]/g, "")}`);
    } catch (error) {
      if (error instanceof WidgetError && error.status === 429) {
        // Nothing was stored: take the message back so it can be sent again.
        if (!retry) {
          setMessages((list) => list.filter((m) => m.id !== localId));
          setDraft(text);
        }
        setRateLimited(error.message);
        setAnnouncement(error.message);
      } else {
        const message =
          error instanceof WidgetError && error.message
            ? error.message
            : "We couldn't send that. Check your connection and try again.";
        setFailure({ content: text, message });
        setAnnouncement(message);
      }
    } finally {
      setStreaming(null);
      inputRef.current?.focus();
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void send(draft);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void send(draft);
    }
  }

  async function rate(messageId: string, rating: Rating) {
    const previous = messages.find((m) => m.id === messageId)?.rating ?? null;
    setMessages((list) => list.map((m) => (m.id === messageId ? { ...m, rating } : m)));
    try {
      await sendFeedback(await validToken(), messageId, rating);
      setAnnouncement("Thanks for the feedback.");
    } catch {
      setMessages((list) =>
        list.map((m) => (m.id === messageId ? { ...m, rating: previous } : m)),
      );
      setAnnouncement("Your feedback couldn't be saved. Try again.");
    }
  }

  /* Rendering ---------------------------------------------------------------------------- */

  const remaining = MAX_CHARS - draft.length;
  const canSend = phase.kind === "ready" && !busy && draft.trim().length > 0 && remaining >= 0;

  return (
    <div className="flex h-dvh flex-col bg-ink text-bone">
      <header className="flex shrink-0 items-center gap-3 border-b border-line bg-carbon px-4 py-3">
        <span
          aria-hidden
          className="flex size-8 shrink-0 items-center justify-center rounded-[6px] bg-ion font-display text-sm font-bold text-ink"
        >
          {workspaceName ? initials(workspaceName) : ""}
        </span>
        <div className="min-w-0 flex-1">
          <h1 className="truncate font-display text-xl font-bold leading-tight tracking-tight">
            {workspaceName || (phase.kind === "loading" ? "Connecting…" : "Support")}
          </h1>
          <p className="truncate text-xs text-ash">AI answers from our help docs</p>
        </div>
        {embedded && (
          <button
            type="button"
            onClick={() => postToHost("close", hostOrigin.current ?? "*")}
            aria-label="Close chat"
            className="pressable rounded-[6px] p-2 text-ash hover:bg-white/[0.06] hover:text-bone focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ion"
          >
            <X className="size-4" aria-hidden />
          </button>
        )}
      </header>

      <div aria-live="polite" aria-atomic="true" className="sr-only">
        {announcement}
      </div>

      {phase.kind === "loading" && (
        <div aria-busy="true" aria-label="Loading chat" className="flex flex-1 flex-col gap-4 p-4">
          <Skeleton className="h-14 w-3/4" />
          <Skeleton className="ml-auto h-10 w-1/2" />
          <Skeleton className="h-20 w-4/5" />
        </div>
      )}

      {(phase.kind === "blocked" || phase.kind === "offline") && (
        <div role="alert" className="flex flex-1 flex-col items-start justify-center gap-4 p-6">
          <p className="font-display text-2xl font-bold tracking-tight">
            {phase.kind === "blocked" ? "Chat unavailable" : "Can't connect"}
          </p>
          <p className="text-sm text-ash">{phase.message}</p>
          {phase.kind === "offline" && (
            <button
              type="button"
              onClick={() => void connect()}
              className="pressable inline-flex h-9 items-center gap-2 rounded-[6px] border border-line px-3 text-sm hover:border-line-strong hover:bg-carbon focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ion"
            >
              <RotateCcw className="size-3.5" aria-hidden />
              Try again
            </button>
          )}
        </div>
      )}

      {phase.kind === "ready" && (
        <>
          <div
            ref={listRef}
            onScroll={onScroll}
            role="log"
            aria-live="off"
            aria-label="Conversation"
            className="flex flex-1 flex-col gap-4 overflow-y-auto overscroll-contain px-4 py-5"
          >
            {messages.length === 0 && !busy && (
              <div className="flex flex-col gap-4">
                <div className="max-w-[90%] rounded-[12px] rounded-tl-[4px] border border-line bg-carbon px-3.5 py-2.5 text-[15px] leading-relaxed">
                  Hi! Ask me anything about {workspaceName || "us"}. I answer from our help docs and
                  show you where each answer comes from.
                </div>
                <div className="flex flex-col gap-2">
                  <p id="suggestions-label" className="text-xs text-ash">
                    Try asking
                  </p>
                  <ul aria-labelledby="suggestions-label" className="flex flex-wrap gap-2">
                    {SUGGESTIONS.map((q) => (
                      <li key={q}>
                        <button
                          type="button"
                          onClick={() => void send(q)}
                          className="pressable h-8 rounded-[6px] border border-ion/30 bg-ion/10 px-3 text-xs font-medium text-bone hover:border-ion/60 hover:bg-ion/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ion"
                        >
                          {q}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            {messages.map((m) =>
              m.role === "customer" ? (
                <div key={m.id} className="flex justify-end">
                  <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-[12px] rounded-tr-[4px] border border-ion/30 bg-ion/15 px-3.5 py-2.5 text-[15px] leading-relaxed">
                    <span className="sr-only">You: </span>
                    {m.content}
                  </p>
                </div>
              ) : (
                <article
                  key={m.id}
                  aria-label={m.role === "agent" ? "Reply from the team" : "Assistant answer"}
                  className="flex max-w-[92%] flex-col gap-2"
                >
                  <div className="rounded-[12px] rounded-tl-[4px] border border-line bg-carbon px-3.5 py-2.5">
                    <CitedAnswer content={m.content} citations={m.citations} />
                    {m.route === "handoff" && (
                      <span className="mt-2 inline-flex items-center gap-1.5 rounded-[4px] border border-line bg-white/[0.04] px-1.5 py-0.5 text-[11px] text-ash">
                        <UsersRound className="size-3" aria-hidden />
                        Passed to the team
                      </span>
                    )}
                  </div>
                  {m.role === "assistant" && (
                    <Feedback rating={m.rating ?? null} onRate={(r) => void rate(m.id, r)} />
                  )}
                </article>
              ),
            )}

            {streaming !== null && (
              <div className="max-w-[92%] rounded-[12px] rounded-tl-[4px] border border-line bg-carbon px-3.5 py-2.5">
                {streaming === "" ? (
                  <span className="flex h-6 items-center gap-1" aria-label="The assistant is typing">
                    <span className="typing-dot size-1.5 rounded-full bg-ash" />
                    <span className="typing-dot size-1.5 rounded-full bg-ash" />
                    <span className="typing-dot size-1.5 rounded-full bg-ash" />
                  </span>
                ) : (
                  <p className="whitespace-pre-wrap break-words text-[15px] leading-relaxed" aria-hidden>
                    {streaming}
                    <span className="stream-caret" />
                  </p>
                )}
              </div>
            )}

            {failure && (
              <div
                role="alert"
                className="flex flex-wrap items-center gap-3 rounded-[6px] border border-urgent/25 bg-urgent/10 px-3 py-2 text-sm"
              >
                <span className="flex-1 text-bone">{failure.message}</span>
                <button
                  type="button"
                  onClick={() => void send(failure.content, true)}
                  className="pressable inline-flex h-8 items-center gap-1.5 rounded-[6px] border border-line bg-carbon px-2.5 text-xs font-medium hover:border-line-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ion"
                >
                  <RotateCcw className="size-3.5" aria-hidden />
                  Retry
                </button>
              </div>
            )}
          </div>

          <form onSubmit={onSubmit} className="shrink-0 border-t border-line bg-carbon p-3">
            {rateLimited && (
              <p
                role="status"
                className="mb-2 flex items-start gap-2 rounded-[6px] border border-review/25 bg-review/10 px-3 py-2 text-xs text-bone"
              >
                <Hourglass className="mt-0.5 size-3.5 shrink-0 text-review" aria-hidden />
                {rateLimited}
              </p>
            )}
            <div className="flex items-end gap-2">
              <label htmlFor="widget-input" className="sr-only">
                Your question
              </label>
              <textarea
                id="widget-input"
                ref={inputRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={onKeyDown}
                rows={1}
                maxLength={MAX_CHARS}
                placeholder="Ask a question…"
                aria-describedby={remaining <= MAX_CHARS - COUNTER_FROM ? "widget-counter" : undefined}
                className="field-sizing-content max-h-32 min-h-10 flex-1 resize-none rounded-[6px] border border-line bg-carbon-input px-3 py-2 text-[15px] leading-snug text-bone placeholder:text-ash focus-visible:border-ion/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ion/40"
              />
              <button
                type="submit"
                disabled={!canSend}
                aria-label="Send"
                className="pressable flex size-10 shrink-0 items-center justify-center rounded-[6px] bg-ion text-ink hover:bg-ion-hover disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ion focus-visible:ring-offset-2 focus-visible:ring-offset-carbon"
              >
                <ArrowUp className="size-4" aria-hidden />
              </button>
            </div>
            <div className="mt-1.5 flex justify-between text-[11px] text-ash">
              <span>Answers can be wrong. A teammate can follow up here.</span>
              {draft.length >= COUNTER_FROM && (
                <span id="widget-counter" className={cn(remaining < 50 && "text-review")}>
                  {remaining} left
                </span>
              )}
            </div>
          </form>
        </>
      )}
    </div>
  );
}

function Feedback({ rating, onRate }: { rating: Rating | null; onRate: (rating: Rating) => void }) {
  const options = [
    { value: "up" as const, label: "Helpful", Icon: ThumbsUp },
    { value: "down" as const, label: "Not helpful", Icon: ThumbsDown },
  ];
  return (
    <div className="flex items-center gap-1 pl-1" role="group" aria-label="Rate this answer">
      {options.map(({ value, label, Icon }) => (
        <button
          key={value}
          type="button"
          onClick={() => onRate(value)}
          aria-pressed={rating === value}
          aria-label={label}
          title={label}
          className={cn(
            "pressable rounded-[4px] p-1.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ion",
            rating === value
              ? value === "up"
                ? "bg-resolved/10 text-resolved"
                : "bg-urgent/10 text-urgent"
              : "text-ash hover:bg-white/[0.06] hover:text-bone",
          )}
        >
          <Icon className="size-3.5" aria-hidden />
        </button>
      ))}
      {rating && <span className="pl-1 text-[11px] text-ash">Thanks!</span>}
    </div>
  );
}
