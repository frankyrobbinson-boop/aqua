/**
 * Card registry — the UI source of truth for which title cards exist. The tab
 * builds its picker from `CARDS`; Root.tsx registers a <Composition> per entry.
 *
 * The backend's ALLOWED_COMPS frozenset (backend/api/routes/remotion.py) MIRRORS
 * `CARD_IDS` — keep the two in sync when adding or removing a card.
 *
 * Likewise `ROLES` below is mirrored by ALLOWED_ROLES in
 * backend/api/routes/remotion.py and _ROLE_FILES in
 * backend/services/graphics_registry.py — keep the role set in sync across the
 * three, same convention as CARD_IDS ↔ ALLOWED_COMPS.
 */
import type { ComponentType } from "react";

import { GardenBand } from "./GardenBand";
import { GardenBloom } from "./GardenBloom";
import { GardenCentered } from "./GardenCentered";
import { GardenFramed } from "./GardenFramed";
import { GardenPremium } from "./GardenPremium";
import type { CardProps } from "./types";

/** The slot a card fills in a video. Mirrored by ALLOWED_ROLES (backend). */
export type CardRole = "title" | "section_header" | "overlay" | "transition";

export type CardDefinition = {
  id: string;
  label: string;
  description: string;
  role: CardRole;
  component: ComponentType<CardProps>;
};

export const CARDS: readonly CardDefinition[] = [
  {
    id: "GardenCentered",
    label: "Centered",
    description: "Centered title with sparse floating botanicals.",
    role: "title",
    component: GardenCentered,
  },
  {
    id: "GardenFramed",
    label: "Framed",
    description: "Botanical corner-vine frame around the title.",
    role: "section_header",
    component: GardenFramed,
  },
  {
    id: "GardenBand",
    label: "Band",
    description: "Title above a lower botanical band.",
    role: "section_header",
    component: GardenBand,
  },
  {
    id: "GardenPremium",
    label: "Premium",
    description:
      "Kicker, masked word-by-word title reveal, soft panel, grain + layered botanicals.",
    role: "overlay",
    component: GardenPremium,
  },
  {
    id: "GardenBloom",
    label: "Bloom",
    description:
      "No panel — a lush, layered botanical frame that blooms in around the title.",
    role: "title",
    component: GardenBloom,
  },
];

export const CARD_IDS: readonly string[] = CARDS.map((c) => c.id);

// Role catalog for the designer's role picker, in display order. Mirrored by
// ALLOWED_ROLES in backend/api/routes/remotion.py.
export const ROLES: ReadonlyArray<{ id: CardRole; label: string }> = [
  { id: "title", label: "Title screens" },
  { id: "section_header", label: "Section headers" },
  { id: "overlay", label: "Overlays" },
  { id: "transition", label: "Transitions" },
];

/** Cards available for a given role (the designer filters its picker by role). */
export function cardsForRole(role: CardRole): readonly CardDefinition[] {
  return CARDS.filter((c) => c.role === role);
}
