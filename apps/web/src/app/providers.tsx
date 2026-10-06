"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";

import { Toaster } from "@/components/ui/sonner";
import { AuthProvider } from "@/lib/auth/auth-provider";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
      <Toaster />
    </QueryClientProvider>
  );
}
