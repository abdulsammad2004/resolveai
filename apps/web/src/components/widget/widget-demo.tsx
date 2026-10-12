"use client";

import Link from "next/link";
import { useEffect } from "react";

import { FullPageLoader } from "@/components/full-page-loader";
import { useWorkspaceSettings } from "@/lib/api/queries";
import { useAuth } from "@/lib/auth/auth-provider";

declare global {
  interface Window {
    __resolveaiWidget?: { open: () => void; close: () => void; toggle: () => void };
  }
}

/**
 * A stand-in customer website: plain light styling, nothing from the app's design system,
 * and the widget loaded exactly as a customer would paste it.
 */
export function WidgetDemo() {
  const { status, workspace } = useAuth();

  if (status === "loading") return <FullPageLoader />;
  if (status !== "authenticated") {
    return (
      <main className="grid min-h-dvh place-items-center bg-ink p-6 text-center">
        <div className="flex max-w-sm flex-col gap-3">
          <h1 className="font-display text-3xl font-bold">Log in to try the widget</h1>
          <p className="text-sm text-ash">The demo page loads your workspace&apos;s widget key.</p>
          <Link href="/login?next=/widget-demo" className="text-ion underline-offset-4 hover:underline">
            Log in
          </Link>
        </div>
      </main>
    );
  }
  return <DemoStore key={workspace?.id} />;
}

function DemoStore() {
  const settings = useWorkspaceSettings();
  const widgetKey = settings.data?.widget_public_key;

  useEffect(() => {
    if (!widgetKey) return;
    const script = document.createElement("script");
    script.src = `${window.location.origin}/widget.js`;
    script.async = true;
    script.dataset.key = widgetKey;
    document.body.appendChild(script);
    return () => {
      script.remove();
      document.querySelector("[data-resolveai-widget]")?.remove();
      delete window.__resolveaiWidget;
    };
  }, [widgetKey]);

  return (
    <div className="min-h-dvh bg-[#f6f4ef] text-[#1d1d1b]" style={{ fontFamily: "Georgia, serif" }}>
      <header className="border-b border-black/10 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-4">
          <span className="text-xl font-bold tracking-tight">Demo Store</span>
          <nav className="flex gap-4 text-sm text-black/60">
            <span>Shop</span>
            <span>Help</span>
            <span>Cart (0)</span>
          </nav>
        </div>
      </header>

      <main className="mx-auto flex max-w-5xl flex-col gap-10 px-4 py-12">
        <section className="flex flex-col gap-4">
          <p className="text-sm text-black/50">Test page</p>
          <h1 className="text-4xl leading-tight font-bold sm:text-5xl">
            A pretend website with your chat widget on it.
          </h1>
          <p className="max-w-2xl text-lg text-black/70">
            This page loads <code className="rounded bg-black/5 px-1">widget.js</code> with your
            workspace key, just like a customer&apos;s site would. Open the chat with the button in
            the bottom-right corner and ask about something in your knowledge base.
          </p>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => window.__resolveaiWidget?.open()}
              disabled={!widgetKey}
              className="rounded-full bg-[#1d1d1b] px-5 py-2.5 text-sm text-white disabled:opacity-40"
            >
              Open the chat
            </button>
            <Link href="/settings" className="rounded-full border border-black/20 px-5 py-2.5 text-sm">
              Back to settings
            </Link>
          </div>
          {settings.isError && (
            <p className="text-sm text-red-700">Couldn&apos;t load your widget key. Refresh to try again.</p>
          )}
        </section>

        <section className="grid gap-4 sm:grid-cols-3">
          {["Canvas tote", "Wool beanie", "Field notebook"].map((name, i) => (
            <div key={name} className="flex flex-col gap-3 rounded-lg border border-black/10 bg-white p-4">
              <div className="aspect-[4/3] rounded bg-black/[0.06]" />
              <div className="flex justify-between">
                <span>{name}</span>
                <span className="text-black/60">${(i + 2) * 12}.00</span>
              </div>
            </div>
          ))}
        </section>

        <p className="text-sm text-black/50">
          This page is served from the app&apos;s own origin, so the session check needs
          <code className="mx-1 rounded bg-black/5 px-1">WIDGET_DEV_ALLOW_LOCALHOST=true</code>
          in the API&apos;s .env, or this origin in the widget&apos;s allowed origins.
        </p>
      </main>
    </div>
  );
}
