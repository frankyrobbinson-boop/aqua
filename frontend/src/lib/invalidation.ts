/**
 * Single source of truth for "a task that mutated project N just finished —
 * what do we invalidate?"
 *
 * Call this from any SSE `onDone` handler with status "completed". It
 * invalidates the project detail, the scenes grid, and the projects list (the
 * list shows has_script/has_audio/has_video flags which flip on completion).
 *
 * The optional `router` argument also triggers a server-component refresh.
 * That covers pages whose data still flows through RSC fetches (notably
 * `/projects/[slug]/page.tsx` → ProjectView), which TanStack Query alone
 * cannot reach. Once those pages move to `useProjectQuery`, the router arg
 * can be dropped at the call sites.
 */
import type { QueryClient } from "@tanstack/react-query";
import { channelKeys, projectKeys } from "./queries";

type RouterLike = { refresh: () => void };

export function invalidateForProject(
  qc: QueryClient,
  slug: string,
  router?: RouterLike,
) {
  qc.invalidateQueries({ queryKey: projectKeys.detail(slug) });
  qc.invalidateQueries({ queryKey: projectKeys.scenes(slug) });
  qc.invalidateQueries({ queryKey: projectKeys.visualConfig(slug) });
  qc.invalidateQueries({ queryKey: projectKeys.list() });
  router?.refresh();
}

/** Mirror of invalidateForProject for channel edits. The channels list
 *  page reads from a server component today (no useChannelsListQuery yet),
 *  so we also touch the router so RSC fetches re-run on next navigation;
 *  the channelKeys.list() invalidation is in place for when a list query
 *  hook is added. */
export function invalidateForChannel(
  qc: QueryClient,
  id: string,
  router?: RouterLike,
) {
  qc.invalidateQueries({ queryKey: channelKeys.preset(id) });
  qc.invalidateQueries({ queryKey: channelKeys.voice(id) });
  qc.invalidateQueries({ queryKey: channelKeys.list() });
  router?.refresh();
}
