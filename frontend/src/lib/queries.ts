/**
 * Centralized TanStack Query hooks + key factory for project artifact reads.
 *
 * The plain fetch functions in `lib/api.ts` stay the source of truth for the
 * wire calls; these hooks wrap them so any component that wants to react to
 * SSE-driven task completions can `useQuery` here and `invalidateQueries`
 * via `lib/invalidation.ts`.
 */
import { useQuery } from "@tanstack/react-query";
import {
  getProject,
  getScenes,
  getVisualConfig,
  listProjects,
} from "./api";

export const projectKeys = {
  all: ["projects"] as const,
  list: () => [...projectKeys.all, "list"] as const,
  detail: (slug: string) => [...projectKeys.all, "detail", slug] as const,
  scenes: (slug: string) => [...projectKeys.all, "scenes", slug] as const,
  visualConfig: (slug: string) =>
    [...projectKeys.all, "visualConfig", slug] as const,
};

export function useProjectsListQuery() {
  return useQuery({
    queryKey: projectKeys.list(),
    queryFn: () => listProjects(),
  });
}

export function useProjectQuery(slug: string) {
  return useQuery({
    queryKey: projectKeys.detail(slug),
    queryFn: () => getProject(slug),
    enabled: Boolean(slug),
  });
}

export function useScenesQuery(slug: string) {
  return useQuery({
    queryKey: projectKeys.scenes(slug),
    queryFn: () => getScenes(slug),
    enabled: Boolean(slug),
  });
}

export function useVisualConfigQuery(slug: string) {
  return useQuery({
    queryKey: projectKeys.visualConfig(slug),
    queryFn: () => getVisualConfig(slug),
    enabled: Boolean(slug),
  });
}
