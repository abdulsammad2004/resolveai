"use client";

import Link from "next/link";
import { motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { HeroCore } from "./hero-core";
import { useAuth } from "@/lib/auth/auth-provider";

export function HeroSection() {
  const { status } = useAuth();
  const isAuthenticated = status === "authenticated";

  // Staggered word animation
  const headlineWords = ["Support", "that", "resolves", "itself."];

  return (
    <section className="relative overflow-hidden pt-12 pb-20 sm:pt-20 sm:pb-28 lg:pt-24 lg:pb-32">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="grid items-center gap-12 lg:grid-cols-[1.1fr_0.9fr] lg:gap-8">
          {/* Headline and Copy */}
          <div className="flex flex-col gap-6 text-left">
            <h1 className="font-display text-6xl font-black uppercase leading-[0.88] tracking-tight text-bone sm:text-8xl md:text-9xl lg:text-[110px] xl:text-[130px]">
              {headlineWords.map((word, index) => (
                <span key={word} className="inline-block mr-3 sm:mr-5 overflow-hidden">
                  <motion.span
                    initial={{ y: "110%", opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    transition={{
                      duration: 0.7,
                      delay: index * 0.12,
                      ease: [0.16, 1, 0.3, 1],
                    }}
                    className={`inline-block ${word === "resolves" ? "text-ion" : "text-bone"}`}
                  >
                    {word}
                  </motion.span>
                </span>
              ))}
            </h1>

            <motion.p
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.6, ease: "easeOut" }}
              className="max-w-xl text-lg text-ash sm:text-xl font-normal leading-relaxed"
            >
              AI drafts grounded replies from your verified documentation. Your team approves
              every action with confidence and total workspace isolation.
            </motion.p>

            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.75, ease: "easeOut" }}
              className="flex flex-wrap items-center gap-4 pt-2"
            >
              {isAuthenticated ? (
                <Button asChild size="lg">
                  <Link href="/dashboard">Open dashboard</Link>
                </Button>
              ) : (
                <>
                  <Button asChild size="lg">
                    <Link href="/signup">Start free</Link>
                  </Button>
                  <Button asChild variant="secondary" size="lg">
                    <Link href="/login">Log in</Link>
                  </Button>
                </>
              )}
            </motion.div>
          </div>

          {/* 3D Kinetic Core Object */}
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.9, delay: 0.3, ease: [0.16, 1, 0.3, 1] }}
            className="flex items-center justify-center lg:justify-end"
          >
            <div className="relative size-[320px] sm:size-[420px] lg:size-[500px]">
              <HeroCore />
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  );
}

