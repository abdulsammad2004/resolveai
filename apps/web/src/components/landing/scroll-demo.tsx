"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { Sparkles, BookOpenText, Check, ShieldCheck } from "lucide-react";
import { StatusChip } from "@/components/status-chip";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";

if (typeof window !== "undefined") {
  gsap.registerPlugin(ScrollTrigger);
}

const fullMessage = "Hi, my order #4821 hasn't arrived yet. Can you check the status?";
const fullDraft =
  "Your order #4821 shipped on Monday via Express and is scheduled for delivery on Thursday by 5:00 PM. Tracking: #TRK-9821.";

function subscribe(callback: () => void) {
  const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
  mql.addEventListener("change", callback);
  return () => mql.removeEventListener("change", callback);
}

function getSnapshot() {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function getServerSnapshot() {
  return false;
}

export function ScrollDemo() {
  const isReduced = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const containerRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  const [typedMessage, setTypedMessage] = useState(isReduced ? fullMessage : "");
  const [sourcesLit, setSourcesLit] = useState(isReduced);
  const [typedDraft, setTypedDraft] = useState(isReduced ? fullDraft : "");
  const [isApproved, setIsApproved] = useState(isReduced);

  useEffect(() => {
    if (isReduced) return;

    const container = containerRef.current;
    if (!container) return;

    const ctx = gsap.context(() => {
      const tl = gsap.timeline({
        scrollTrigger: {
          trigger: container,
          start: "top top",
          end: "+=1800",
          pin: true,
          scrub: 0.6,
          onUpdate: (self) => {
            const progress = self.progress;

            // Phase 1: Customer message typing (0 -> 0.3)
            if (progress <= 0.3) {
              const charCount = Math.floor((progress / 0.3) * fullMessage.length);
              setTypedMessage(fullMessage.slice(0, charCount));
              setSourcesLit(false);
              setTypedDraft("");
              setIsApproved(false);
            }
            // Phase 2: Source lookup lighting (0.3 -> 0.45)
            else if (progress <= 0.45) {
              setTypedMessage(fullMessage);
              setSourcesLit(true);
              setTypedDraft("");
              setIsApproved(false);
            }
            // Phase 3: AI draft typing (0.45 -> 0.8)
            else if (progress <= 0.8) {
              setTypedMessage(fullMessage);
              setSourcesLit(true);
              const draftProgress = (progress - 0.45) / 0.35;
              const draftCharCount = Math.floor(draftProgress * fullDraft.length);
              setTypedDraft(fullDraft.slice(0, draftCharCount));
              setIsApproved(false);
            }
            // Phase 4: Button click & approval (0.8 -> 1.0)
            else {
              setTypedMessage(fullMessage);
              setSourcesLit(true);
              setTypedDraft(fullDraft);
              setIsApproved(true);
            }
          },
        },
      });

      return () => {
        tl.kill();
      };
    }, containerRef);

    return () => ctx.revert();
  }, [isReduced]);

  return (
    <section ref={containerRef} className="relative w-full bg-ink py-20 lg:py-28">
      <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <div className="mb-12 flex flex-col items-center text-center gap-3">
          <span className="text-xs font-semibold text-ion">
            Interactive architecture
          </span>
          <h2 className="font-display text-4xl font-bold uppercase tracking-tight text-bone sm:text-6xl md:text-7xl">
            Live resolution pipeline
          </h2>
          <p className="max-w-xl text-base text-ash sm:text-lg">
            Scroll to trace how customer messages ground into verified sources, generate precision drafts, and resolve with team approval.
          </p>
        </div>

        {/* Demo Interface Card */}
        <div
          ref={cardRef}
          className="relative mx-auto w-full rounded-panel border border-line bg-carbon p-6 shadow-2xl sm:p-8 md:p-10"
        >
          {/* Card Topbar */}
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line pb-6">
            <div className="flex items-center gap-3">
              <Avatar className="size-10 border border-line">
                <AvatarFallback className="bg-carbon-elevated text-bone font-medium">MR</AvatarFallback>
              </Avatar>
              <div>
                <p className="font-medium text-bone">Maya Robinson</p>
                <p className="text-xs text-ash">Customer #4821 · Live chat</p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <StatusChip tone={isApproved ? "resolved" : "review"} dot={true}>
                {isApproved ? "Resolved" : "Awaiting review"}
              </StatusChip>
            </div>
          </div>

          {/* Customer Message Bubble */}
          <div className="mt-6 flex flex-col gap-2">
            <span className="text-xs font-medium text-ash">Customer inquiry</span>
            <div className="min-h-[52px] rounded-[6px] border border-line bg-carbon-input p-4 text-sm sm:text-base text-bone font-normal">
              {(isReduced ? fullMessage : typedMessage) || <span className="text-ash/40 italic">Waiting for customer input…</span>}
              {!isReduced && typedMessage.length < fullMessage.length && typedMessage.length > 0 && (
                <span className="inline-block size-1.5 ml-1 bg-ion animate-pulse" />
              )}
            </div>
          </div>

          {/* Grounded Source Retrieval Chips */}
          <div className="mt-6 flex flex-col gap-2.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-ash">Grounded knowledge retrieval</span>
              {(isReduced || sourcesLit) && (
                <span className="flex items-center gap-1 text-xs text-resolved font-medium">
                  <Check className="size-3.5" /> 100% ground truth verified
                </span>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <div
                className={`flex items-center gap-2 rounded-[6px] border px-3 py-2 text-xs sm:text-sm font-medium transition-all duration-300 ${
                  isReduced || sourcesLit
                    ? "border-ion/50 bg-ion/10 text-bone shadow-[0_0_16px_rgba(123,108,255,0.2)]"
                    : "border-line bg-carbon-input text-ash/60"
                }`}
              >
                <BookOpenText className="size-4 text-ion" />
                <span>Shipping & Delivery Policy (v2.4)</span>
              </div>

              <div
                className={`flex items-center gap-2 rounded-[6px] border px-3 py-2 text-xs sm:text-sm font-medium transition-all duration-300 ${
                  isReduced || sourcesLit
                    ? "border-white/20 bg-carbon-elevated text-bone"
                    : "border-line bg-carbon-input text-ash/40"
                }`}
              >
                <ShieldCheck className="size-4 text-resolved" />
                <span>Order #4821 Fulfillment Event</span>
              </div>
            </div>
          </div>

          {/* AI Draft Resolution Box */}
          <div className="mt-6 rounded-panel border border-line bg-carbon-elevated p-5 sm:p-6">
            <div className="flex items-center justify-between gap-2 border-b border-line pb-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-ion">
                <Sparkles className="size-4" />
                <span>AI drafted resolution</span>
              </div>
              <span className="text-xs text-ash font-mono">Workspace: Acme Support</span>
            </div>

            <p className="mt-4 min-h-[64px] text-sm sm:text-base text-bone font-normal leading-relaxed">
              {(isReduced ? fullDraft : typedDraft) || <span className="text-ash/40 italic">Retrieving grounded context…</span>}
              {!isReduced && typedDraft.length < fullDraft.length && typedDraft.length > 0 && (
                <span className="inline-block size-1.5 ml-1 bg-ion animate-pulse" />
              )}
            </p>

            <div className="mt-6 flex flex-wrap items-center justify-between gap-4 border-t border-line pt-4">
              <span className="text-xs text-ash">Requires human approval prior to dispatch.</span>
              <div className="flex items-center gap-3">
                <Button
                  size="sm"
                  variant={isReduced || isApproved ? "secondary" : "primary"}
                  className={`transition-all duration-300 ${
                    isReduced || isApproved ? "bg-resolved/15 border-resolved/40 text-resolved font-semibold" : ""
                  }`}
                >
                  {isReduced || isApproved ? (
                    <>
                      <Check className="size-4" /> Approved & dispatched
                    </>
                  ) : (
                    "Approve and send"
                  )}
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

