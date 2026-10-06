import { Logo } from "@/components/logo";

// Shown while the session is restored from the refresh cookie, so the login page never flashes.
export function FullPageLoader({ label = "Restoring your session" }: { label?: string }) {
  return (
    <div className="grid min-h-dvh place-items-center p-4" role="status" aria-live="polite">
      <div className="glass flex flex-col items-center gap-5 rounded-panel px-10 py-9">
        <Logo />
        <div className="h-1 w-40 overflow-hidden rounded-full bg-white/10" aria-hidden>
          <div className="loader-bar h-full w-1/3 rounded-full bg-seafoam/80" />
        </div>
        <p className="text-sm text-mist-dim">{label}</p>
      </div>
    </div>
  );
}
