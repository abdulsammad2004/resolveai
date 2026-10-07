"use client";

import { motion, useReducedMotion, type Transition } from "motion/react";

export type IllustrationKind = "inbox" | "approvals" | "conversations" | "knowledge" | "activity";

const loop = (duration: number, delay = 0): Transition => ({
  duration,
  delay,
  repeat: Infinity,
  ease: "easeInOut",
});

/** Small looping SVG for empty states. Renders a still frame under reduced motion. */
export function EmptyIllustration({ kind, className }: { kind: IllustrationKind; className?: string }) {
  const still = useReducedMotion() ?? false;
  return (
    <svg
      viewBox="0 0 96 96"
      fill="none"
      aria-hidden
      className={className ?? "size-20"}
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="48" cy="48" r="44" className="fill-ion/[0.07] stroke-none" />
      {kind === "inbox" && <Inbox still={still} />}
      {kind === "approvals" && <Approvals still={still} />}
      {kind === "conversations" && <Conversations still={still} />}
      {kind === "knowledge" && <Knowledge still={still} />}
      {kind === "activity" && <Activity still={still} />}
    </svg>
  );
}

function Inbox({ still }: { still: boolean }) {
  return (
    <g className="text-ion">
      <motion.g
        initial={false}
        animate={still ? { y: 6, opacity: 1 } : { y: [-14, 6, 6, -14], opacity: [0, 1, 1, 0] }}
        transition={still ? undefined : { ...loop(3.2), times: [0, 0.35, 0.75, 1] }}
      >
        <rect x="34" y="24" width="28" height="20" rx="3" className="fill-carbon" />
        <path d="M34 27l14 9 14-9" />
      </motion.g>
      <path d="M22 54h14l4 7h16l4-7h14v14a4 4 0 0 1-4 4H26a4 4 0 0 1-4-4z" className="fill-carbon" />
    </g>
  );
}

function Approvals({ still }: { still: boolean }) {
  return (
    <g className="text-ion">
      <path d="M48 18l24 9v17c0 15-10 26-24 32-14-6-24-17-24-32V27z" className="fill-carbon" />
      <motion.path
        d="M37 47l8 8 15-16"
        className="text-resolved"
        initial={false}
        animate={still ? { pathLength: 1 } : { pathLength: [0, 1, 1, 0] }}
        transition={still ? undefined : { ...loop(2.8), times: [0, 0.35, 0.8, 1] }}
      />
    </g>
  );
}

function Conversations({ still }: { still: boolean }) {
  return (
    <g className="text-ion">
      <motion.g
        initial={false}
        animate={still ? { y: 0 } : { y: [0, -2, 0] }}
        transition={still ? undefined : loop(2.4)}
      >
        <path d="M18 26h36a4 4 0 0 1 4 4v16a4 4 0 0 1-4 4H32l-8 7v-7h-6a4 4 0 0 1-4-4V30a4 4 0 0 1 4-4z" className="fill-carbon" />
      </motion.g>
      <path d="M44 46h32a4 4 0 0 1 4 4v14a4 4 0 0 1-4 4h-4v7l-8-7H44a4 4 0 0 1-4-4V50a4 4 0 0 1 4-4z" className="fill-carbon" />
      {[52, 60, 68].map((cx, i) => (
        <motion.circle
          key={cx}
          cx={cx}
          cy={57}
          r={2}
          className="fill-ion stroke-none"
          initial={false}
          animate={still ? { opacity: 1 } : { opacity: [0.25, 1, 0.25] }}
          transition={still ? undefined : loop(1.2, i * 0.2)}
        />
      ))}
    </g>
  );
}

function Knowledge({ still }: { still: boolean }) {
  return (
    <g className="text-ion">
      <rect x="30" y="30" width="36" height="44" rx="3" className="fill-carbon" opacity={0.6} />
      <rect x="26" y="26" width="36" height="44" rx="3" className="fill-carbon" />
      <motion.g
        initial={false}
        animate={still ? { y: 0, rotate: 0 } : { y: [0, -6, 0], rotate: [0, -4, 0] }}
        transition={still ? undefined : loop(3)}
        style={{ originX: "40px", originY: "62px" }}
      >
        <rect x="22" y="22" width="36" height="44" rx="3" className="fill-carbon" />
        <path d="M29 33h22M29 41h22M29 49h14" className="text-ash" />
      </motion.g>
    </g>
  );
}

function Activity({ still }: { still: boolean }) {
  return (
    <g className="text-ion">
      <rect x="16" y="24" width="64" height="48" rx="6" className="fill-carbon" />
      <motion.path
        d="M22 52h12l5-12 8 22 6-16 4 6h17"
        initial={false}
        animate={still ? { pathLength: 1, opacity: 1 } : { pathLength: [0, 1, 1], opacity: [1, 1, 0] }}
        transition={still ? undefined : { ...loop(3), times: [0, 0.6, 1] }}
      />
    </g>
  );
}
