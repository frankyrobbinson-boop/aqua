"use client";

import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * Root TanStack Query provider. Holds a single QueryClient per browser
 * session — created via useState so React doesn't tear it down across
 * Strict-Mode re-renders or hot reloads.
 *
 * Defaults are tuned for this app:
 *   - staleTime 30s: artifacts (script, scenes, project detail) don't change
 *     unless we explicitly invalidate after a task completes.
 *   - refetchOnWindowFocus off: tab-switching shouldn't re-fetch; we control
 *     refresh via SSE-driven invalidation.
 *   - retry 1: fail fast for a local dev API.
 */
export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
