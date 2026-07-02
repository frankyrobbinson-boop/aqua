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
  getChannelPreset,
  getChannelVoice,
  getProject,
  getScenes,
  getVisualConfig,
  getVisualProviders,
  listProjects,
} from "./api";

export const projectKeys = {
  all: ["projects"] as const,
  list: () => [...projectKeys.all, "list"] as const,
  detail: (slug: string) => [...projectKeys.all, "detail", slug] as const,
  scenes: (slug: string) => [...projectKeys.all, "scenes", slug] as const,
  visualConfig: (slug: string) =>
    [...projectKeys.all, "visualConfig", slug] as const,
  visualProviders: () => [...projectKeys.all, "visualProviders"] as const,
};

export const channelKeys = {
  all: ["channels"] as const,
  list: () => [...channelKeys.all, "list"] as const,
  preset: (id: string) => [...channelKeys.all, "preset", id] as const,
  voice: (id: string) => [...channelKeys.all, "voice", id] as const,
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

export function useVisualProvidersQuery() {
  return useQuery({
    queryKey: projectKeys.visualProviders(),
    queryFn: () => getVisualProviders(),
  });
}

export function useChannelPresetQuery(id: string) {
  return useQuery({
    queryKey: channelKeys.preset(id),
    queryFn: () => getChannelPreset(id),
    enabled: Boolean(id),
  });
}

export function useChannelVoiceQuery(id: string) {
  return useQuery({
    queryKey: channelKeys.voice(id),
    queryFn: () => getChannelVoice(id),
    enabled: Boolean(id),
  });
}
