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

import { FloralCard } from "./floral/FloralCard";
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
  /** Primary slot this card fills — and, unless `roles` is set, its sole
   *  membership in the role picker (see cardsForRole). */
  role: CardRole;
  /** Visual STYLE family this card belongs to, for cards that ship as a themed
   *  set (e.g. "floral"). Undefined for the original garden cards.
   *  Informational for now. */
  style?: string;
  /** Every slot this card may fill, when it serves MORE than its primary `role`
   *  (e.g. a section header that doubles as an overlay). Defaults to `[role]`;
   *  cardsForRole() matches against this set. */
  roles?: CardRole[];
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
  {
    id: "FloralSlide01",
    label: "Floral 1 · Title",
    description:
      "Floral paper-texture title — a centered hero framed by a botanical border that settles inward.",
    role: "title",
    style: "floral",
    component: FloralCard,
  },
  {
    id: "FloralSlide02",
    label: "Floral 2 · Section",
    description:
      "Floral paper-texture section header — a left-anchored heading with botanicals massed down the right.",
    role: "section_header",
    roles: ["section_header", "overlay"],
    style: "floral",
    component: FloralCard,
  },
  {
    id: "FloralSlide03",
    label: "Floral 3 · Section",
    description:
      "Floral paper-texture section header — a right-anchored heading with botanicals massed down the left.",
    role: "section_header",
    roles: ["section_header", "overlay"],
    style: "floral",
    component: FloralCard,
  },
  {
    id: "FloralSlide04",
    label: "Floral 4 · Section",
    description:
      "Floral paper-texture section header — a left-anchored heading with botanicals massed down the right.",
    role: "section_header",
    roles: ["section_header", "overlay"],
    style: "floral",
    component: FloralCard,
  },
  {
    id: "FloralSlide05",
    label: "Floral 5 · Section",
    description:
      "Floral paper-texture section header — a right-anchored heading with botanicals massed down the left.",
    role: "section_header",
    roles: ["section_header", "overlay"],
    style: "floral",
    component: FloralCard,
  },
  {
    id: "FloralSlide06",
    label: "Floral 6 · Section",
    description:
      "Floral paper-texture section header — a left-anchored heading with botanicals massed down the right.",
    role: "section_header",
    roles: ["section_header", "overlay"],
    style: "floral",
    component: FloralCard,
  },
  {
    id: "FloralSlide07",
    label: "Floral 7 · Section",
    description:
      "Floral paper-texture section header — a right-anchored heading with botanicals massed down the left.",
    role: "section_header",
    roles: ["section_header", "overlay"],
    style: "floral",
    component: FloralCard,
  },
  {
    id: "FloralSlide08",
    label: "Floral 8 · Section",
    description:
      "Floral paper-texture section header — a left-anchored heading with botanicals massed down the right.",
    role: "section_header",
    roles: ["section_header", "overlay"],
    style: "floral",
    component: FloralCard,
  },
  {
    id: "FloralSlide09",
    label: "Floral 9 · Section",
    description:
      "Floral paper-texture section header — a right-anchored heading with botanicals massed down the left.",
    role: "section_header",
    roles: ["section_header", "overlay"],
    style: "floral",
    component: FloralCard,
  },
  {
    id: "FloralSlide10",
    label: "Floral 10 · Section",
    description:
      "Floral paper-texture section header — a left-anchored heading with botanicals massed down the right.",
    role: "section_header",
    roles: ["section_header", "overlay"],
    style: "floral",
    component: FloralCard,
  },
  {
    id: "FloralSlide11",
    label: "Floral 11 · Section",
    description:
      "Floral paper-texture section header — a right-anchored heading with botanicals massed down the left.",
    role: "section_header",
    roles: ["section_header", "overlay"],
    style: "floral",
    component: FloralCard,
  },
  {
    id: "FloralSlide12",
    label: "Floral 12 · Section",
    description:
      "Floral paper-texture section header — a left-anchored heading with botanicals massed down the right.",
    role: "section_header",
    roles: ["section_header", "overlay"],
    style: "floral",
    component: FloralCard,
  },
  {
    id: "FloralSlide13",
    label: "Floral 13 · Section",
    description:
      "Floral paper-texture section header — a right-anchored heading with botanicals massed down the left.",
    role: "section_header",
    roles: ["section_header", "overlay"],
    style: "floral",
    component: FloralCard,
  },
  {
    id: "FloralSlide14",
    label: "Floral 14 · Section",
    description:
      "Floral paper-texture section header — a left-anchored heading with botanicals massed down the right.",
    role: "section_header",
    roles: ["section_header", "overlay"],
    style: "floral",
    component: FloralCard,
  },
  {
    id: "FloralSlide15",
    label: "Floral 15 · Title",
    description:
      "Floral paper-texture closing title — a centered hero framed by a botanical border that settles inward.",
    role: "title",
    style: "floral",
    component: FloralCard,
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

/** Cards available for a given role (the designer filters its picker by role).
 *  A card advertises the roles it serves via `roles` (defaulting to `[role]`). */
export function cardsForRole(role: CardRole): readonly CardDefinition[] {
  return CARDS.filter((c) => (c.roles ?? [c.role]).includes(role));
}
