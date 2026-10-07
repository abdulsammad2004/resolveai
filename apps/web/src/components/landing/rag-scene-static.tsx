import { BookOpenText } from "lucide-react";

import { RAG_ANSWER, RAG_QUESTION, RAG_STEPS } from "./rag-scene-timeline";

const ION = "#7B6CFF";
const RESOLVED = "#4FD1A5";

// Fixed "cloud" positions so the illustration is identical on every render.
const DOTS = [
  [18, 22], [40, 14], [62, 26], [82, 16], [26, 46], [50, 40], [72, 50], [90, 38], [14, 70], [38, 66], [60, 74], [84, 68],
] as const;
const NEAR = new Set([2, 3, 6, 7]);
const Q = [80, 30] as const;

function Doc() {
  return (
    <svg viewBox="0 0 100 80" className="h-24 w-full" aria-hidden>
      <rect x="28" y="6" width="44" height="68" rx="4" fill="#1F2229" stroke={ION} strokeOpacity="0.4" />
      {[18, 28, 38, 48, 58].map((y) => (
        <rect key={y} x="35" y={y} width={y === 58 ? 18 : 30} height="4" rx="2" fill={ION} fillOpacity="0.5" />
      ))}
    </svg>
  );
}

function Chunks() {
  return (
    <svg viewBox="0 0 100 80" className="h-24 w-full" aria-hidden>
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <rect
          key={i}
          x={i % 2 ? 54 : 18}
          y={8 + Math.floor(i / 2) * 24}
          width="28"
          height="16"
          rx="3"
          fill="#4B4290"
          transform={`rotate(${(i % 3) - 1} 50 40)`}
        />
      ))}
    </svg>
  );
}

function Cloud({ withQuestion, gathered }: { withQuestion?: boolean; gathered?: boolean }) {
  return (
    <svg viewBox="0 0 100 80" className="h-24 w-full" aria-hidden>
      {withQuestion &&
        DOTS.map(([x, y], i) =>
          NEAR.has(i) ? (
            <line key={`l${i}`} x1={Q[0]} y1={Q[1]} x2={x} y2={y} stroke="#EEECE7" strokeOpacity="0.35" />
          ) : null,
        )}
      {DOTS.map(([x, y], i) => {
        const near = NEAR.has(i);
        if (gathered && near) return null;
        return (
          <circle
            key={i}
            cx={x}
            cy={y}
            r={3}
            fill={withQuestion && near ? RESOLVED : ION}
            fillOpacity={gathered ? 0.25 : 0.9}
          />
        );
      })}
      {withQuestion && <circle cx={Q[0]} cy={Q[1]} r={4.5} fill="#EEECE7" />}
      {gathered && (
        <>
          <rect x="14" y="52" width="72" height="22" rx="4" fill="#1F2229" stroke={RESOLVED} />
          {[0, 1, 2, 3].map((k) => (
            <circle key={k} cx={32 + k * 12} cy={63} r={3} fill={RESOLVED} />
          ))}
        </>
      )}
    </svg>
  );
}

const ART = [<Doc key="doc" />, <Chunks key="chunks" />, <Cloud key="cloud" />, <Cloud key="q" withQuestion />, <Cloud key="a" gathered />];

/** Still version of the scene, for phones and reduced motion. */
export function RagSceneStatic() {
  return (
    <section aria-labelledby="rag-heading" className="border-t border-line bg-ink py-20 sm:py-28">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="mb-10 flex flex-col gap-3">
          <span className="text-sm font-semibold text-ion">Under the hood</span>
          <h2 id="rag-heading" className="font-display text-4xl font-bold tracking-tight text-bone sm:text-6xl">
            How an answer gets found
          </h2>
        </div>
        <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {RAG_STEPS.map((step, i) => (
            <li key={step.title} className="flex flex-col gap-3 rounded-panel border border-line bg-carbon p-5">
              {ART[i]}
              <p className="text-sm font-semibold text-bone">{step.title}</p>
              <p className="text-sm text-ash">{step.body}</p>
            </li>
          ))}
        </ol>
        <div className="mt-6 flex flex-col gap-3 rounded-panel border border-line bg-carbon p-5 sm:flex-row sm:items-start sm:gap-6">
          <p className="text-sm text-ash sm:w-1/3">
            <span className="block text-xs">Question</span>
            <span className="text-bone">{RAG_QUESTION}</span>
          </p>
          <div className="text-sm sm:flex-1">
            <span className="block text-xs text-ash">Answer</span>
            <span className="text-bone">{RAG_ANSWER}</span>
            <span className="mt-2 flex w-fit items-center gap-1.5 rounded-[4px] border border-resolved/30 bg-resolved/10 px-2 py-1 text-xs text-resolved">
              <BookOpenText className="size-3" aria-hidden />
              Source: Returns policy
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}
