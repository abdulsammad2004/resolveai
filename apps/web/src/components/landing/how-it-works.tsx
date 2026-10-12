"use client";

import { motion } from "motion/react";
import { UploadCloud, FileCheck2, UserCheck } from "lucide-react";

export function HowItWorks() {
  const steps = [
    {
      number: "01",
      icon: UploadCloud,
      title: "Upload your docs",
      description:
        "Sync internal help center articles, return policies, and API specifications directly into pgvector-indexed collections.",
    },
    {
      number: "02",
      icon: FileCheck2,
      title: "The AI drafts with sources",
      description:
        "When tickets arrive, the assistant retrieves ground-truth passages and synthesizes typed, allowlisted draft responses with citations.",
    },
    {
      number: "03",
      icon: UserCheck,
      title: "Your team approves",
      description:
        "Agents inspect citations, adjust phrasing if necessary, and dispatch verified resolutions with full workspace audit logging.",
    },
  ];

  return (
    <section className="relative w-full border-t border-line bg-ink py-24 sm:py-32">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="mb-16 flex flex-col items-start gap-4">
          <span className="text-sm font-semibold text-ion">
            Operational workflow
          </span>
          <h2 className="font-display text-5xl font-bold tracking-tight text-bone sm:text-7xl">
            How it works
          </h2>
          <p className="max-w-xl text-base text-ash sm:text-lg">
            A three-step loop combining autonomous neural retrieval with strict human oversight.
          </p>
        </div>

        <div className="grid gap-6 md:grid-cols-3">
          {steps.map((step, idx) => {
            const Icon = step.icon;
            return (
              <motion.div
                key={step.number}
                initial={{ opacity: 0, y: 30 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-80px" }}
                transition={{ duration: 0.6, delay: idx * 0.15, ease: [0.16, 1, 0.3, 1] }}
                className="group relative flex flex-col justify-between rounded-panel border border-line bg-carbon p-8 transition-colors hover:border-line-strong hover:bg-carbon-elevated"
              >
                <div>
                  <div className="flex items-center justify-between">
                    <span className="font-display text-4xl font-black text-ion/40 group-hover:text-ion transition-colors">
                      {step.number}
                    </span>
                    <span className="flex size-11 items-center justify-center rounded-[6px] border border-line bg-carbon-input text-ion">
                      <Icon className="size-5" />
                    </span>
                  </div>

                  <h3 className="font-display mt-8 text-2xl font-bold tracking-tight text-bone sm:text-3xl">
                    {step.title}
                  </h3>

                  <p className="mt-3 text-sm text-ash leading-relaxed">
                    {step.description}
                  </p>
                </div>

                <div className="mt-8 pt-4 border-t border-line/50 text-xs text-ash/60">
                  Step {idx + 1} of 3
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

