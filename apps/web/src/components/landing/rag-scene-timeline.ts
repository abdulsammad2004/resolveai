/** Shared timeline for the "how an answer gets found" scene. Progress runs 0 to 1. */

export type Phase = readonly [start: number, end: number];

export const RAG_PHASES = {
  docFade: [0.1, 0.22],
  split: [0.12, 0.3],
  scatter: [0.32, 0.52],
  glow: [0.4, 0.5],
  question: [0.56, 0.66],
  gather: [0.72, 0.9],
  answer: [0.86, 0.96],
} as const satisfies Record<string, Phase>;

export const RAG_STEPS = [
  { at: 0, title: "A help article arrives", body: "You upload a policy or FAQ. Nothing is answered from memory." },
  { at: 0.14, title: "It's split into chunks", body: "Each article is cut into short passages that can be cited on their own." },
  { at: 0.34, title: "Chunks become points", body: "Each passage is placed in space by meaning, so similar ideas sit close together." },
  { at: 0.56, title: "A customer asks", body: "The question is placed in the same space, inside your workspace only." },
  { at: 0.74, title: "The closest points answer", body: "The nearest passages are pulled into a draft that cites where each fact came from." },
] as const;

export const RAG_QUESTION = "Can I return a jacket I wore once?";
export const RAG_ANSWER =
  "Unworn items can be returned within 30 days. Worn items can't be refunded, but we can offer store credit.";

const smooth = (t: number) => t * t * (3 - 2 * t);

/** 0 before the phase, 1 after it, eased in between. */
export function phaseAmount(p: number, [start, end]: Phase): number {
  const t = Math.min(1, Math.max(0, (p - start) / (end - start)));
  return smooth(t);
}

export function stepAt(p: number): number {
  let index = 0;
  RAG_STEPS.forEach((s, i) => {
    if (p >= s.at) index = i;
  });
  return index;
}
