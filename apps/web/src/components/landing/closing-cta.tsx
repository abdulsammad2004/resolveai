"use client";

import Link from "next/link";
import { motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth/auth-provider";

export function ClosingCta() {
  const { status } = useAuth();
  const isAuthenticated = status === "authenticated";

  return (
    <section className="relative overflow-hidden border-t border-line bg-carbon py-24 sm:py-32 lg:py-40">
      {/* Background ambient ion glow */}
      <div
        className="pointer-events-none absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 size-[600px] rounded-full bg-ion/10 blur-[120px]"
        aria-hidden
      />

      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 text-center">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
          className="flex flex-col items-center gap-8"
        >
          <h2 className="font-display text-6xl font-black uppercase tracking-tight text-bone sm:text-8xl md:text-9xl lg:text-[140px] leading-[0.85]">
            Less inbox.<br />
            <span className="text-ion">More resolved.</span>
          </h2>

          <p className="max-w-xl text-lg text-ash sm:text-xl">
            Start automating customer support with verified knowledge retrieval and precision human review today.
          </p>

          <div className="pt-4">
            {isAuthenticated ? (
              <Button asChild size="lg">
                <Link href="/dashboard">Open dashboard</Link>
              </Button>
            ) : (
              <Button asChild size="lg">
                <Link href="/signup">Start free</Link>
              </Button>
            )}
          </div>
        </motion.div>
      </div>
    </section>
  );
}

