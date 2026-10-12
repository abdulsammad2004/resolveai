"use client";

import { ArrowUp, BookOpenText, Sparkles } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useReducedMotion } from "motion/react";

import { Button } from "@/components/ui/button";

/*
 * A scripted demo: nothing here calls a model or an API. The questions,
 * answers and "Acme Store" docs are written by hand for illustration.
 */

type SourceId = "returns" | "shipping" | "express" | "contact";

const SOURCES: { id: SourceId; title: string }[] = [
  { id: "returns", title: "Returns policy" },
  { id: "shipping", title: "Shipping guide" },
  { id: "express", title: "Express delivery rates" },
  { id: "contact", title: "Contact us" },
];

const ANSWERS: { source: SourceId; match: RegExp; answer: string }[] = [
  {
    source: "express",
    match: /express|overnight|rush|faster|cost|price|how much/i,
    answer:
      "Express shipping costs $12.95 and arrives in 1 to 2 business days. It's free on orders over $150.",
  },
  {
    source: "returns",
    match: /return|refund|send (it )?back|exchange/i,
    answer:
      "You can return unworn items within 30 days of delivery for a full refund. Start the return from your order page and we'll email you a prepaid label.",
  },
  {
    source: "shipping",
    match: /ship|deliver|arrive|how long|when will/i,
    answer:
      "Standard shipping takes 3 to 5 business days in the US. Orders placed before 2 pm ship the same day.",
  },
  {
    source: "contact",
    match: /contact|email|phone|call|talk|human|person|reach|support/i,
    answer:
      "Email help@acme.example or use the chat on any page. We reply within one business day, Monday to Friday.",
  },
];

const FALLBACK = "I don't have that in Acme's docs, so I'd hand this to a person.";

const SUGGESTIONS = [
  "Can I return an item?",
  "How long does shipping take?",
  "How much is express shipping?",
];

type Phase = "idle" | "searching" | "answering" | "done";

const SOURCE_STEP_MS = 320;
const WORD_STEP_MS = 55;

const wait = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

