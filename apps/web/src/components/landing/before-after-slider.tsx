"use client";

import { ChevronsLeftRight, Sparkles } from "lucide-react";
import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

import { StatusChip } from "@/components/status-chip";

// Illustrative messages for a made-up shop; not real customers or tickets.
const MESSAGES = [
  { from: "Jordan", text: "Where is my order? It's been a week.", waiting: "3h", needsApproval: false },
  { from: "Priya", text: "Can I change my delivery address?", waiting: "2h", needsApproval: false },
  { from: "Sam", text: "My mug arrived broken. Can I get a refund?", waiting: "5h", needsApproval: true },
  { from: "Lee", text: "Do you ship to Canada?", waiting: "1h", needsApproval: false },
  { from: "Alex", text: "How do I reset my password?", waiting: "40m", needsApproval: false },
];

const PILE = [
  "top-[14%] left-[4%] -rotate-6",
  "top-[24%] left-[18%] rotate-3",
  "top-[38%] left-[2%] rotate-2",
  "top-[50%] left-[16%] -rotate-3",
  "top-[64%] left-[6%] rotate-6",
];

const clamp = (n: number) => Math.min(100, Math.max(0, n));

export function BeforeAfterSlider() {
  const [pos, setPos] = useState(50);
  const frameRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  function moveTo(clientX: number) {
    const rect = frameRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return;
    setPos(clamp(((clientX - rect.left) / rect.width) * 100));
  }

  function onPointerDown(e: PointerEvent<HTMLDivElement>) {
    dragging.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    moveTo(e.clientX);
  }

  function onPointerMove(e: PointerEvent<HTMLDivElement>) {
    if (dragging.current) moveTo(e.clientX);
  }

  function stopDrag() {
    dragging.current = false;
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const steps: Record<string, number> = { ArrowLeft: -5, ArrowDown: -5, ArrowRight: 5, ArrowUp: 5, PageDown: -20, PageUp: 20 };
    if (e.key in steps) setPos((p) => clamp(p + steps[e.key]));
    else if (e.key === "Home") setPos(0);
    else if (e.key === "End") setPos(100);
    else return;
    e.preventDefault();
  }

  const rounded = Math.round(pos);

  return (
    <section aria-labelledby="compare-heading" className="border-t border-line bg-ink py-20 sm:py-28">
      <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
        <div className="mb-10 flex flex-col gap-3">
          <span className="text-sm font-semibold text-ion">Before and after</span>
          <h2 id="compare-heading" className="font-display text-4xl font-bold tracking-tight text-bone sm:text-6xl">
            From a pile to a queue
          </h2>
          <p className="max-w-xl text-base text-ash">
            Drag the handle, or focus it and use the arrow keys, to compare an inbox today with one where drafts are
            already waiting for approval.
          </p>
        </div>

        <div
          ref={frameRef}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={stopDrag}
          onPointerCancel={stopDrag}
          className="relative h-[460px] cursor-ew-resize touch-pan-y select-none overflow-hidden rounded-panel border border-line bg-carbon"
        >
          <AfterPane />
          <div className="absolute inset-0" style={{ clipPath: `inset(0 ${100 - pos}% 0 0)` }}>
            <BeforePane />
          </div>

          <div className="pointer-events-none absolute inset-y-0 w-0.5 -translate-x-1/2 bg-bone/80" style={{ left: `${pos}%` }} />
          <div
            role="slider"
            tabIndex={0}
            aria-label="Compare inbox today with ResolveAI"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={rounded}
            aria-valuetext={`${rounded}% inbox today, ${100 - rounded}% with ResolveAI`}
            onKeyDown={onKeyDown}
            className="absolute top-1/2 grid size-11 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-line-strong bg-bone text-ink shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ion focus-visible:ring-offset-2 focus-visible:ring-offset-ink"
            style={{ left: `${pos}%` }}
          >
            <ChevronsLeftRight className="size-5" aria-hidden />
          </div>
        </div>
      </div>
    </section>
  );
}

function PaneLabel({ children, side }: { children: string; side: "left" | "right" }) {
  return (
    <span
      className={`absolute top-4 z-10 rounded-[4px] border border-line bg-ink/90 px-2 py-1 text-xs font-medium text-bone ${
        side === "left" ? "left-4" : "right-4"
      }`}
    >
      {children}
    </span>
  );
}

function BeforePane() {
  return (
    <div className="absolute inset-0 bg-carbon-input" aria-hidden>
      <PaneLabel side="left">Inbox today</PaneLabel>
      {MESSAGES.map((m, i) => (
        <div
          key={m.from}
          className={`absolute w-[78%] max-w-[420px] rounded-[6px] border border-line bg-carbon-elevated p-3.5 shadow-xl ${PILE[i]}`}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-2 text-sm font-semibold text-bone">
              <span className="size-2 rounded-full bg-urgent" />
              {m.from}
            </span>
            <StatusChip tone="urgent">Waiting {m.waiting}</StatusChip>
          </div>
          <p className="mt-1.5 truncate text-sm text-ash">{m.text}</p>
        </div>
      ))}
    </div>
  );
}

function AfterPane() {
  return (
    <div className="absolute inset-0 flex flex-col gap-2 bg-carbon p-4 pt-14" aria-hidden>
      <PaneLabel side="right">With ResolveAI</PaneLabel>
      {MESSAGES.map((m) => (
        <div key={m.from} className="flex items-center gap-3 rounded-[6px] border border-line bg-carbon-elevated px-3 py-2.5">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-bone">{m.from}</p>
            <p className="truncate text-xs text-ash">{m.text}</p>
          </div>
          {m.needsApproval ? (
            <StatusChip tone="review">Needs approval</StatusChip>
          ) : (
            <StatusChip tone="ion">
              <Sparkles className="size-3" />
              Draft ready
            </StatusChip>
          )}
        </div>
      ))}
    </div>
  );
}
