"use client";

import Link from "next/link";
import { motion, useMotionValue, useReducedMotion, useSpring } from "motion/react";
import type { PointerEvent } from "react";

const MAX_SHIFT_X = 18;
const MAX_SHIFT_Y = 10;

export function SiteFooter() {
  const still = useReducedMotion() ?? false;
  const x = useSpring(useMotionValue(0), { stiffness: 120, damping: 20, mass: 0.6 });
  const y = useSpring(useMotionValue(0), { stiffness: 120, damping: 20, mass: 0.6 });

  function onPointerMove(e: PointerEvent<HTMLElement>) {
    if (still || e.pointerType !== "mouse") return;
    const rect = e.currentTarget.getBoundingClientRect();
    const nx = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    const ny = ((e.clientY - rect.top) / rect.height) * 2 - 1;
    x.set(nx * MAX_SHIFT_X);
    y.set(ny * MAX_SHIFT_Y);
  }

  function onPointerLeave() {
    x.set(0);
    y.set(0);
  }

  return (
    <footer
      onPointerMove={onPointerMove}
      onPointerLeave={onPointerLeave}
      className="relative overflow-hidden border-t border-line bg-ink pt-12"
    >
      <div className="mx-auto flex max-w-7xl flex-col items-start justify-between gap-4 px-4 text-sm text-ash sm:flex-row sm:items-center sm:px-6 lg:px-8">
        <p>ResolveAI &copy; 2026. Grounded answers, human approval.</p>
        <nav aria-label="Footer" className="flex gap-6">
          <Link href="/login" className="transition-colors hover:text-bone">
            Log in
          </Link>
          <Link href="/signup" className="transition-colors hover:text-bone">
            Start free
          </Link>
        </nav>
      </div>
      <motion.p
        aria-hidden
        style={still ? undefined : { x, y }}
        className="pointer-events-none mt-6 -mb-[0.18em] text-center font-display text-[21vw] leading-[0.8] font-black tracking-tight text-bone/[0.09] select-none"
      >
        ResolveAI
      </motion.p>
    </footer>
  );
}