export function TryItPlayground() {
  const reduced = useReducedMotion() ?? false;
  const [input, setInput] = useState("");
  const [question, setQuestion] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [litIndex, setLitIndex] = useState(-1);
  const [cited, setCited] = useState<SourceId | null>(null);
  const [words, setWords] = useState<string[]>([]);
  const [shown, setShown] = useState(0);
  const runId = useRef(0);

  useEffect(() => () => void (runId.current += 1), []);

  async function ask(text: string) {
    const q = text.trim();
    if (!q) return;
    const id = ++runId.current;
    const stale = () => id !== runId.current;
    const hit = ANSWERS.find((a) => a.match.test(q));
    const answerWords = (hit?.answer ?? FALLBACK).split(" ");

    setQuestion(q);
    setInput("");
    setCited(null);
    setWords(answerWords);

    if (reduced) {
      setLitIndex(SOURCES.length - 1);
      setCited(hit?.source ?? null);
      setShown(answerWords.length);
      setPhase("done");
      return;
    }

    setShown(0);
    setLitIndex(-1);
    setPhase("searching");
    for (let i = 0; i < SOURCES.length; i++) {
      await wait(SOURCE_STEP_MS);
      if (stale()) return;
      setLitIndex(i);
    }
    await wait(SOURCE_STEP_MS);
    if (stale()) return;
    setCited(hit?.source ?? null);
    setPhase("answering");
    for (let i = 1; i <= answerWords.length; i++) {
      await wait(WORD_STEP_MS);
      if (stale()) return;
      setShown(i);
    }
    setPhase("done");
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void ask(input);
  }

  const finalAnswer = words.join(" ");
  const citedTitle = SOURCES.find((s) => s.id === cited)?.title;

  return (
    <section id="try-it" className="relative border-t border-line bg-ink py-20 sm:py-28">
      <div className="mx-auto max-w-3xl px-4 sm:px-6 lg:px-8">
        <div className="mb-10 flex flex-col items-center gap-3 text-center">
          <span className="text-sm font-semibold text-ion">Try it</span>
          <h2 className="font-display text-4xl font-bold tracking-tight text-bone sm:text-6xl">
            Ask Acme Store a question
          </h2>
          <p className="max-w-lg text-base text-ash">
            See how an answer is pulled from a shop&apos;s own help docs, with the source attached.
          </p>
        </div>

        <div className="rounded-panel border border-line bg-carbon p-4 shadow-2xl sm:p-6">
          <p className="mb-4 text-xs text-ash">A sample help center, not a live AI</p>

          <form onSubmit={onSubmit} className="flex gap-2">
            <label htmlFor="try-it-input" className="sr-only">
              Your question for Acme Store
            </label>
            <input
              id="try-it-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about returns, shipping or contact"
              maxLength={200}
              autoComplete="off"
              className="h-11 min-w-0 flex-1 rounded-[6px] border border-line bg-carbon-input px-3 text-sm text-bone placeholder:text-ash focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ion"
            />
            <Button type="submit" size="icon" className="size-11" aria-label="Ask" disabled={!input.trim()}>
              <ArrowUp className="size-4" aria-hidden />
            </Button>
          </form>

          <div className="mt-3 flex flex-wrap gap-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => void ask(s)}
                className="pressable rounded-[6px] border border-line bg-carbon-elevated px-3 py-1.5 text-xs text-bone hover:border-ion/50"
              >
                {s}
              </button>
            ))}
          </div>

          {phase !== "idle" && (
            <div className="mt-6 flex flex-col gap-4 border-t border-line pt-5">
              <div className="ml-auto max-w-[85%] rounded-[6px] bg-ion/15 px-3.5 py-2.5 text-sm text-bone">
                {question}
              </div>

              <div>
                <p className="mb-2 text-xs text-ash">Searching Acme&apos;s docs</p>
                <ul className="flex flex-wrap gap-2" aria-hidden>
                  {SOURCES.map((s, i) => {
                    const lit = i <= litIndex;
                    const settled = phase === "answering" || phase === "done";
                    const isCited = s.id === cited;
                    const active = settled ? isCited : lit;
                    return (
                      <li
                        key={s.id}
                        className={`flex items-center gap-1.5 rounded-[4px] border px-2 py-1 text-xs transition-all duration-300 ${
                          active
                            ? "border-ion/50 bg-ion/10 text-bone shadow-[0_0_14px_rgba(123,108,255,0.25)]"
                            : settled || lit
                              ? "border-line bg-carbon-input text-ash/50"
                              : "border-line bg-carbon-input text-ash/40"
                        }`}
                      >
                        <BookOpenText className="size-3" aria-hidden />
                        {s.title}
                      </li>
                    );
                  })}
                </ul>
              </div>

              {(phase === "answering" || phase === "done") && (
                <div className="rounded-[6px] border border-line bg-carbon-elevated p-4">
                  <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-ion">
                    <Sparkles className="size-3.5" aria-hidden />
                    Suggested answer
                  </p>
                  <p className="text-sm leading-relaxed text-bone" aria-hidden>
                    {words.slice(0, shown).join(" ")}
                    {phase === "answering" && (
                      <span className="ml-0.5 inline-block h-3.5 w-1 translate-y-0.5 animate-pulse bg-ion" />
                    )}
                  </p>
                  {phase === "done" && citedTitle && (
                    <span className="mt-3 inline-flex items-center gap-1.5 rounded-[4px] border border-resolved/30 bg-resolved/10 px-2 py-1 text-xs text-resolved animate-in fade-in-0 zoom-in-95 duration-300">
                      <BookOpenText className="size-3" aria-hidden />
                      Source: {citedTitle}
                    </span>
                  )}
                </div>
              )}

              <p className="sr-only" aria-live="polite">
                {phase === "done" ? `${finalAnswer}${citedTitle ? ` Source: ${citedTitle}.` : ""}` : ""}
              </p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
