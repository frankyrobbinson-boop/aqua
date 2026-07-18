"use client";

/**
 * Render-settings panel + the shared config-panel helper components, extracted
 * from ProjectView so the render tab and the script-creation form ("Run full
 * pipeline" options) share the identical panel.
 */

// Background-music volume presets (linear gain of the bed under the narration).
// Values mirror backend defaults; "Low" (0.05) is the default. The bed plays at a
// flat low gain for the whole video (auto-ducking was removed by request; selective
// music swells are a future enhancement).
const MUSIC_VOLUME_PRESETS = [
  { label: "Low", value: 0.05 },
  { label: "Med", value: 0.08 },
  { label: "High", value: 0.12 },
] as const;

export function RenderConfigPanel({
  sectionTransitions,
  setSectionTransitions,
  sectionCards,
  setSectionCards,
  kenBurns,
  setKenBurns,
  music,
  setMusic,
  musicVolume,
  setMusicVolume,
}: {
  sectionTransitions: boolean;
  setSectionTransitions: (b: boolean) => void;
  sectionCards: boolean;
  setSectionCards: (b: boolean) => void;
  kenBurns: boolean;
  setKenBurns: (b: boolean) => void;
  music: boolean;
  setMusic: (b: boolean) => void;
  musicVolume: number;
  setMusicVolume: (v: number) => void;
}) {
  return (
    <ConfigPanel title="Render settings" badge="transitions wired">
      <div className="grid gap-4 sm:grid-cols-2">
        <ConfigRow label="Resolution" hint="1080p locked">
          <div className="flex gap-1">
            {["720p", "1080p"].map((r) => (
              <button
                key={r}
                type="button"
                disabled
                className={`flex-1 rounded-md px-3 py-1.5 text-sm ${
                  r === "1080p"
                    ? "bg-accent text-white"
                    : "border border-border bg-surface-2 text-muted"
                }`}
              >
                {r}
              </button>
            ))}
          </div>
        </ConfigRow>
        <ConfigRow label="Frame rate" hint="60 fps locked">
          <div className="flex gap-1">
            {["30", "60"].map((f) => (
              <button
                key={f}
                type="button"
                disabled
                className={`flex-1 rounded-md px-3 py-1.5 text-sm ${
                  f === "60"
                    ? "bg-accent text-white"
                    : "border border-border bg-surface-2 text-muted"
                }`}
              >
                {f} fps
              </button>
            ))}
          </div>
        </ConfigRow>
      </div>
      <PlaceholderToggle
        label="Subtitles"
        checked
        hint="Word-level highlight, burned in"
      />
      {/* Live (non-placeholder) controls — wired through to run_render.py. */}
      <LiveToggle
        label="Background music"
        checked={music}
        onChange={setMusic}
        hint="Plays songs from the music folder in filename order, low under the narration."
      />
      {music && (
        <div className="flex items-center justify-between gap-3 pl-1">
          <p className="text-sm text-muted">Volume</p>
          <div className="flex gap-1">
            {MUSIC_VOLUME_PRESETS.map(({ label, value }) => (
              <button
                key={label}
                type="button"
                onClick={() => setMusicVolume(value)}
                aria-pressed={musicVolume === value}
                className={`rounded-md px-3 py-1 text-xs ${
                  musicVolume === value
                    ? "bg-accent text-white"
                    : "border border-border bg-surface-2 text-muted hover:text-foreground"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      )}
      <LiveToggle
        label="Section transitions"
        checked={sectionTransitions}
        onChange={setSectionTransitions}
        hint="Automatic by significance — hard cut, blur-dissolve on subject shifts, fade-to-black at section beats."
      />
      <LiveToggle
        label="Section cards"
        checked={sectionCards}
        onChange={setSectionCards}
        hint="Floral section headers + mid-hook title card."
      />
      <LiveToggle
        label="Ken Burns"
        checked={kenBurns}
        onChange={setKenBurns}
        hint="Slow zoom on still images (PNG scenes only)"
      />
      <InfoBox>
        <strong className="text-foreground">Render pipeline:</strong> libx264 ·
        CRF 18 · scale+crop · libass subtitle burn-in · AAC audio mux.
      </InfoBox>
    </ConfigPanel>
  );
}

// ---------------------------------------------------------------------------
// Shared placeholder UI for stage config panels
// ---------------------------------------------------------------------------

export function ConfigPanel({
  title,
  badge,
  children,
}: {
  title: string;
  badge?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border bg-surface p-5">
      <div className="mb-4 flex items-baseline justify-between">
        <h2 className="text-sm font-medium text-foreground">{title}</h2>
        {badge && (
          <span className="rounded-full border border-border bg-surface-2 px-2 py-0.5 text-xs text-muted">
            {badge}
          </span>
        )}
      </div>
      <div className="space-y-4">{children}</div>
      <style>{`
        .config-select {
          width: 100%;
          padding: 0.5rem 0.75rem;
          background: var(--surface-2);
          color: var(--foreground);
          border: 1px solid var(--border);
          border-radius: 0.375rem;
          font-size: 0.875rem;
          outline: none;
        }
        .config-select:disabled { opacity: 0.6; cursor: not-allowed; }
      `}</style>
    </section>
  );
}

export function ConfigRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="opacity-70">
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <label className="text-sm font-medium text-foreground">{label}</label>
        {hint && <span className="text-xs text-muted">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

function PlaceholderToggle({
  label,
  checked,
  hint,
}: {
  label: string;
  checked: boolean;
  hint?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 opacity-70">
      <div>
        <p className="text-sm font-medium text-foreground">{label}</p>
        {hint && <p className="text-xs text-muted">{hint}</p>}
      </div>
      <button
        type="button"
        disabled
        className={`relative inline-flex h-6 w-11 cursor-not-allowed items-center rounded-full ${
          checked ? "bg-accent" : "bg-surface-3"
        }`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
            checked ? "translate-x-6" : "translate-x-1"
          }`}
        />
      </button>
    </div>
  );
}

/** Functional sibling of PlaceholderToggle — same visual, but clickable and
 *  controlled. Used for render options that are actually wired through. */
function LiveToggle({
  label,
  checked,
  onChange,
  hint,
}: {
  label: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  hint?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div>
        <p className="text-sm font-medium text-foreground">{label}</p>
        {hint && <p className="text-xs text-muted">{hint}</p>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 cursor-pointer items-center rounded-full transition-colors ${
          checked ? "bg-accent" : "bg-surface-3"
        }`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
            checked ? "translate-x-6" : "translate-x-1"
          }`}
        />
      </button>
    </div>
  );
}

export function InfoBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-surface-2 p-3 text-xs text-muted">
      {children}
    </div>
  );
}
