import { Logo } from "@/components/logo";

export function FullPageLoader({ label = "Restoring your session" }: { label?: string }) {
  return (
    <div className="grid min-h-dvh place-items-center bg-ink p-4" role="status" aria-live="polite">
      <div className="flex flex-col items-center gap-5 rounded-panel border border-line bg-carbon px-10 py-9 shadow-2xl">
        <Logo />
        <div className="h-1 w-40 overflow-hidden rounded-full bg-white/10" aria-hidden>
          <div className="loader-bar h-full w-1/3 rounded-full bg-ion" />
        </div>
        <p className="text-sm text-ash">{label}</p>
      </div>
    </div>
  );
}
