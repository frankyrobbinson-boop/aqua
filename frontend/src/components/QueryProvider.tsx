"use client";

import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * Root TanStack Query provider. Holds a single QueryClient per browser
 * session — created via useState so React doesn't tear it down across
 * Strict-Mode re-renders or hot reloads.
 *
 * Defaults are tuned for this app:
 *   - staleTime 5s: artifacts (script, scenes, project detail) get a short
 *     stale window so per-scene regenerates and sibling edits surface quickly.
 *   - refetchOnWindowFocus on: returning from a backend log tab refreshes the
 *     visible artifacts; SSE invalidation still drives the primary path.
 *   - retry 1: fail fast for a local dev API.
 */
export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5_000,
            refetchOnWindowFocus: true,
            retry: 1,
          },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
