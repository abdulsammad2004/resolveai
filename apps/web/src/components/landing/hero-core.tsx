"use client";

import dynamic from "next/dynamic";
import { useSyncExternalStore } from "react";
import { CoreFallback } from "./core-fallback";

const DynamicCoreScene = dynamic(() => import("./core-scene"), {
  ssr: false,
  loading: () => <CoreFallback />,
});

function subscribe(callback: () => void) {
  window.addEventListener("resize", callback);
  const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
  mql.addEventListener("change", callback);
  return () => {
    window.removeEventListener("resize", callback);
    mql.removeEventListener("change", callback);
  };
}

function getSnapshot() {
  if (typeof window === "undefined") return false;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const isMobile = window.innerWidth < 768;
  return !reducedMotion && !isMobile;
}

function getServerSnapshot() {
  return false;
}

export function HeroCore() {
  const shouldRender3D = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  return (
    <div className="relative flex size-full items-center justify-center">
      {shouldRender3D ? <DynamicCoreScene /> : <CoreFallback />}
    </div>
  );
}

