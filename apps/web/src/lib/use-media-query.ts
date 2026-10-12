"use client";

import { useSyncExternalStore } from "react";

/** Live matchMedia result. Returns `serverValue` during SSR and hydration. */
export function useMediaQuery(query: string, serverValue = false): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mql = window.matchMedia(query);
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    },
    () => window.matchMedia(query).matches,
    () => serverValue,
  );
}

/** True when heavy motion should be skipped: reduced motion or a phone-sized screen. */
export function useLiteMotion(): boolean {
  const reduced = useMediaQuery("(prefers-reduced-motion: reduce)", true);
  const small = useMediaQuery("(max-width: 767px)", true);
  return reduced || small;
}
