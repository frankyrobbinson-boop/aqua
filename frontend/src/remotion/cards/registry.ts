/**
 * Card registry — the UI source of truth for which title cards exist. The tab
 * builds its picker from `CARDS`; Root.tsx registers a <Composition> per entry.
 *
 * The backend's ALLOWED_COMPS frozenset (backend/api/routes/remotion.py) MIRRORS
 * `CARD_IDS` — keep the two in sync when adding or removing a card.
 */
import type { ComponentType } from "react";

import { GardenBand } from "./GardenBand";
import { GardenCentered } from "./GardenCentered";
import { GardenFramed } from "./GardenFramed";
import type { CardProps } from "./types";

export type CardDefinition = {
  id: string;
  label: string;
  description: string;
  component: ComponentType<CardProps>;
};

export const CARDS: readonly CardDefinition[] = [
  {
    id: "GardenCentered",
    label: "Centered",
    description: "Centered title with sparse floating botanicals.",
    component: GardenCentered,
  },
  {
    id: "GardenFramed",
    label: "Framed",
    description: "Botanical corner-vine frame around the title.",
    component: GardenFramed,
  },
  {
    id: "GardenBand",
    label: "Band",
    description: "Title above a lower botanical band.",
    component: GardenBand,
  },
];

export const CARD_IDS: readonly string[] = CARDS.map((c) => c.id);
