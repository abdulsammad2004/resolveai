"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useInView } from "motion/react";
import { BookOpenText, MessageCircleQuestion } from "lucide-react";

import { useLiteMotion } from "@/lib/use-media-query";
import { RAG_ANSWER, RAG_PHASES, RAG_QUESTION, RAG_STEPS, phaseAmount, stepAt } from "./rag-scene-timeline";
import { RagSceneStatic } from "./rag-scene-static";

if (typeof window !== "undefined") {
  gsap.registerPlugin(ScrollTrigger);
}

const RagSceneCanvas = dynamic(() => import("./rag-scene-canvas"), { ssr: false, loading: () => null });

/** "How it works" in 3D, scrubbed by scroll. Phones and reduced motion get the static version. */
export function RagScene() {
  const lite = useLiteMotion();
  return lite ? <RagSceneStatic /> : <RagSceneScrubbed />;
}

function RagSceneScrubbed() {
  const sectionRef = useRef<HTMLElement>(null);
  const progressRef = useRef(0);
  const questionRef = useRef<HTMLDivElement>(null);
  const answerRef = useRef<HTMLDivElement>(null);
  const [step, setStep] = useState(0);
  const nearView = useInView(sectionRef, { margin: "600px 0px", once: true });
  const inView = useInView(sectionRef);

  useEffect(() => {
    const section = sectionRef.current;
    if (!section) return;

    const apply = (p: number) => {
      progressRef.current = p;
      setStep(stepAt(p));
      if (questionRef.current) questionRef.current.style.opacity = String(phaseAmount(p, RAG_PHASES.question));
      if (answerRef.current) answerRef.current.style.opacity = String(phaseAmount(p, RAG_PHASES.answer));
    };

    const trigger = ScrollTrigger.create({
      trigger: section,
      start: "top top",
      end: "bottom bottom",
      onUpdate: (self) => apply(self.progress),
      onRefresh: (self) => apply(self.progress),
    });
    return () => trigger.kill();
  }, []);

  return (
    <section ref={sectionRef} aria-labelledby="rag-heading" className="relative h-[320vh] border-t border-line bg-ink">
      <div className="sticky top-0 grid h-dvh grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] items-center gap-8 overflow-hidden px-8 lg:px-16">
        <div className="flex flex-col gap-6">
          <span className="text-sm font-semibold text-ion">Under the hood</span>
          <h2 id="rag-heading" className="font-display text-5xl font-bold tracking-tight text-bone lg:text-6xl">
            How an answer gets found
          </h2>
          <ol className="flex flex-col gap-1">
            {RAG_STEPS.map((s, i) => (
              <li
                key={s.title}
                aria-current={i === step ? "step" : undefined}
                className={`rounded-[6px] border-l-2 py-2 pl-4 transition-colors duration-300 ${
                  i === step ? "border-ion text-bone" : "border-line text-ash/60"
                }`}
              >
                <p className="text-base font-semibold">{s.title}</p>
                <p
                  className={`text-sm text-ash transition-[opacity,max-height] duration-300 ${
                    i === step ? "max-h-20 opacity-100" : "max-h-0 overflow-hidden opacity-0"
                  }`}
                >
                  {s.body}
                </p>
              </li>
            ))}
          </ol>
        </div>

        <div className="relative h-[78dvh] min-h-[420px]" aria-hidden>
          {nearView && <RagSceneCanvas progressRef={progressRef} running={inView} />}

          <div
            ref={questionRef}
            style={{ opacity: 0 }}
            className="absolute top-6 right-4 flex max-w-[260px] items-start gap-2 rounded-[6px] border border-line bg-carbon-elevated px-3 py-2.5 text-sm text-bone"
          >
            <MessageCircleQuestion className="mt-0.5 size-4 shrink-0 text-ion" />
            {RAG_QUESTION}
          </div>

          <div
            ref={answerRef}
            style={{ opacity: 0 }}
            className="absolute bottom-6 left-1/2 w-[min(420px,90%)] -translate-x-1/2 rounded-[6px] border border-resolved/30 bg-carbon-elevated p-4"
          >
            <p className="text-sm leading-relaxed text-bone">{RAG_ANSWER}</p>
            <span className="mt-3 inline-flex items-center gap-1.5 rounded-[4px] border border-resolved/30 bg-resolved/10 px-2 py-1 text-xs text-resolved">
              <BookOpenText className="size-3" />
              Source: Returns policy
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}
