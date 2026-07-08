"use client";

import { useState } from "react";

import { CardDesigner } from "@/components/CardDesigner";
import { ChannelSelect } from "@/components/ChannelSelect";
import { LottieLibrary } from "@/components/LottieLibrary";
import { TransitionDesigner } from "@/components/TransitionDesigner";
import { cardsForRole, ROLES, type CardRole } from "@/remotion/cards/registry";

/**
 * Shell for the /remotion studio. Pins the channel selector at the top (scoping
 * every designer below it), then a tab row: one tab per card role that has at
 * least one comp today, plus a global "Lottie library" tab. The body is a
 * per-role CardDesigner (keyed by role so switching remounts cleanly — one
 * <Player> at a time) or the shared Lottie library. Lives in a client component
 * so page.tsx can stay a server component (it owns the metadata + header).
 */

// A tab is either a card role or the literal Lottie-library view.
type Section = CardRole | "lottie";

// Role tabs, data-driven: roles that have a card comp today (title,
// section_header, overlay) PLUS "transition", which has its own designer
// (TransitionDesigner) rather than card comps.
const ROLE_TABS = ROLES.filter(
  (r) => r.id === "transition" || cardsForRole(r.id).length > 0,
);

const TABS: ReadonlyArray<{ id: Section; label: string }> = [
  ...ROLE_TABS,
  { id: "lottie", label: "Lottie library" },
];

export function RemotionWorkspace() {
  const [channel, setChannel] = useState<string | undefined>(undefined);
  const [activeSection, setActiveSection] = useState<Section>(ROLE_TABS[0].id);

  return (
    <div className="space-y-6">
      {/* Channel — pinned at the top; scopes every designer below it. */}
      <ChannelSelect value={channel} onChange={setChannel} />

      <div className="flex flex-wrap gap-2">
        {TABS.map(({ id, label }) => {
          const active = id === activeSection;
          return (
            <button
              key={id}
              type="button"
              onClick={() => setActiveSection(id)}
              aria-pressed={active}
              className={`rounded-md border px-3.5 py-2 text-sm font-medium transition-colors ${
                active
                  ? "border-accent bg-accent/10 text-foreground"
                  : "border-border bg-surface text-muted hover:bg-surface-2 hover:text-foreground"
              }`}
            >
              {label}
            </button>
          );
        })}
      </div>

      {activeSection === "lottie" ? (
        <LottieLibrary />
      ) : activeSection === "transition" ? (
        <TransitionDesigner channel={channel} />
      ) : (
        <CardDesigner
          key={activeSection}
          role={activeSection}
          channel={channel}
        />
      )}
    </div>
  );
}
