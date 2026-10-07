import type { ReactNode } from "react";
import { BookOpenText } from "lucide-react";

/*
 * Each tile has a small decorative hover animation made of CSS transitions.
 * The global reduced-motion rule in globals.css flattens them.
 */

function Tile({ className = "", title, body, art }: { className?: string; title: string; body: string; art: ReactNode }) {
  return (
    <li
      className={`group relative flex flex-col justify-between gap-6 overflow-hidden rounded-panel border border-line bg-carbon p-6 transition-colors duration-200 hover:border-line-strong hover:bg-carbon-elevated ${className}`}
    >
      <div className="flex min-h-24 flex-1 items-center justify-center">{art}</div>
      <div>
        <h3 className="text-lg font-semibold text-bone">{title}</h3>
        <p className="mt-1 text-sm leading-relaxed text-ash">{body}</p>
      </div>
    </li>
  );
}

function LockArt() {
  return (
    <svg viewBox="0 0 64 72" className="h-24 w-auto" fill="none" aria-hidden>
      <path
        d="M18 34V24a14 14 0 0 1 28 0v4"
        stroke="#8B9099"
        strokeWidth="5"
        strokeLinecap="round"
        className="-translate-y-2 transition-[transform,stroke] duration-300 ease-[cubic-bezier(.3,1.6,.5,1)] group-hover:translate-y-0 group-hover:stroke-[#7B6CFF]"
      />
      <path
        d="M46 28v6"
        stroke="#8B9099"
        strokeWidth="5"
        strokeLinecap="round"
        className="opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-hover:stroke-[#7B6CFF]"
      />
      <rect x="10" y="34" width="44" height="32" rx="6" fill="#1F2229" stroke="#7B6CFF" strokeWidth="2" />
      <circle cx="32" cy="48" r="4" fill="#7B6CFF" />
      <path d="M32 52v6" stroke="#7B6CFF" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

function CitationArt() {
  return (
    <div className="flex w-full max-w-[240px] flex-col gap-2" aria-hidden>
      {["w-full", "w-11/12", "w-4/5", "w-2/3"].map((w) => (
        <span key={w} className={`h-2.5 rounded-full bg-white/10 ${w}`} />
      ))}
      <span className="mt-2 inline-flex w-fit translate-y-2 scale-90 items-center gap-1.5 rounded-[4px] border border-resolved/30 bg-resolved/10 px-2 py-1 text-xs text-resolved opacity-0 transition-all duration-300 group-hover:translate-y-0 group-hover:scale-100 group-hover:opacity-100">
        <BookOpenText className="size-3" />
        Returns policy
      </span>
    </div>
  );
}

function ToggleArt() {
  return (
    <div className="flex items-center gap-3" aria-hidden>
      <span className="text-sm text-ash">Approve refund</span>
      <span className="relative h-7 w-12 rounded-full border border-line bg-carbon-input transition-colors duration-300 group-hover:border-resolved/40 group-hover:bg-resolved/20">
        <span className="absolute top-1 left-1 size-5 rounded-full bg-ash transition-all duration-300 ease-[cubic-bezier(.3,1.4,.5,1)] group-hover:translate-x-5 group-hover:bg-resolved" />
      </span>
    </div>
  );
}

function ProgressArt() {
  return (
    <div className="flex w-full max-w-[220px] flex-col gap-2" aria-hidden>
      <div className="flex justify-between text-xs text-ash">
        <span>returns-policy.pdf</span>
        <span className="transition-colors delay-700 duration-300 group-hover:text-resolved">Ready</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-white/10">
        <div className="h-full w-[18%] rounded-full bg-ion transition-[width] duration-1000 ease-out group-hover:w-full" />
      </div>
    </div>
  );
}

function WidgetArt() {
  return (
    <div className="relative h-28 w-full max-w-[320px] rounded-[6px] border border-line bg-carbon-input" aria-hidden>
      <div className="flex gap-1.5 border-b border-line px-3 py-2">
        {[0, 1, 2].map((i) => (
          <span key={i} className="size-2 rounded-full bg-white/15" />
        ))}
      </div>
      <div className="flex flex-col gap-1.5 p-3">
        <span className="h-2 w-1/2 rounded-full bg-white/10" />
        <span className="h-2 w-1/3 rounded-full bg-white/10" />
      </div>
      <span className="absolute right-12 bottom-3 origin-bottom-right scale-0 rounded-[6px] rounded-br-none bg-ion px-2.5 py-1.5 text-xs font-medium text-ink opacity-0 transition-all duration-300 ease-[cubic-bezier(.3,1.5,.5,1)] group-hover:scale-100 group-hover:opacity-100">
        Hi! How can we help?
      </span>
      <span className="absolute right-3 bottom-3 size-7 rounded-full bg-ion" />
    </div>
  );
}

export function CapabilitiesBento() {
  return (
    <section aria-labelledby="capabilities-heading" className="border-t border-line bg-ink py-20 sm:py-28">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="mb-10 flex flex-col gap-3">
          <span className="text-sm font-semibold text-ion">What you get</span>
          <h2 id="capabilities-heading" className="font-display text-4xl font-bold tracking-tight text-bone sm:text-6xl">
            Built for support teams
          </h2>
        </div>
        <ul className="grid gap-4 md:auto-rows-[260px] md:grid-cols-3">
          <Tile
            className="md:col-span-2"
            title="Workspace isolation"
            body="Each business's documents, tickets and conversations are walled off at the database level."
            art={<LockArt />}
          />
          <Tile
            className="md:row-span-2"
            title="Citations on every answer"
            body="Drafts point to the passage they came from, so agents can check before sending."
            art={<CitationArt />}
          />
          <Tile
            title="Human approval"
            body="Refunds and account changes wait for a person to say yes."
            art={<ToggleArt />}
          />
          <Tile
            title="Background processing"
            body="Uploads are parsed and indexed in the background while you keep working."
            art={<ProgressArt />}
          />
          <Tile
            className="md:col-span-3"
            title="Works on your site"
            body="Add the chat widget to your store with a public key and an allowed-origins list."
            art={<WidgetArt />}
          />
        </ul>
      </div>
    </section>
  );
}
